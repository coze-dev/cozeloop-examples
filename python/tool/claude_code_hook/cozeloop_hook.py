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
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

# --- SDK Import ---
try:
    import cozeloop
    from cozeloop.spec.tracespec import (
        Runtime, ModelInput, ModelMessage, ModelToolChoice,
        ModelOutput, ModelChoice, ModelToolCall, ModelToolCallFunction,
        ModelMessagePart, ModelMessagePartType
    )
except ImportError:
    print("Error: cozeloop SDK not found. Please install it with: pip install cozeloop", file=sys.stderr)
    sys.exit(1)

# --- Configuration ---
DEBUG = os.environ.get("CC_COZELOOP_DEBUG", "").lower() == "true"

def debug_log(message: str):
    """Print debug message if debug mode is enabled."""
    if DEBUG:
        print(f"[COZELOOP_HOOK_DEBUG] {datetime.now().isoformat()} - {message}", file=sys.stderr)

# --- State Management ---

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

# --- Conversation File Handling ---

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

# --- Content Helpers ---

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


# --- Message Parsing and Grouping ---

def is_tool_result_message(msg: Dict[str, Any]) -> bool:
    """Check if a message is a tool_result (not a real user input)."""
    content = msg.get("message", {}).get("content", [])
    return isinstance(content, list) and any(
        isinstance(item, dict) and item.get("type") == "tool_result"
        for item in content
    )

