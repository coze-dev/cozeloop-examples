#!/usr/bin/env python3
"""
CozeLoop Hook for Codex CLI

This hook integrates OpenAI Codex CLI with CozeLoop for tracing and observability.
It captures conversation interactions from the rollout JSONL file and sends them
to the CozeLoop platform for analysis.

Usage:
    1. Copy this script to ~/.codex/hooks/cozeloop_hook.py
    2. Register the hook in ~/.codex/hooks.json
    3. Set environment variables: COZELOOP_WORKSPACE_ID, COZELOOP_API_TOKEN
    4. Run Codex CLI as normal - traces will be sent automatically on each turn end

Hook input (via stdin):
    {
        "hook_event_name": "Stop",
        "session_id": "...",
        "turn_id": "...",
        "transcript_path": "/Users/.../.codex/sessions/YYYY/MM/DD/rollout-xxx.jsonl"
    }

Subagent support:
    When Codex spawns subagents, each subagent gets its own rollout file with:
      session_meta.source = {"subagent": {"thread_spawn": {"parent_thread_id": "..."}}}
    Subagent hooks do NOT report traces directly. Instead they save their
    processed turn data to a per-agent file under ~/.codex/cozeloop_state/.
    When the parent session's hook runs, it reads those saved files and includes
    the subagent spans inside the same trace, producing a single trace per
    conversation that contains both the main agent and all of its subagents.
"""

import json
import os
import sys
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

def get_state_file_path(transcript_path: str) -> str:
    """Get the state file path for tracking processed lines."""
    state_dir = Path.home() / ".codex" / "cozeloop_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    file_hash = hashlib.md5(transcript_path.encode()).hexdigest()[:12]
    return str(state_dir / f"state_{file_hash}.json")


def get_subagent_data_file(agent_session_id: str) -> str:
    """Get the file path for storing subagent turn data."""
    state_dir = Path.home() / ".codex" / "cozeloop_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    return str(state_dir / f"subagent_{agent_session_id}.json")


def save_subagent_data(agent_session_id: str, data: Dict[str, Any]):
    """Save subagent turn data for later inclusion by parent hook."""
    path = get_subagent_data_file(agent_session_id)
    try:
        with open(path, "w") as f:
            json.dump(data, f, ensure_ascii=False)
        debug_log(f"Saved subagent data for {agent_session_id}")
    except Exception as e:
        debug_log(f"Error saving subagent data for {agent_session_id}: {e}")


def load_subagent_data(agent_session_id: str) -> Optional[Dict[str, Any]]:
    """Load previously saved subagent turn data."""
    path = get_subagent_data_file(agent_session_id)
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception as e:
            debug_log(f"Error loading subagent data for {agent_session_id}: {e}")
    return None


