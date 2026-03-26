#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CozeLoop Hook for Claude Code

This hook integrates Claude Code with CozeLoop for tracing and observability.
It captures conversation interactions from the local .jsonl file and sends them
as traces to the CozeLoop platform.

Usage:
    1. Place this script in `~/.claude/hooks/cozeloop_hook.py`.
    2. Configure the hook in `~/.claude/settings.json`.
    3. Set environment variables `COZELOOP_WORKSPACE_ID` and `COZELOOP_API_TOKEN`
       in your project's `.claude/settings.local.json`.
    4. Run Claude Code as normal - traces will be sent automatically.
"""

import json
import os
import sys
import glob
import hashlib
from cozeloop.spec.tracespec import (
    Runtime, ModelInput, ModelMessage, ModelToolChoice,
    ModelOutput, ModelChoice
)
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

# --- SDK Import ---
try:
    import cozeloop
except ImportError:
    print("Error: cozeloop SDK not found. Please install it with: pip install cozeloop", file=sys.stderr)
    sys.exit(1)

# --- Configuration ---
DEBUG = os.environ.get("CC_COZELOOP_DEBUG", "").lower() == "true"

def debug_log(message: str):
    """Print debug message if debug mode is enabled."""
    if DEBUG:
        print(f"[COZELOOP_HOOK_DEBUG] {datetime.now().isoformat()} - {message}", file=sys.stderr)

# --- State Management (Similar to Fornax Hook) ---

def get_state_file_path(conversation_file: str) -> str:
    """Get the state file path for tracking processed messages."""
    state_dir = Path.home() / ".claude" / "cozeloop_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    file_hash = hashlib.md5(conversation_file.encode()).hexdigest()[:12]
    return str(state_dir / f"state_{file_hash}.json")

def load_state(state_file: str) -> Dict[str, Any]:
    """Load the processing state from file."""
    if os.path.exists(state_file):
        try:
            with open(state_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            debug_log(f"Error loading state: {e}")
    return {"last_processed_line": 0, "session_id": None}

def save_state(state_file: str, state: Dict[str, Any]):
    """Save the processing state to file."""
    try:
        with open(state_file, 'w') as f:
            json.dump(state, f, indent=2)
    except IOError as e:
        debug_log(f"Error saving state: {e}")

# --- Conversation File Handling (Similar to Fornax Hook) ---

def find_latest_conversation_file() -> Optional[str]:
    """Find the most recently modified conversation file in ~/.claude/projects/."""
    claude_dir = Path.home() / ".claude" / "projects"
    if not claude_dir.exists():
        debug_log(f"Claude projects directory not found: {claude_dir}")
        return None
    
    jsonl_files = list(claude_dir.rglob("*.jsonl"))
    if not jsonl_files:
        debug_log("No conversation files (*.jsonl) found.")
        return None
        
    latest_file = max(jsonl_files, key=lambda p: p.stat().st_mtime)
    debug_log(f"Found latest conversation file: {latest_file}")
    return str(latest_file)

def read_new_messages(file_path: str, start_line: int = 0) -> List[Dict[str, Any]]:
    """Read new messages from a conversation file since the last processed line."""
    messages = []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f):
                if i < start_line:
                    continue
                line = line.strip()
                if line:
                    try:
                        msg = json.loads(line)
                        msg['_line_number'] = i
                        messages.append(msg)
                    except json.JSONDecodeError:
                        debug_log(f"Skipping malformed JSON on line {i+1}")
    except (IOError, FileNotFoundError) as e:
        debug_log(f"Error reading conversation file: {e}")
    return messages

# --- Message Parsing and Grouping (Adapted from Fornax Hook) ---

def is_tool_result_message(msg: Dict[str, Any]) -> bool:
    """Check if a message is a tool_result (not a real user input)."""
    content = msg.get("message", {}).get("content", [])
    return isinstance(content, list) and any(item.get("type") == "tool_result" for item in content if isinstance(item, dict))

def extract_tool_results_from_message(msg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract tool_result items from a user message."""
    content = msg.get("message", {}).get("content", [])
    if isinstance(content, list):
        return [item for item in content if isinstance(item, dict) and item.get("type") == "tool_result"]
    return []