def extract_tool_result_from_message(msg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract tool_result items from a user message."""
    content = msg.get("message", {}).get("content", [])
    if isinstance(content, list):
        return [item for item in content if isinstance(item, dict) and item.get("type") == "tool_result"]
    return []


def _extract_progress_inner_message(msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract the inner conversation message from a progress (sub-agent) message.

    Progress messages have the inner message nested at data.message.message.
    Returns a dict with keys: role, content, id, parentToolUseID, or None if not valid.
    """
    data = msg.get("data", {})
    outer_msg = data.get("message", {})
    inner_msg = outer_msg.get("message", {})
    if not inner_msg:
        return None

    role = inner_msg.get("role")
    content = inner_msg.get("content")
    if not role or content is None:
        return None

    return {
        "role": role,
        "content": content,
        "id": inner_msg.get("id"),
        "usage": inner_msg.get("usage", {}),
        "model": inner_msg.get("model"),
        "parentToolUseID": msg.get("parentToolUseID"),
        "agentId": data.get("agentId", ""),
    }


def _group_subagent_steps(progress_msgs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group sub-agent progress messages into steps (same logic as top-level).

    Each step is an assistant message (model call) + its tool_calls + tool_results.
    Returns list of steps in the same format as turn["steps"], but with simplified
    assistant_message structure.
    """
    steps = []

    for pmsg in progress_msgs:
        role = pmsg.get("role")
        content = pmsg.get("content", [])

        if role == "user":
            # Could be tool_result or user input for the sub-agent
            if isinstance(content, list):
                has_tool_result = any(
                    isinstance(item, dict) and item.get("type") == "tool_result"
                    for item in content
                )
                if has_tool_result and steps:
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "tool_result":
                            steps[-1]["tool_results"].append(item)
            # Skip non-tool-result user messages (sub-agent prompt)
            continue

        if role == "assistant":
            tool_calls = []
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "tool_use":
                        tool_calls.append(item)

            msg_id = pmsg.get("id")
            last_step = steps[-1] if steps else None
            last_msg_id = last_step.get("_msg_id") if last_step else None

            if last_step and msg_id and msg_id == last_msg_id:
                # Same API response — merge
                existing = last_step["assistant_message"].get("message", {}).get("content", [])
                if isinstance(existing, list) and isinstance(content, list):
                    existing.extend(content)
                last_step["tool_calls"].extend(tool_calls)
                usage = pmsg.get("usage", {})
                if usage.get("input_tokens", 0) > 0 or usage.get("output_tokens", 0) > 0:
                    last_step["assistant_message"]["message"]["usage"] = usage
            else:
                steps.append({
                    "assistant_message": {
                        "message": {
                            "role": "assistant",
                            "content": content,
                            "id": msg_id,
                            "model": pmsg.get("model", ""),
                            "usage": pmsg.get("usage", {}),
                        }
                    },
                    "tool_calls": tool_calls,
                    "tool_results": [],
                    "_msg_id": msg_id,
                })

    return steps


def group_messages_into_turns(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group messages into conversation turns (user -> assistant -> tool_results).

    A turn represents a complete interaction cycle starting from a real user input.
    Within each turn, we track individual "steps" -- each step is a single model
    invocation (assistant message) paired with the tool_results it triggered.

    This captures the full chain:
      user_input -> model_call_1 (tool_use) -> tool_result -> model_call_2 (tool_use)
      -> tool_result -> ... -> model_call_N (final text)

    Each step has:
      - assistant_message: the assistant's response (one API call)
      - tool_calls: tool_use items from this assistant message
      - tool_results: matching tool_result items from the following user message(s)

    Sub-agent (Task tool) progress messages are parsed and stored as
    sub_steps on the step containing the parent tool call.
    """
    turns = []
    current_turn = None

    # First pass: collect progress messages grouped by parentToolUseID,
    # and collect toolUseResult usage keyed by tool_use_id.
    subagent_progress: Dict[str, List[Dict[str, Any]]] = {}
    tool_use_result_usage: Dict[str, Dict[str, Any]] = {}
    for msg in messages:
        if msg.get("type") == "progress":
            inner = _extract_progress_inner_message(msg)
            if inner and inner.get("parentToolUseID"):
                parent_id = inner["parentToolUseID"]
                if parent_id not in subagent_progress:
                    subagent_progress[parent_id] = []
                subagent_progress[parent_id].append(inner)
        # Collect toolUseResult usage from tool_result messages
        tur = msg.get("toolUseResult")
        if isinstance(tur, dict) and tur.get("usage"):
            message = msg.get("message", {})
            content = message.get("content", [])
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "tool_result":
                        tid = item.get("tool_use_id", "")
                        if tid:
                            tool_use_result_usage[tid] = tur["usage"]

    # Second pass: build turns from user/assistant messages
    for msg in messages:
        msg_type = msg.get("type")
        role = msg.get("role")
        message = msg.get("message", {})
        message_role = message.get("role", "")

        # Skip non-conversation messages
        if msg_type in ("progress", "system", "file-history-snapshot"):
            continue

        # Check if this is a user message
        is_user_msg = msg_type == "user" or role == "user" or message_role == "user"

        if is_user_msg:
            # Check if this is a tool_result message (should not start a new turn)
            if is_tool_result_message(msg):
                # Attach tool results to the last step of the current turn
                if current_turn and current_turn["steps"]:
                    tool_results = extract_tool_result_from_message(msg)
                    current_turn["steps"][-1]["tool_results"].extend(tool_results)
            else:
                # This is a real user input, start a new turn
                if current_turn:
                    turns.append(current_turn)
                current_turn = {
                    "user_message": msg,
                    "steps": [],
                    "start_line": msg.get("_line_number", 0)
                }
        elif msg_type == "assistant" or role == "assistant" or message_role == "assistant":
            if current_turn:
                # Extract tool_use items from this line's content
                tool_calls = []
                content = message.get("content", [])
                if isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "tool_use":
                            tool_calls.append(item)

                # Claude Code writes text and tool_use from the same API response
                # as separate JSONL lines sharing the same message.id.
                # Merge them into a single step.
                msg_id = message.get("id")
                last_step = current_turn["steps"][-1] if current_turn["steps"] else None
                last_msg_id = (last_step["assistant_message"].get("message", {}).get("id")
                               if last_step else None)

                if last_step and msg_id and msg_id == last_msg_id:
                    # Same API response — merge content into the existing step
                    existing_content = last_step["assistant_message"].get("message", {}).get("content", [])
                    if isinstance(existing_content, list) and isinstance(content, list):
                        existing_content.extend(content)
                    last_step["tool_calls"].extend(tool_calls)
                    # Carry over usage from the later line (earlier line typically has zeros)
                    usage = message.get("usage", {})
                    if usage.get("input_tokens", 0) > 0 or usage.get("output_tokens", 0) > 0:
                        last_step["assistant_message"]["message"]["usage"] = usage
                else:
                    # New API response — create a new step
                    current_turn["steps"].append({
                        "assistant_message": msg,
                        "tool_calls": tool_calls,
                        "tool_results": [],
                    })

    # Don't forget the last turn
    if current_turn:
        turns.append(current_turn)

    # Third pass: attach sub-agent steps, agentId, and total usage to their parent tool calls
    for turn in turns:
        for step in turn["steps"]:
            for tc in step["tool_calls"]:
                tool_id = tc.get("id", "")
                if tool_id in subagent_progress:
                    progress_msgs = subagent_progress[tool_id]
                    tc["_sub_steps"] = _group_subagent_steps(progress_msgs)
                    # Extract agentId (same for all messages under this parent)
                    for pm in progress_msgs:
                        if pm.get("agentId"):
                            tc["_agent_id"] = pm["agentId"]
                            break
                    # Attach total usage from toolUseResult for token distribution
                    if tool_id in tool_use_result_usage:
                        tc["_total_usage"] = tool_use_result_usage[tool_id]

    return turns


# --- CozeLoop Message Helpers ---

def _make_message(role: str, content: str = "", tool_calls: list = None,
                   tool_call_id: str = "", parts: list = None) -> ModelMessage:
    """Helper to create a CozeLoop ModelMessage with default fields."""
    return ModelMessage(
        role=role,
        content=content,
        reasoning_content="",
        parts=parts or [],
        name="",
        tool_calls=tool_calls or [],
        tool_call_id=tool_call_id or "",
        metadata={}
    )


def _format_tool_output(result_content: Any, max_len: int = 2000) -> str:
    """Format tool result content for span output.

    When content is a list (e.g. Task tool results with multiple text blocks),
    extract and join text parts instead of dumping raw JSON.
    """
    if isinstance(result_content, str):
        if len(result_content) > max_len:
            return result_content[:max_len] + "..."
        return result_content

    if isinstance(result_content, list):
        text_parts = []
        for item in result_content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
                else:
                    # Non-text items: serialize compactly
                    text_parts.append(json.dumps(item, ensure_ascii=False))
            elif isinstance(item, str):
                text_parts.append(item)
        joined = "\n".join(text_parts)
        if len(joined) > max_len:
            return joined[:max_len] + "..."
        return joined

    s = str(result_content)
    if len(s) > max_len:
        return s[:max_len] + "..."
    return s


def _make_tool_result_message(result_content: Any, tool_call_id: str = "") -> ModelMessage:
    """Create a role='tool' ModelMessage for model input.

    When result_content is a list, items go into parts (not content) to avoid
    dumping raw JSON into the content field.
    """
    if isinstance(result_content, list):
        parts_list = []
        for item in result_content:
            if isinstance(item, dict):
                item_type = item.get("type", "text")
                if item_type == "text":
                    parts_list.append(ModelMessagePart(type=ModelMessagePartType.TEXT, text=item.get("text", "")))
                else:
                    parts_list.append(ModelMessagePart(
                        type=ModelMessagePartType.TEXT,
                        text=json.dumps(item, ensure_ascii=False)[:4096]
                    ))
            elif isinstance(item, str):
                parts_list.append(ModelMessagePart(type=ModelMessagePartType.TEXT, text=item))
        return _make_message(
            role="tool",
            content="",
            tool_call_id=tool_call_id,
            parts=parts_list
        )

    # String or other scalar
    return _make_message(
        role="tool",
        content=format_content(result_content),
        tool_call_id=tool_call_id
    )


def _raw_content_to_input_message(raw_content: Any, role: str) -> List[ModelMessage]:
    """Convert raw Claude content to CozeLoop ModelMessage(s) suitable for model input.

    When content is a list:
    - tool_use items -> ModelMessage.tool_calls (as ModelToolCall objects)
    - tool_result items -> separate ModelMessage(role="tool") per result
    - all other items (text, etc.) -> ModelMessage.parts (as ModelMessagePart objects)
    - ModelMessage.content = empty when parts are used (avoid duplication)

    When content is a string:
    - Simple ModelMessage with content
    """
    if isinstance(raw_content, str):
        return [_make_message(role, format_content(raw_content))]

    if not isinstance(raw_content, list):
        return [_make_message(role, format_content(raw_content))]

    # Check if content is all tool_result items
    all_tool_results = all(
        isinstance(item, dict) and item.get("type") == "tool_result"
        for item in raw_content if isinstance(item, dict)
    ) and any(
        isinstance(item, dict) and item.get("type") == "tool_result"
        for item in raw_content
    )

    if all_tool_results:
        messages = []
        for item in raw_content:
            if isinstance(item, dict) and item.get("type") == "tool_result":
                result_content = item.get("content", "")
                messages.append(_make_tool_result_message(
                    result_content,
                    tool_call_id=item.get("tool_use_id", "")
                ))
        return messages

    # Mixed content: split into tool_calls, parts, and text
    tc_list = []
    parts_list = []
    text_parts = []

    for item in raw_content:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type", "")

        if item_type == "tool_use":
            tc_list.append(ModelToolCall(
                id=item.get("id", ""),
                type="function",
                function=ModelToolCallFunction(
                    name=item.get("name", ""),
                    arguments=json.dumps(item.get("input", {}), ensure_ascii=False) if isinstance(item.get("input"), dict) else str(item.get("input", ""))
                )
            ))
        elif item_type == "text":
            t = item.get("text", "")
            if t:
                text_parts.append(t)
                parts_list.append(ModelMessagePart(type=ModelMessagePartType.TEXT, text=t))
        else:
            # Any other type goes into parts as text (serialized)
            parts_list.append(ModelMessagePart(
                type=ModelMessagePartType.TEXT,
                text=json.dumps(item, ensure_ascii=False)[:4096]
            ))

    # When parts are used, content should be empty to avoid duplication
    content_text = "" if parts_list else "\n".join(text_parts)
    return [_make_message(
        role=role,
        content=content_text,
        tool_calls=tc_list if tc_list else None,
        parts=parts_list if parts_list else None
    )]


def _build_history_messages(history_turns: List[Dict[str, Any]]) -> list:
    """Build cumulative history messages from previously processed turns."""
    history_messages = []
    for ht in (history_turns or []):
        ht_user = ht.get("user_message", {}).get("message", {})
        ht_user_content = ht_user.get("content") if ht_user else None
        if ht_user and not is_empty_content(ht_user_content):
            history_messages.append(_make_message("user", format_content(ht_user_content)))
        for step in ht.get("steps", []):
            msg = step.get("assistant_message", {})
            asst_content = msg.get("message", {}).get("content")
            if not is_empty_content(asst_content):
                history_messages.extend(_raw_content_to_input_message(asst_content, "assistant"))
            for tr in step.get("tool_results", []):
                tr_content = tr.get("content", "")
                history_messages.append(_make_tool_result_message(
                    tr_content,
                    tool_call_id=tr.get("tool_use_id", "")
                ))
    return history_messages


# --- CozeLoop Trace Reporting ---

def send_turns_to_cozeloop(turns: List[Dict[str, Any]], session_id: str, history_turns: Optional[List[Dict[str, Any]]] = None):
    """Send conversation turns to CozeLoop.

    Span hierarchy:
      root_span (claude_code_request) [input=user_input, output=final_response]
        +-- turn_span
              |-- model_span (1st model call)
              |-- tool_span / agent_span (tool call from 1st model response)
              |-- model_span (2nd model call, after receiving tool result)
              |-- tool_span / agent_span (tool call from 2nd model response)
              |-- ...
              +-- model_span (Nth model call, final text response)
    """
    if not turns:
        return

    debug_log(f"Initializing CozeLoop client for session: {session_id}")
    client = cozeloop.new_client()

    try:
        with client.start_span(name="claude_code_request", span_type="main") as root_span:
            root_span.set_runtime(Runtime(library="claude-code"))
            root_span.set_tags({
                "thread_id": session_id,
                "total_turns": len(turns),
                "source": "claude_code"
            })
            root_span.set_baggage({
                "thread_id": session_id,
            })

            # Set root span input: first user message across all turns
            first_user_content = None
            for turn in turns:
                um = turn.get("user_message", {}).get("message", {})
                uc = um.get("content") if um else None
                if not is_empty_content(uc):
                    first_user_content = uc
                    break
            if first_user_content is not None:
                root_span.set_input(format_content(first_user_content))

            # Build cumulative history from previously processed turns
            history_messages = _build_history_messages(history_turns)

            # Process each turn as a child span under the root
            for i, turn in enumerate(turns):
                try:
                    steps = turn.get("steps", [])
                    total_steps = len(steps)

                    with client.start_span(name=f"turn_{i}", span_type="main") as turn_span:
                        turn_span.set_runtime(Runtime(library="claude-code"))
                        turn_span.set_tags({
                            "thread_id": session_id,
                            "turn_index": i,
                            "total_steps": total_steps,
                            "source": "claude_code",
                        })

                        # Extract user input for this turn
                        user_message = turn.get("user_message", {}).get("message", {})
                        user_raw_content = user_message.get("content") if user_message else None

                        # Build input context for the first model call in this turn
                        input_messages = list(history_messages)
                        if not is_empty_content(user_raw_content):
                            input_messages.append(_make_message("user", format_content(user_raw_content)))

                        # Process each step: model_span + tool_spans
                        for j, step in enumerate(steps):
                            assistant_msg = step.get("assistant_message", {})
                            assistant_message_obj = assistant_msg.get("message", {})
                            raw_content = assistant_message_obj.get("content", [])
                            model_name = assistant_message_obj.get("model", "claude-code")

                            # --- Create model span for this step ---
                            with client.start_span(name=f"model_call_{j}", span_type="model") as model_span:
                                model_span.set_runtime(Runtime(library="claude-code"))
                                model_span.set_model_name(model_name)

                                # Set input: accumulated context up to this point
                                model_span.set_input(ModelInput(
                                    messages=list(input_messages),
                                    tools=[],
                                    tool_choice=ModelToolChoice(type="", function=None)
                                ))

                                # Build output: text -> parts, tool_use -> tool_calls
                                text_parts = []
                                tool_call_list = []
                                parts_list = []
                                if isinstance(raw_content, list):
                                    for item in raw_content:
                                        if not isinstance(item, dict):
                                            continue
                                        item_type = item.get("type", "")
                                        if item_type == "text":
                                            text = item.get("text", "")
                                            if text:
                                                text_parts.append(text)
                                                parts_list.append(ModelMessagePart(type=ModelMessagePartType.TEXT, text=text))
                                        elif item_type == "tool_use":
                                            tool_call_list.append(ModelToolCall(
                                                id=item.get("id", ""),
                                                type="function",
                                                function=ModelToolCallFunction(
                                                    name=item.get("name", ""),
                                                    arguments=json.dumps(item.get("input", {}), ensure_ascii=False) if isinstance(item.get("input"), dict) else str(item.get("input", ""))
                                                )
                                            ))
                                        else:
                                            parts_list.append(ModelMessagePart(
                                                type=ModelMessagePartType.TEXT,
                                                text=json.dumps(item, ensure_ascii=False)[:4096]
                                            ))
                                elif isinstance(raw_content, str) and raw_content:
                                    text_parts.append(raw_content)

                                content_text = "" if parts_list else ("\n".join(text_parts) if text_parts else "")
                                finish_reason = "tool_calls" if tool_call_list else "stop"

                                output_choice = ModelChoice(
                                    finish_reason=finish_reason,
                                    index=0,
                                    message=ModelMessage(
                                        role="assistant",
                                        content=content_text,
                                        reasoning_content="",
                                        parts=parts_list,
                                        name="",
                                        tool_calls=tool_call_list if tool_call_list else [],
                                        tool_call_id="",
                                        metadata={}
                                    )
                                )

                                model_span.set_output(ModelOutput(choices=[output_choice]))

                                # Set token usage for this specific model call
                                usage = assistant_message_obj.get("usage", {})
                                input_tokens = usage.get("input_tokens", 0)
                                output_tokens = usage.get("output_tokens", 0)
                                cache_creation = usage.get("cache_creation_input_tokens", 0)
                                cache_read = usage.get("cache_read_input_tokens", 0)
                                if input_tokens > 0 or cache_creation > 0 or cache_read > 0:
                                    model_span.set_input_tokens(input_tokens + cache_creation + cache_read)
                                if output_tokens > 0:
                                    model_span.set_output_tokens(output_tokens)

                            # Add this assistant message to context for subsequent steps
                            if not is_empty_content(raw_content):
                                input_messages.extend(_raw_content_to_input_message(raw_content, "assistant"))

                            # --- Create tool spans for each tool call in this step ---
                            for tool_call in step.get("tool_calls", []):
                                tool_name = tool_call.get('name', 'unknown')
                                sub_steps = tool_call.get("_sub_steps", [])
                                agent_id = tool_call.get("_agent_id", "")
                                is_agent = bool(sub_steps)

                                # Task tool with sub-agent steps uses "agent" span type
                                span_type = "agent" if is_agent else "tool"
                                span_name = f"agent_{tool_name}" if is_agent else f"tool_{tool_name}"

                                with client.start_span(name=span_name, span_type=span_type) as tool_span:
                                    tool_span.set_runtime(Runtime(library="claude-code"))
                                    tags = {
                                        "tool_name": tool_name,
                                        "tool_call_id": tool_call.get("id"),
                                        "step_index": j,
                                    }
                                    if is_agent:
                                        tags["agent_name"] = agent_id
                                    tool_span.set_tags(tags)
                                    tool_span.set_input(
                                        json.dumps(tool_call.get("input", {}), ensure_ascii=False)[:2000]
                                    )

                                    # Find matching tool result
                                    tool_id = tool_call.get("id")
                                    for result in step.get("tool_results", []):
                                        if result.get("tool_use_id") == tool_id:
                                            result_content = result.get("content", "")
                                            tool_span.set_output(_format_tool_output(result_content))
                                            break

                                    # If this tool call has sub-agent steps (e.g. Task tool),
                                    # create child spans for each sub-agent model call and tool call.
                                    if sub_steps:
                                        # Initialize sub-agent input with the prompt (first user message)
                                        sub_input_messages = []
                                        task_prompt = tool_call.get("input", {}).get("prompt", "")
                                        if task_prompt:
                                            sub_input_messages.append(_make_message("user", format_content(task_prompt)))

                                        # Distribute total usage evenly across sub-agent model steps.
                                        total_usage = tool_call.get("_total_usage", {})
                                        total_in = (total_usage.get("input_tokens", 0)
                                                    + total_usage.get("cache_creation_input_tokens", 0)
                                                    + total_usage.get("cache_read_input_tokens", 0))
                                        total_out = total_usage.get("output_tokens", 0)
                                        n_model_steps = len(sub_steps)
                                        per_step_in = total_in // n_model_steps if n_model_steps > 0 else 0
                                        per_step_out = total_out // n_model_steps if n_model_steps > 0 else 0
                                        # Give remainder to the last step
                                        remainder_in = total_in - per_step_in * n_model_steps if n_model_steps > 0 else 0
                                        remainder_out = total_out - per_step_out * n_model_steps if n_model_steps > 0 else 0

                                        for sk, sub_step in enumerate(sub_steps):
                                            sub_asst = sub_step.get("assistant_message", {}).get("message", {})
                                            sub_content = sub_asst.get("content", [])
                                            sub_model = sub_asst.get("model") or "claude-code"

                                            # Sub-agent model span
                                            with client.start_span(name=f"subagent_model_{sk}", span_type="model") as sub_model_span:
                                                sub_model_span.set_runtime(Runtime(library="claude-code"))
                                                sub_model_span.set_model_name(sub_model)
                                                sub_model_span.set_tags({"agent_name": agent_id})

                                                # Set input: accumulated sub-agent context
                                                sub_model_span.set_input(ModelInput(
                                                    messages=list(sub_input_messages),
                                                    tools=[],
                                                    tool_choice=ModelToolChoice(type="", function=None)
                                                ))

                                                # Build output for sub-agent model call
                                                sub_text_parts = []
                                                sub_tc_list = []
                                                sub_parts_list = []
                                                if isinstance(sub_content, list):
                                                    for item in sub_content:
                                                        if not isinstance(item, dict):
                                                            continue
                                                        item_type = item.get("type", "")
                                                        if item_type == "text":
                                                            t = item.get("text", "")
                                                            if t:
                                                                sub_text_parts.append(t)
                                                                sub_parts_list.append(ModelMessagePart(type=ModelMessagePartType.TEXT, text=t))
                                                        elif item_type == "tool_use":
                                                            sub_tc_list.append(ModelToolCall(
                                                                id=item.get("id", ""),
                                                                type="function",
                                                                function=ModelToolCallFunction(
                                                                    name=item.get("name", ""),
                                                                    arguments=json.dumps(item.get("input", {}), ensure_ascii=False) if isinstance(item.get("input"), dict) else str(item.get("input", ""))
                                                                )
                                                            ))
                                                        else:
                                                            sub_parts_list.append(ModelMessagePart(
                                                                type=ModelMessagePartType.TEXT,
                                                                text=json.dumps(item, ensure_ascii=False)[:4096]
                                                            ))

                                                sub_content_text = "" if sub_parts_list else ("\n".join(sub_text_parts) if sub_text_parts else "")
                                                sub_finish = "tool_calls" if sub_tc_list else "stop"
                                                sub_model_span.set_output(ModelOutput(choices=[ModelChoice(
                                                    finish_reason=sub_finish,
                                                    index=0,
                                                    message=ModelMessage(
                                                        role="assistant",
                                                        content=sub_content_text,
                                                        reasoning_content="",
                                                        parts=sub_parts_list,
                                                        name="",
                                                        tool_calls=sub_tc_list if sub_tc_list else [],
                                                        tool_call_id="",
                                                        metadata={}
                                                    )
                                                )]))

                                                # Distribute tokens evenly; remainder goes to last step
                                                step_in = per_step_in + (remainder_in if sk == n_model_steps - 1 else 0)
                                                step_out = per_step_out + (remainder_out if sk == n_model_steps - 1 else 0)
                                                if step_in > 0:
                                                    sub_model_span.set_input_tokens(step_in)
                                                if step_out > 0:
                                                    sub_model_span.set_output_tokens(step_out)

                                            # Add assistant output to sub-agent context
                                            if not is_empty_content(sub_content):
                                                sub_input_messages.extend(
                                                    _raw_content_to_input_message(sub_content, "assistant")
                                                )

                                            # Sub-agent tool spans
                                            for sub_tc in sub_step.get("tool_calls", []):
                                                with client.start_span(name=f"tool_{sub_tc.get('name', 'unknown')}", span_type="tool") as sub_tool_span:
                                                    sub_tool_span.set_tags({
                                                        "tool_name": sub_tc.get("name"),
                                                        "tool_call_id": sub_tc.get("id"),
                                                        "agent_name": agent_id,
                                                    })
                                                    sub_tool_span.set_runtime(Runtime(library="claude-code"))
                                                    sub_tool_span.set_input(
                                                        json.dumps(sub_tc.get("input", {}), ensure_ascii=False)[:2000]
                                                    )

                                                    sub_tool_id = sub_tc.get("id")
                                                    for sub_result in sub_step.get("tool_results", []):
                                                        if sub_result.get("tool_use_id") == sub_tool_id:
                                                            sr_content = sub_result.get("content", "")
                                                            sub_tool_span.set_output(_format_tool_output(sr_content))
                                                            break

                                            # Add tool results to sub-agent context
                                            for sub_result in sub_step.get("tool_results", []):
                                                sr_content = sub_result.get("content", "")
                                                sub_input_messages.append(_make_tool_result_message(
                                                    sr_content,
                                                    tool_call_id=sub_result.get("tool_use_id", "")
                                                ))

                            # Add tool results to context for subsequent model calls
                            for result in step.get("tool_results", []):
                                result_content = result.get("content", "")
                                input_messages.append(_make_tool_result_message(
                                    result_content,
                                    tool_call_id=result.get("tool_use_id", "")
                                ))

                        # Append this turn's messages to history for subsequent turns
                        if user_message and not is_empty_content(user_message.get("content")):
                            history_messages.append(_make_message(
                                "user", format_content(user_message.get("content"))
                            ))
                        for step in steps:
                            msg = step.get("assistant_message", {})
                            asst_content = msg.get("message", {}).get("content")
                            if not is_empty_content(asst_content):
                                history_messages.extend(_raw_content_to_input_message(asst_content, "assistant"))
                            for tr in step.get("tool_results", []):
                                tr_content = tr.get("content", "")
                                history_messages.append(_make_tool_result_message(
                                    tr_content,
                                    tool_call_id=tr.get("tool_use_id", "")
                                ))

                except Exception as e:
                    debug_log(f"Error processing turn {i}: {e}")
                    continue

            # Set root span output: last assistant text from the last step of the last turn
            last_output = None
            for turn in reversed(turns):
                for step in reversed(turn.get("steps", [])):
                    asst = step.get("assistant_message", {}).get("message", {})
                    content = asst.get("content", [])
                    if isinstance(content, list):
                        text_parts = [
                            item.get("text", "")
                            for item in content
                            if isinstance(item, dict) and item.get("type") == "text" and item.get("text")
                        ]
                        if text_parts:
                            last_output = "\n".join(text_parts)
                            break
                    elif isinstance(content, str) and content.strip():
                        last_output = content
                        break
                if last_output:
                    break
            if last_output:
                root_span.set_output(format_content(last_output))

        debug_log(f"Successfully processed {len(turns)} turn(s) for session {session_id}")

    except Exception as e:
        debug_log(f"An error occurred while sending traces to CozeLoop: {e}")
    finally:
        # Crucial: close the client to ensure all buffered traces are sent.
        client.close()
        debug_log("CozeLoop client closed.")


# --- Hook Input ---

def read_hook_stdin() -> Dict[str, Any]:
    """Read hook input from stdin (non-blocking).

    Claude Code passes a JSON payload via stdin to hooks, containing fields like
    transcript_path, session_id, hook_event_name, etc.
    Returns empty dict if stdin is empty or not valid JSON.
    """
    try:
        if not sys.stdin.isatty():
            data = sys.stdin.read().strip()
            if data:
                result = json.loads(data)
                debug_log(f"Read hook stdin: keys={list(result.keys())}")
                return result
    except Exception as e:
        debug_log(f"Error reading hook stdin: {e}")
    return {}


# --- Main Execution ---

def main():
    """Main entry point for the hook script."""
    debug_log("Hook started.")

    # Check if tracing is enabled
    if os.environ.get("TRACE_TO_COZELOOP", "").lower() == "false":
        debug_log("TRACE_TO_COZELOOP is set to 'false', skipping")
        return

    # Read hook input from stdin (Claude Code provides transcript_path, session_id, etc.)
    hook_input = read_hook_stdin()

    # Determine conversation file: prefer stdin, fallback to file scan
    conversation_file = hook_input.get("transcript_path")
    if conversation_file:
        conversation_file = os.path.expanduser(conversation_file)
        if not os.path.exists(conversation_file):
            debug_log(f"transcript_path from stdin does not exist: {conversation_file}")
            conversation_file = None

    if not conversation_file:
        conversation_file = find_latest_conversation_file()

    if not conversation_file:
        debug_log("Execution skipped: No conversation file found.")
        return

    debug_log(f"Using conversation file: {conversation_file}")

    # Load state to know where to start reading
    state_file = get_state_file_path(conversation_file)
    state = load_state(state_file)
    last_processed_line = state.get("last_processed_line", 0)

    # Read new messages from the file
    new_messages = read_new_messages(conversation_file, last_processed_line)

    # Determine session ID: prefer stdin, then messages, then state, then generate
    session_id = hook_input.get("session_id")
    if not session_id:
        for msg in new_messages:
            if msg.get("sessionId"):
                session_id = msg.get("sessionId")
                break
    if not session_id:
        if state.get("session_id"):
            session_id = state["session_id"]
        else:
            session_id = f"claude-code-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
            debug_log(f"Generated new session ID: {session_id}")

    state["session_id"] = session_id
    debug_log(f"Session ID: {session_id}")

    if not new_messages:
        debug_log("No new messages to process.")
        return

    debug_log(f"Found {len(new_messages)} new messages.")

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