def load_state(state_file: str) -> Dict[str, Any]:
    """Load the processing state from file."""
    if os.path.exists(state_file):
        try:
            with open(state_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            debug_log(f"Error loading state: {e}")
    return {"last_processed_line": 0, "session_id": None, "conversation_history": []}


def save_state(state_file: str, state: Dict[str, Any]):
    """Save the processing state to file."""
    try:
        with open(state_file, 'w') as f:
            json.dump(state, f)
    except Exception as e:
        debug_log(f"Error saving state: {e}")


# --- Rollout File Parsing ---

def read_rollout_messages(transcript_path: str, start_line: int = 0) -> List[Dict[str, Any]]:
    """Read raw JSONL entries from the rollout file starting from a given line."""
    entries = []
    try:
        with open(transcript_path, 'r') as f:
            for i, line in enumerate(f):
                if i < start_line:
                    continue
                line = line.strip()
                if line:
                    try:
                        entry = json.loads(line)
                        entry['_line_number'] = i
                        entries.append(entry)
                    except json.JSONDecodeError as e:
                        debug_log(f"Error parsing line {i}: {e}")
    except Exception as e:
        debug_log(f"Error reading rollout file: {e}")
    return entries


def parse_session_meta(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Extract session identity from session_meta entry."""
    result = {
        "session_id": None,
        "parent_session_id": None,
        "agent_nickname": None,
        "agent_role": None,
        "is_subagent": False,
        "subagent_content_start_line": None,
    }
    for entry in entries:
        if entry.get("type") != "session_meta":
            continue
        p = entry.get("payload", {})
        result["session_id"] = p.get("id")
        result["agent_nickname"] = p.get("agent_nickname")
        result["agent_role"] = p.get("agent_role")

        source = p.get("source", "")
        if isinstance(source, dict):
            thread_spawn = source.get("subagent", {}).get("thread_spawn", {})
            parent_id = thread_spawn.get("parent_thread_id")
            if parent_id:
                result["parent_session_id"] = parent_id
                result["is_subagent"] = True
        break

    if result["is_subagent"]:
        meta_count = 0
        for entry in entries:
            if entry.get("type") == "session_meta":
                meta_count += 1
                if meta_count == 2:
                    result["subagent_content_start_line"] = entry.get("_line_number", 0) + 1
                    break

    return result


# --- Message Content Helpers ---

def is_real_user_message(payload: Dict[str, Any]) -> bool:
    """Check whether a response_item/message(user) entry is a real user input."""
    if payload.get("role") != "user":
        return False
    content = payload.get("content", [])
    if not isinstance(content, list):
        return False

    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "input_text":
            continue
        text = item.get("text", "")
        if text.startswith("<environment_context>"):
            continue
        if text.startswith("<permissions instructions>"):
            continue
        if text.startswith("<turn_aborted>"):
            continue
        if text.strip():
            return True

    return False


def extract_user_text(payload: Dict[str, Any]) -> str:
    """Extract the visible text from a user message payload."""
    parts = []
    for item in payload.get("content", []):
        if isinstance(item, dict) and item.get("type") == "input_text":
            text = item.get("text", "")
            if (not text.startswith("<environment_context>") and
                    not text.startswith("<permissions instructions>") and
                    not text.startswith("<turn_aborted>")):
                parts.append(text)
    return "\n".join(parts)


def extract_assistant_text(payload: Dict[str, Any]) -> str:
    """Extract visible text from an assistant message payload."""
    parts = []
    for item in payload.get("content", []):
        if isinstance(item, dict) and item.get("type") in ("output_text", "text"):
            parts.append(item.get("text", ""))
    return "\n".join(parts)


def extract_message_content_text(payload: Dict[str, Any]) -> str:
    """Extract all text content from a message payload regardless of role."""
    parts = []
    for item in payload.get("content", []):
        if not isinstance(item, dict):
            continue
        text = item.get("text", "")
        if text:
            parts.append(text)
    return "\n".join(parts)


def truncate_text(text: str, limit: int = 12000) -> str:
    """Truncate text to a maximum length."""
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


# --- Message Grouping ---

def group_messages_into_turns(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group raw JSONL entries into conversation turns.

    Turn lifecycle:
      - Opened by: event_msg / task_started
      - Closed by: event_msg / task_complete (or next task_started)

    Within a turn we collect:
      - user_message       : first real user input
      - assistant_messages : response_item/message role=assistant items
      - tool_calls         : response_item/function_call items (excl. spawn/wait_agent)
      - tool_results       : response_item/function_call_output items (excl. spawn/wait)
      - input_messages     : messages sent as model input up to the user message
      - subagent_calls     : spawn_agent calls with their agent_id and final result
    """
    turns = []
    current_turn: Optional[Dict[str, Any]] = None
    pending_calls: Dict[str, Dict[str, Any]] = {}

    for entry in entries:
        entry_type = entry.get("type")
        payload = entry.get("payload", {})

        # --- Turn lifecycle events ---
        if entry_type == "event_msg":
            msg_type = payload.get("type")
            if msg_type == "task_started":
                if current_turn is not None:
                    turns.append(current_turn)
                current_turn = {
                    "turn_id": payload.get("turn_id"),
                    "user_message": None,
                    "user_message_text": "",
                    "assistant_messages": [],
                    "tool_calls": [],
                    "tool_results": [],
                    "input_messages": [],
                    "subagent_calls": [],
                    "token_usage": {},
                    "start_line": entry.get("_line_number", 0),
                }
                pending_calls = {}
            elif msg_type == "task_complete":
                if current_turn is not None:
                    turns.append(current_turn)
                    current_turn = None
                pending_calls = {}
            elif msg_type == "token_count":
                if current_turn is not None:
                    info = payload.get("info") or {}
                    current_turn["token_usage"] = info.get("last_token_usage", {})
            continue

        # --- Content items ---
        if entry_type == "response_item":
            item_type = payload.get("type")

            if item_type == "message":
                role = payload.get("role")
                if role == "user" and is_real_user_message(payload):
                    if current_turn is not None and current_turn["user_message"] is None:
                        current_turn["user_message"] = payload
                        current_turn["user_message_text"] = extract_user_text(payload)
                    if current_turn is not None:
                        current_turn["input_messages"].append({
                            "role": "user",
                            "content": extract_user_text(payload),
                        })
                elif role == "assistant":
                    if current_turn is not None:
                        current_turn["assistant_messages"].append(payload)
                elif role in ("developer", "system"):
                    if current_turn is not None:
                        current_turn["input_messages"].append({
                            "role": role,
                            "content": extract_message_content_text(payload),
                        })
                else:
                    if current_turn is not None:
                        text = extract_message_content_text(payload)
                        if text:
                            current_turn["input_messages"].append({
                                "role": role or "user",
                                "content": text,
                            })

            elif item_type == "function_call":
                if current_turn is None:
                    continue
                call_id = payload.get("call_id")
                name = payload.get("name", "")
                args_raw = payload.get("arguments", "{}")
                try:
                    args = json.loads(args_raw)
                except (json.JSONDecodeError, TypeError):
                    args = {"_raw": args_raw}

                if name == "spawn_agent":
                    subagent_call = {
                        "call_id": call_id,
                        "agent_id": None,
                        "nickname": None,
                        "role": args.get("agent_type"),
                        "message": args.get("message", ""),
                        "model": args.get("model"),
                        "result": None,
                    }
                    current_turn["subagent_calls"].append(subagent_call)
                    pending_calls[call_id] = {"kind": "spawn", "subagent_call": subagent_call}
                elif name == "wait_agent":
                    pending_calls[call_id] = {
                        "kind": "wait",
                        "ids": args.get("ids", []),
                    }
                else:
                    current_turn["tool_calls"].append({
                        "call_id": call_id,
                        "name": name,
                        "input": args,
                    })
                    pending_calls[call_id] = {"kind": "tool"}

            elif item_type == "function_call_output":
                if current_turn is None:
                    continue
                call_id = payload.get("call_id")
                raw_output = payload.get("output", "")

                pending = pending_calls.get(call_id, {})
                kind = pending.get("kind", "tool")

                if kind == "spawn":
                    subagent_call = pending.get("subagent_call")
                    if subagent_call is not None:
                        try:
                            out = json.loads(raw_output) if isinstance(raw_output, str) else raw_output
                            subagent_call["agent_id"] = out.get("agent_id")
                            subagent_call["nickname"] = out.get("nickname")
                        except (json.JSONDecodeError, TypeError, AttributeError):
                            pass

                elif kind == "wait":
                    try:
                        out = json.loads(raw_output) if isinstance(raw_output, str) else raw_output
                        status = out.get("status", {}) if isinstance(out, dict) else {}
                        for agent_id, agent_status in status.items():
                            result_text = None
                            if isinstance(agent_status, dict):
                                result_text = agent_status.get("completed")
                            for sc in current_turn["subagent_calls"]:
                                if sc.get("agent_id") == agent_id and sc.get("result") is None:
                                    sc["result"] = result_text
                                    break
                    except (json.JSONDecodeError, TypeError, AttributeError):
                        pass

                else:
                    current_turn["tool_results"].append({
                        "call_id": call_id,
                        "output": raw_output,
                    })

    if current_turn is not None:
        turns.append(current_turn)

    # Drop turns with no user input and no assistant response
    turns = [
        t for t in turns
        if t["user_message"] is not None or t["assistant_messages"]
    ]

    return turns


# --- CozeLoop Trace Reporting ---

def _make_model_message(role: str, content: str = "", tool_calls: list = None,
                        tool_call_id: str = "") -> ModelMessage:
    """Helper to create a CozeLoop ModelMessage."""
    return ModelMessage(
        role=role,
        content=content,
        reasoning_content="",
        parts=[],
        name="",
        tool_calls=tool_calls or [],
        tool_call_id=tool_call_id or "",
        metadata={}
    )


def send_turns_to_cozeloop(turns: List[Dict[str, Any]], session_id: str, model_name: str = "codex",
                           history_context: Optional[List[Dict[str, Any]]] = None) -> Optional[List[Dict[str, Any]]]:
    """Send conversation turns to CozeLoop for tracing.

    Span hierarchy:
      root_span (codex_request) [input=user_input, output=final_response]
        +-- turn_span (turn_0, turn_1, ...)
              |-- model_span (assistant_response)
              |-- tool_span (tool calls)
              |-- subagent_span (subagent calls with nested turns)

    Returns the updated history_context on success, or None on failure.
    """
    if not turns:
        return history_context

    debug_log(f"Initializing CozeLoop client for session: {session_id}")
    client = cozeloop.new_client()
    ctx: List[Dict[str, Any]] = list(history_context) if history_context else []

    try:
        with client.start_span(name="codex_request", span_type="main") as root_span:
            root_span.set_runtime(Runtime(library="codex-cli"))
            root_span.set_tags({
                "thread_id": session_id,
                "total_turns": len(turns),
                "source": "codex_cli",
            })
            root_span.set_baggage({
                "thread_id": session_id,
            })

            # Set root span input: all user messages
            root_input_parts = []
            for turn in turns:
                text = turn.get("user_message_text", "")
                if text:
                    root_input_parts.append(text)
            if root_input_parts:
                root_span.set_input(truncate_text("\n\n".join(root_input_parts)))

            # Set root span output: all assistant messages
            root_output_parts = []
            for turn in turns:
                for assistant_payload in turn.get("assistant_messages", []):
                    assistant_text = extract_assistant_text(assistant_payload)
                    if assistant_text:
                        root_output_parts.append(assistant_text)
            if root_output_parts:
                root_span.set_output(truncate_text("\n\n".join(root_output_parts)))

            # Process each turn
            for i, turn in enumerate(turns):
                try:
                    with client.start_span(name=f"turn_{i}", span_type="main") as turn_span:
                        turn_span.set_runtime(Runtime(library="codex-cli"))
                        turn_span.set_tags({
                            "thread_id": session_id,
                            "turn_index": i,
                            "turn_id": turn.get("turn_id", ""),
                            "source": "codex_cli",
                        })

                        # --- Model span for assistant response ---
                        if turn.get("assistant_messages"):
                            with client.start_span(name="assistant_response", span_type="model") as model_span:
                                model_span.set_runtime(Runtime(library="codex-cli"))
                                model_span.set_model_name(model_name)

                                # Build input messages: history + current turn input
                                turn_input = turn.get("input_messages", [])
                                if not turn_input:
                                    turn_input = [{"role": "user", "content": turn.get("user_message_text", "")}]
                                input_messages = ctx + turn_input

                                model_messages = []
                                for msg in input_messages:
                                    model_messages.append(_make_model_message(
                                        role=msg.get("role", "user"),
                                        content=msg.get("content", "")
                                    ))

                                model_span.set_input(ModelInput(
                                    messages=model_messages,
                                    tools=[],
                                    tool_choice=ModelToolChoice(type="", function=None)
                                ))

                                # Build output choices
                                choices = []
                                for assistant_payload in turn["assistant_messages"]:
                                    assistant_text = extract_assistant_text(assistant_payload)
                                    # Extract tool calls from assistant content
                                    tc_list = []
                                    for item in assistant_payload.get("content", []):
                                        if isinstance(item, dict) and item.get("type") == "function_call":
                                            tc_list.append(ModelToolCall(
                                                id=item.get("call_id", ""),
                                                type="function",
                                                function=ModelToolCallFunction(
                                                    name=item.get("name", ""),
                                                    arguments=item.get("arguments", "")
                                                )
                                            ))

                                    finish_reason = "tool_calls" if tc_list else "stop"
                                    choices.append(ModelChoice(
                                        finish_reason=finish_reason,
                                        index=len(choices),
                                        message=ModelMessage(
                                            role="assistant",
                                            content=assistant_text,
                                            reasoning_content="",
                                            parts=[],
                                            name="",
                                            tool_calls=tc_list,
                                            tool_call_id="",
                                            metadata={}
                                        )
                                    ))

                                model_span.set_output(ModelOutput(choices=choices))

                                # Set token usage
                                token_usage = turn.get("token_usage", {})
                                input_tokens = token_usage.get("input_tokens", 0)
                                output_tokens = token_usage.get("output_tokens", 0)
                                if input_tokens > 0:
                                    model_span.set_input_tokens(input_tokens)
                                if output_tokens > 0:
                                    model_span.set_output_tokens(output_tokens)

                        # --- Tool call spans ---
                        for tool_call in turn.get("tool_calls", []):
                            tool_name = tool_call.get("name", "unknown")
                            with client.start_span(name=f"tool_{tool_name}", span_type="tool") as tool_span:
                                tool_span.set_runtime(Runtime(library="codex-cli"))
                                tool_span.set_tags({
                                    "tool_name": tool_name,
                                    "call_id": tool_call.get("call_id"),
                                })
                                tool_span.set_input(
                                    json.dumps(tool_call.get("input", {}), ensure_ascii=False)[:2000]
                                )
                                # Find matching tool result
                                call_id = tool_call.get("call_id")
                                for result in turn.get("tool_results", []):
                                    if result.get("call_id") == call_id:
                                        output = result.get("output", "")
                                        if isinstance(output, str) and len(output) > 2000:
                                            output = output[:2000] + "..."
                                        tool_span.set_output(str(output))
                                        break

                        # --- Subagent spans ---
                        for sc in turn.get("subagent_calls", []):
                            agent_id = sc.get("agent_id") or "unknown"
                            nickname = sc.get("nickname") or agent_id

                            with client.start_span(name=f"subagent_{nickname}", span_type="agent") as subagent_span:
                                subagent_span.set_runtime(Runtime(library="codex-cli"))
                                subagent_span.set_tags({
                                    "agent_id": agent_id,
                                    "agent_nickname": nickname,
                                    "agent_role": sc.get("role") or "",
                                    "agent_model": sc.get("model") or "",
                                })
                                subagent_span.set_input(sc.get("message", "")[:2000])

                                # Load and include saved subagent turn data
                                sa_data = load_subagent_data(agent_id)
                                if sa_data and sa_data.get("turns"):
                                    sa_turns = sa_data["turns"]
                                    sa_model = sa_data.get("model_name", "codex")

                                    for si, sa_turn in enumerate(sa_turns):
                                        with client.start_span(name=f"turn_{si}", span_type="main") as sa_turn_span:
                                            sa_turn_span.set_runtime(Runtime(library="codex-cli"))
                                            sa_turn_span.set_tags({
                                                "turn_index": si,
                                                "turn_id": sa_turn.get("turn_id", ""),
                                                "agent_name": nickname,
                                            })

                                            # Subagent model span
                                            if sa_turn.get("assistant_messages"):
                                                with client.start_span(name="assistant_response", span_type="model") as sa_model_span:
                                                    sa_model_span.set_runtime(Runtime(library="codex-cli"))
                                                    sa_model_span.set_model_name(sa_model)
                                                    sa_model_span.set_tags({"agent_name": nickname})

                                                    sa_input = sa_turn.get("input_messages", [])
                                                    if not sa_input:
                                                        sa_input = [{"role": "user", "content": sa_turn.get("user_message_text", "")}]
                                                    sa_model_messages = []
                                                    for msg in sa_input:
                                                        sa_model_messages.append(_make_model_message(
                                                            role=msg.get("role", "user"),
                                                            content=msg.get("content", "")
                                                        ))
                                                    sa_model_span.set_input(ModelInput(
                                                        messages=sa_model_messages,
                                                        tools=[],
                                                        tool_choice=ModelToolChoice(type="", function=None)
                                                    ))

                                                    sa_choices = []
                                                    for ap in sa_turn["assistant_messages"]:
                                                        sa_choices.append(ModelChoice(
                                                            finish_reason="stop",
                                                            index=len(sa_choices),
                                                            message=ModelMessage(
                                                                role="assistant",
                                                                content=extract_assistant_text(ap),
                                                                reasoning_content="",
                                                                parts=[],
                                                                name="",
                                                                tool_calls=[],
                                                                tool_call_id="",
                                                                metadata={}
                                                            )
                                                        ))
                                                    sa_model_span.set_output(ModelOutput(choices=sa_choices))

                                                    sa_token = sa_turn.get("token_usage", {})
                                                    if sa_token.get("input_tokens", 0) > 0:
                                                        sa_model_span.set_input_tokens(sa_token["input_tokens"])
                                                    if sa_token.get("output_tokens", 0) > 0:
                                                        sa_model_span.set_output_tokens(sa_token["output_tokens"])

                                            # Subagent tool spans
                                            for sa_tc in sa_turn.get("tool_calls", []):
                                                sa_tool_name = sa_tc.get("name", "unknown")
                                                with client.start_span(name=f"tool_{sa_tool_name}", span_type="tool") as sa_tool_span:
                                                    sa_tool_span.set_runtime(Runtime(library="codex-cli"))
                                                    sa_tool_span.set_tags({
                                                        "tool_name": sa_tool_name,
                                                        "call_id": sa_tc.get("call_id"),
                                                        "agent_name": nickname,
                                                    })
                                                    sa_tool_span.set_input(
                                                        json.dumps(sa_tc.get("input", {}), ensure_ascii=False)[:2000]
                                                    )
                                                    sa_cid = sa_tc.get("call_id")
                                                    for sa_r in sa_turn.get("tool_results", []):
                                                        if sa_r.get("call_id") == sa_cid:
                                                            sa_out = sa_r.get("output", "")
                                                            if isinstance(sa_out, str) and len(sa_out) > 2000:
                                                                sa_out = sa_out[:2000] + "..."
                                                            sa_tool_span.set_output(str(sa_out))
                                                            break

                                    debug_log(f"Included {len(sa_turns)} subagent turns for {nickname} ({agent_id})")
                                else:
                                    debug_log(f"No saved data found for subagent {nickname} ({agent_id})")

                                result_text = sc.get("result") or ""
                                if len(result_text) > 2000:
                                    result_text = result_text[:2000] + "..."
                                subagent_span.set_output(result_text)

                        # Update conversation context for subsequent turns
                        if turn.get("user_message_text"):
                            ctx.append({"role": "user", "content": turn["user_message_text"]})
                        for assistant_payload in turn.get("assistant_messages", []):
                            assistant_text = extract_assistant_text(assistant_payload)
                            if assistant_text:
                                ctx.append({"role": "assistant", "content": assistant_text})

                except Exception as e:
                    debug_log(f"Error processing turn {i}: {e}")
                    continue

        debug_log(f"Successfully processed {len(turns)} turn(s) for session {session_id}")

    except Exception as e:
        debug_log(f"An error occurred while sending traces to CozeLoop: {e}")
        return None
    finally:
        client.close()
        debug_log("CozeLoop client closed.")

    return ctx


# --- Main Execution ---

def main():
    """Main entry point for the Codex CozeLoop hook."""
    debug_log("Codex CozeLoop hook started.")

    # Check if tracing is enabled
    if os.environ.get("TRACE_TO_COZELOOP", "").lower() == "false":
        debug_log("TRACE_TO_COZELOOP is set to 'false', skipping")
        return

    # Read hook input from stdin
    try:
        raw_input = sys.stdin.read().strip()
        if not raw_input:
            debug_log("No input received from stdin")
            return
        hook_input = json.loads(raw_input)
    except Exception as e:
        debug_log(f"Error reading hook input from stdin: {e}")
        return

    debug_log(f"Hook input: {json.dumps(hook_input, ensure_ascii=False)}")

    # Get transcript path
    transcript_path = hook_input.get("transcript_path")
    if not transcript_path:
        debug_log("No transcript_path in hook input")
        return

    if not os.path.exists(transcript_path):
        debug_log(f"Transcript file not found: {transcript_path}")
        return

    # Load state
    state_file = get_state_file_path(transcript_path)
    state = load_state(state_file)

    # Read new entries
    entries = read_rollout_messages(transcript_path, state["last_processed_line"])

    if not entries:
        debug_log("No new entries to process")
        return

    debug_log(f"Read {len(entries)} new entries from line {state['last_processed_line']}")

    # Parse session identity
    all_entries_for_meta = read_rollout_messages(transcript_path, 0)
    session_info = parse_session_meta(all_entries_for_meta)

    session_id = session_info["session_id"] or hook_input.get("session_id", "")
    parent_session_id = session_info["parent_session_id"]
    agent_nickname = session_info["agent_nickname"]
    agent_role = session_info["agent_role"]
    is_subagent = session_info["is_subagent"]
    subagent_content_start = session_info.get("subagent_content_start_line")

    # Filter subagent entries to only include their own content
    if is_subagent and subagent_content_start is not None:
        entries = [e for e in entries if e.get("_line_number", 0) >= subagent_content_start]
        debug_log(f"Filtered subagent entries from line {subagent_content_start}, {len(entries)} remaining")

    # Determine model name
    model_name = "codex"
    for entry in entries:
        if entry.get("type") == "turn_context":
            model_name = entry.get("payload", {}).get("model", model_name)
            break

    if not session_id:
        session_id = f"codex_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{os.getpid()}"

    state["session_id"] = session_id
    debug_log(f"Session ID: {session_id}, parent: {parent_session_id}, "
              f"is_subagent: {is_subagent}, nickname: {agent_nickname}, model: {model_name}")

    # Group entries into turns
    turns = group_messages_into_turns(entries)
    debug_log(f"Grouped into {len(turns)} turns")

    # If this is a subagent, save data for parent to include later
    if is_subagent:
        save_subagent_data(session_id, {
            "session_id": session_id,
            "parent_session_id": parent_session_id,
            "agent_nickname": agent_nickname,
            "agent_role": agent_role,
            "model_name": model_name,
            "turns": turns[-1:],
        })
        last_line = max(e.get("_line_number", 0) for e in entries) + 1
        state["last_processed_line"] = last_line
        save_state(state_file, state)
        debug_log("Subagent data saved, hook completed")
        return

    # Send turns to CozeLoop
    if turns:
        history_context = state.get("conversation_history", [])
        updated_history = send_turns_to_cozeloop(
            turns, session_id, model_name,
            history_context=history_context,
        )
        if updated_history is not None:
            last_line = max(e.get("_line_number", 0) for e in entries) + 1
            state["last_processed_line"] = last_line
            state["conversation_history"] = updated_history
            save_state(state_file, state)
            debug_log(f"State updated, last processed line: {last_line}")
        else:
            debug_log("Send failed, state not advanced")
    else:
        debug_log("No turns to send")

    debug_log("Codex CozeLoop hook completed.")


if __name__ == "__main__":
    main()