def group_messages_into_turns(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group messages into conversation turns."""
    turns = []
    current_turn = None
    for msg in messages:
        role = msg.get("message", {}).get("role", "")
        
        is_user_message = role == "user"
        
        if is_user_message:
            if is_tool_result_message(msg):
                if current_turn:
                    current_turn.setdefault("tool_results", []).extend(extract_tool_results_from_message(msg))
            else:
                if current_turn:
                    turns.append(current_turn)
                current_turn = {
                    "user_message": msg,
                    "assistant_messages": [],
                    "tool_calls": [],
                    "tool_results": [],
                    "_start_line": msg.get("_line_number", 0)
                }
        elif role == "assistant":
            if current_turn:
                current_turn["assistant_messages"].append(msg)
                content = msg.get("message", {}).get("content", [])
                if isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "tool_use":
                            current_turn.setdefault("tool_calls", []).append(item)
    
    if current_turn:
        turns.append(current_turn)
        
    return turns

# --- CozeLoop Trace Reporting ---

def is_empty_content(content: Any) -> bool:
    """Return True if content carries no meaningful data."""
    if content is None:
        return True
    if isinstance(content, str):
        return content.strip() == ""
    if isinstance(content, list):
        if len(content) == 0:
            return True
        if len(content) == 1 and isinstance(content[0], dict) and content[0].get("type") == "text" and content[0].get("text", "").strip() == "":
            return True

    return False

def format_content(content: Any, truncate: int = 4096) -> str:
    """Format message content for trace display."""
    if isinstance(content, str):
        return content[:truncate]
    if isinstance(content, dict):
        return json.dumps(content, ensure_ascii=False)[:truncate]
    if isinstance(content, list):
        return json.dumps(content, ensure_ascii=False)[:truncate]
    return str(content)[:truncate]

def send_turns_to_cozeloop(turns: List[Dict[str, Any]], session_id: str, history_turns: Optional[List[Dict[str, Any]]] = None):
    """Send grouped conversation turns to CozeLoop."""
    if not turns:
        return

    debug_log(f"Initializing CozeLoop client for session: {session_id}")
    # Client is initialized using environment variables by default
    client = cozeloop.new_client()

    try:
        with client.start_span(name="claude_code_request", span_type="main") as root_span:
            root_span.set_runtime(Runtime(library="claude-code"))
            root_span.set_tags({
                "session_id": session_id,
                "total_turns": len(turns),
                "source": "claude_code"
            })

            # Build cumulative history from previously processed turns
            history_messages: List[ModelMessage] = []
            for ht in (history_turns or []):
                ht_user = ht.get("user_message", {}).get("message", {})
                ht_user_content = ht_user.get("content") if ht_user else None
                if ht_user and not is_empty_content(ht_user_content):
                    history_messages.append(ModelMessage(
                        role="user",
                        content=format_content(ht_user_content),
                        reasoning_content="",
                        parts=[],
                        name="",
                        tool_calls=[],
                        tool_call_id="",
                        metadata={}
                    ))
                for msg in ht.get("assistant_messages", []):
                    asst_content = msg.get("message", {}).get("content")
                    if not is_empty_content(asst_content):
                        history_messages.append(ModelMessage(
                            role="assistant",
                            content=format_content(asst_content),
                            reasoning_content="",
                            parts=[],
                            name="",
                            tool_calls=[],
                            tool_call_id="",
                            metadata={}
                        ))

            for i, turn_data in enumerate(turns):
                # Create a turn span as child of root
                with client.start_span(name=f"claude_code_turn_{i}", span_type="main") as turn_span:
                    turn_span.set_runtime(Runtime(library="claude-code"))
                    turn_span.set_tags({
                        "session_id": session_id,
                        "turn_index": i,
                        "source": "claude_code",
                        "project": os.environ.get("CLAUDE_PROJECT_NAME", "unknown") # Example of custom tag
                    })

                    # User Input Span
                    user_message = turn_data.get("user_message", {}).get("message", {})
                    if user_message:
                        with client.start_span(name="user_input", span_type="query") as user_span:
                            user_span.set_runtime(Runtime(library="claude-code"))
                            user_span.set_input(format_content(user_message.get("content")))
                            user_span.set_tags({"role": "user"})

                    # Assistant Response Span
                    assistant_messages = turn_data.get("assistant_messages", [])
                    if assistant_messages:
                        with client.start_span(name="assistant_response", span_type="model") as assistant_span:
                            assistant_span.set_runtime(Runtime(library="claude-code"))
                            # Build output choices: each non-empty content item becomes a separate ModelChoice.
                            # text items -> ModelMessage(content=text)
                            # tool_use items -> ModelMessage(content=serialized tool_use json)
                            output_choices = []
                            choice_index = 0
                            for msg in assistant_messages:
                                raw_content = msg.get("message", {}).get("content", [])
                                if isinstance(raw_content, list):
                                    for item in raw_content:
                                        if not isinstance(item, dict):
                                            continue
                                        if item.get("type") == "text":
                                            text = item.get("text", "")
                                            if not text:
                                                continue
                                            output_choices.append(ModelChoice(
                                                finish_reason="",
                                                index=choice_index,
                                                message=ModelMessage(
                                                    role="assistant",
                                                    content=text,
                                                    reasoning_content="",
                                                    parts=[],
                                                    name="",
                                                    tool_calls=[],
                                                    tool_call_id="",
                                                    metadata={}
                                                )
                                            ))
                                            choice_index += 1
                                        elif item.get("type") == "tool_use":
                                            output_choices.append(ModelChoice(
                                                finish_reason="",
                                                index=choice_index,
                                                message=ModelMessage(
                                                    role="assistant",
                                                    content=json.dumps(item, ensure_ascii=False),
                                                    reasoning_content="",
                                                    parts=[],
                                                    name="",
                                                    tool_calls=[],
                                                    tool_call_id="",
                                                    metadata={}
                                                )
                                            ))
                                            choice_index += 1
                                elif isinstance(raw_content, str) and raw_content:
                                    output_choices.append(ModelChoice(
                                        finish_reason="",
                                        index=choice_index,
                                        message=ModelMessage(
                                            role="assistant",
                                            content=raw_content,
                                            reasoning_content="",
                                            parts=[],
                                            name="",
                                            tool_calls=[],
                                            tool_call_id="",
                                            metadata={}
                                        )
                                    ))
                                    choice_index += 1
                            # Build model input: history messages + current user message (skip if empty)
                            user_raw_content = user_message.get("content")
                            input_messages = list(history_messages)
                            if not is_empty_content(user_raw_content):
                                current_user_msg = ModelMessage(
                                    role="user",
                                    content=format_content(user_raw_content),
                                    reasoning_content="",
                                    parts=[],
                                    name="",
                                    tool_calls=[],
                                    tool_call_id="",
                                    metadata={}
                                )
                                input_messages.append(current_user_msg)
                            assistant_span.set_input(ModelInput(
                                messages=input_messages,
                                tools=[],
                                tool_choice=ModelToolChoice(type="", function=None)
                            ))
                            assistant_span.set_output(ModelOutput(choices=output_choices))
                            assistant_span.set_tags({"role": "assistant"})
                            # Accumulate token usage across all assistant messages in this turn
                            total_input_tokens = sum(
                                msg.get("message", {}).get("usage", {}).get("input_tokens", 0)
                                for msg in assistant_messages
                            )
                            total_output_tokens = sum(
                                msg.get("message", {}).get("usage", {}).get("output_tokens", 0)
                                for msg in assistant_messages
                            )
                            if total_input_tokens > 0:
                                assistant_span.set_input_tokens(total_input_tokens)
                            if total_output_tokens > 0:
                                assistant_span.set_output_tokens(total_output_tokens)

                    # Tool Spans
                    tool_calls = turn_data.get("tool_calls", [])
                    tool_results = turn_data.get("tool_results", [])

                    for tool_call in tool_calls:
                        tool_name = tool_call.get("name", "unknown_tool")
                        tool_id = tool_call.get("id")
                        with client.start_span(name=f"tool_{tool_name}", span_type="tool") as tool_span:
                            tool_span.set_runtime(Runtime(library="claude-code"))
                            tool_span.set_input(format_content(tool_call.get("input")))
                            tool_span.set_tags({
                                "tool_name": tool_name,
                                "tool_id": tool_id
                            })

                            # Find matching tool result
                            matching_result = next((res for res in tool_results if res.get("tool_use_id") == tool_id), None)
                            if matching_result:
                                tool_span.set_output(format_content(matching_result.get("content")))
                                if matching_result.get("is_error"):
                                    tool_span.set_status_code(1) # Using 1 for error
                                    tool_span.set_error(Exception(format_content(matching_result.get("content"))))

                    # Append current turn to history for subsequent turns
                    if user_message and not is_empty_content(user_message.get("content")):
                        history_messages.append(ModelMessage(
                            role="user",
                            content=format_content(user_message.get("content")),
                            reasoning_content="",
                            parts=[],
                            name="",
                            tool_calls=[],
                            tool_call_id="",
                            metadata={}
                        ))
                    for msg in assistant_messages:
                        asst_content = msg.get("message", {}).get("content")
                        if not is_empty_content(asst_content):
                            history_messages.append(ModelMessage(
                                role="assistant",
                                content=format_content(asst_content),
                                reasoning_content="",
                                parts=[],
                                name="",
                                tool_calls=[],
                                tool_call_id="",
                                metadata={}
                            ))

        debug_log(f"Successfully processed {len(turns)} turn(s) for session {session_id}")

    except Exception as e:
        debug_log(f"An error occurred while sending traces to CozeLoop: {e}")
    finally:
        # Crucial: close the client to ensure all buffered traces are sent.
        client.close()
        debug_log("CozeLoop client closed.")


# --- Main Execution ---

def main():
    """Main entry point for the hook script."""
    debug_log("Hook started.")

    # Check if tracing is enabled
    if os.environ.get("TRACE_TO_COZELOOP", "").lower() == "false":
        debug_log("TRACE_TO_COZELOOP is set to 'false', skipping")
        return

    # Find the latest conversation file
    conversation_file = find_latest_conversation_file()
    if not conversation_file:
        debug_log("Execution skipped: No conversation file found.")
        return

    # Load state to know where to start reading
    state_file = get_state_file_path(conversation_file)
    state = load_state(state_file)
    last_processed_line = state.get("last_processed_line", 0)

    # Read new messages from the file
    new_messages = read_new_messages(conversation_file, last_processed_line)
    if not new_messages:
        debug_log("No new messages to process.")
        return

    debug_log(f"Found {len(new_messages)} new messages.")

    # Determine Session ID
    session_id = state.get("session_id")
    if not session_id:
        # Create a new session ID if one doesn't exist
        session_id = f"claude-code-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
        debug_log(f"Generated new session ID: {session_id}")
    state["session_id"] = session_id

    # Read historical messages to build context for model input
    history_turns = []
    if last_processed_line > 0:
        historical_messages = read_new_messages(conversation_file, 0)
        historical_messages = [m for m in historical_messages if m.get("_line_number", 0) < last_processed_line]
        history_turns = group_messages_into_turns(historical_messages)
        debug_log(f"Loaded {len(history_turns)} historical turn(s) for context.")

    # Group messages into turns and send to CozeLoop
    turns = group_messages_into_turns(new_messages)
    if turns:
        send_turns_to_cozeloop(turns, session_id, history_turns)
        
        # Update state with the new last processed line number
        last_line_in_batch = max(msg.get("_line_number", 0) for msg in new_messages)
        state["last_processed_line"] = last_line_in_batch + 1
        save_state(state_file, state)
        debug_log(f"State updated. Last processed line: {state['last_processed_line']}")

    debug_log("Hook finished.")

if __name__ == "__main__":
    main()
