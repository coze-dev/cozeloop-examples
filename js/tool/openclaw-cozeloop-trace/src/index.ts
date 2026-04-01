import type {
  OpenClawPlugin,
  OpenClawPluginApi,
  PluginHookContext,
  CozeloopTraceConfig,
  LlmInputEvent,
  LlmOutputEvent,
  BeforeToolCallEvent,
  AfterToolCallEvent,
  BeforeAgentStartEvent,
  AgentEndEvent,
  SessionStartEvent,
  SessionEndEvent,
  GatewayStartEvent,
  GatewayStopEvent,
  MessageReceivedEvent,
  MessageSendingEvent,
  MessageSentEvent,
  SpanData,
} from "./types.js";
import { CozeloopExporter } from "./cozeloop-exporter.js";
import { readFileSync, readdirSync, existsSync } from "node:fs";
import { join, resolve } from "node:path";
import { homedir } from "node:os";

function generateId(length = 16): string {
  const chars = "0123456789abcdef";
  let result = "";
  for (let i = 0; i < length; i++) {
    result += chars[Math.floor(Math.random() * chars.length)];
  }
  return result;
}

function safeClone<T>(value: T): T {
  if (typeof (globalThis as unknown as { structuredClone?: unknown }).structuredClone === "function") {
    return (globalThis as unknown as { structuredClone: (input: T) => T }).structuredClone(value);
  }
  return JSON.parse(JSON.stringify(value)) as T;
}

function resolveOpenclawStateDir(): string {
  const override = process.env.OPENCLAW_STATE_DIR?.trim() || process.env.CLAWDBOT_STATE_DIR?.trim();
  if (override) return resolve(override.startsWith("~") ? override.replace(/^~(?=$|[\\/])/, homedir()) : override);

  const home = homedir();
  const newDir = join(home, ".openclaw");
  try { if (existsSync(newDir)) return newDir; } catch { /* ignore */ }

  for (const legacy of [".clawdbot", ".moldbot", ".moltbot"]) {
    const legacyDir = join(home, legacy);
    try { if (existsSync(legacyDir)) return legacyDir; } catch { /* ignore */ }
  }

  return newDir;
}

function resolveAgentIdFromHookCtx(hookCtx: PluginHookContext): string {
  const explicit = (hookCtx.agentId as string)?.trim()?.toLowerCase();
  if (explicit) return explicit;

  const sessionKey = (hookCtx.sessionKey as string)?.trim()?.toLowerCase();
  if (sessionKey) {
    const match = sessionKey.match(/^agent:([^:]+):/);
    if (match?.[1]) return match[1];
  }

  return "main";
}

function resolveSessionFile(hookCtx: PluginHookContext): string | undefined {
  try {
    const stateDir = resolveOpenclawStateDir();
    const agentId = resolveAgentIdFromHookCtx(hookCtx);
    const sessionsDir = join(stateDir, "agents", agentId, "sessions");
    const sessionId = (hookCtx.sessionId || "") as string;
    let targetFile: string | undefined;

    const files = readdirSync(sessionsDir);
    if (sessionId) {
      for (const f of files) {
        if (!f.endsWith(".jsonl")) continue;
        if (f.includes(".deleted.") || f.includes(".reset.")) continue;
        if (f.startsWith(sessionId)) {
          targetFile = join(sessionsDir, f);
          break;
        }
      }
    }

    if (!targetFile) {
      const jsonlFiles = files.filter(
        (f) => f.endsWith(".jsonl") && !f.includes(".deleted.") && !f.includes(".reset.")
      );
      if (jsonlFiles.length > 0) {
        targetFile = join(sessionsDir, jsonlFiles[jsonlFiles.length - 1]);
      }
    }

    return targetFile;
  } catch {
    return undefined;
  }
}

function formatAssistantOutput(content: unknown, stopReason?: string): Record<string, unknown> {
  const contentItems = Array.isArray(content) ? content as Array<Record<string, unknown>> : [];

  const toolCalls: Array<Record<string, unknown>> = [];
  const messageContent: unknown[] = [];

  for (const item of contentItems) {
    if (!item || typeof item !== "object") {
      messageContent.push(item);
      continue;
    }

    const itemType = (item as Record<string, unknown>).type;

    if (itemType === "toolCall") {
      toolCalls.push({
        function: {
          arguments: typeof item.arguments === "string" ? item.arguments : JSON.stringify(item.arguments ?? item.input ?? {}),
          name: item.name ?? "",
        },
        id: item.id ?? "",
        type: "function",
      });
    } else if (itemType === "text") {
      messageContent.push({ type: "text", text: item.text ?? "" });
    } else if (itemType === "thinking") {
      messageContent.push({
        type: "thinking",
        thinking: item.thinking ?? "",
        signature: item.signature,
      });
    } else {
      messageContent.push(item);
    }
  }

  const message: Record<string, unknown> = {
    content: messageContent.length === 1 && (messageContent[0] as Record<string, unknown>)?.type === "text"
      ? ((messageContent[0] as Record<string, unknown>).text ?? "")
      : messageContent,
    role: "assistant",
    tool_calls: toolCalls.length > 0 ? toolCalls : undefined,
    function_call: null,
    provider_specific_fields: null,
  };

  return {
    choices: [
      {
        finish_reason: stopReason === "toolUse" ? "tool_calls" : "stop",
        message,
      },
    ],
  };
}

function convertAssistantContentForMessages(content: unknown): unknown[] {
  if (!Array.isArray(content)) return [{ type: "text", text: String(content ?? "") }];

  const result: unknown[] = [];
  for (const item of content as Array<Record<string, unknown>>) {
    if (!item || typeof item !== "object") {
      result.push(item);
      continue;
    }
    if (item.type === "toolCall") {
      result.push({
        type: "tool_use",
        id: item.id ?? "",
        name: item.name ?? "",
        input: item.arguments ?? item.input ?? {},
      });
    } else if (item.type === "thinking") {
      result.push({
        type: "thinking",
        thinking: item.thinking ?? "",
        signature: item.signature,
      });
    } else {
      result.push(item);
    }
  }
  return result;
}

function convertToolResultsForMessages(
  toolResultEntries: ReactEntry[]
): Array<{ role: string; content: string; tool_call_id: string }> {
  const messages: Array<{ role: string; content: string; tool_call_id: string }> = [];
  for (const tr of toolResultEntries) {
    let textContent = "";
    if (Array.isArray(tr.content)) {
      const parts = tr.content as Array<Record<string, unknown>>;
      textContent = parts
        .filter((p) => p?.type === "text")
        .map((p) => String(p.text ?? ""))
        .join("\n");
    } else if (typeof tr.content === "string") {
      textContent = tr.content;
    } else {
      textContent = JSON.stringify(tr.content);
    }

    messages.push({
      role: "tool",
      content: textContent,
      tool_call_id: tr.toolCallId ?? "",
    });
  }
  return messages;
}

interface ReactEntry {
  type: "assistant" | "toolResult" | "tool";
  content: unknown;
  provider?: string;
  model?: string;
  usage?: { input?: number; output?: number };
  stopReason?: string;
  timestamp?: number;
  writtenAt?: number;
  toolCallId?: string;
  toolName?: string;
  isError?: boolean;
}

function parseEntryWrittenAt(entry: Record<string, unknown>): number | undefined {
  const ts = entry.timestamp;
  if (typeof ts === "string") {
    const ms = new Date(ts).getTime();
    if (!Number.isNaN(ms)) return ms;
  }
  if (typeof ts === "number") return ts;
  return undefined;
}

function readCurrentTurnReactSequence(hookCtx: PluginHookContext): { entries: ReactEntry[]; userWrittenAt?: number } {
  try {
    const targetFile = resolveSessionFile(hookCtx);
    if (!targetFile) return { entries: [] };

    const raw = readFileSync(targetFile, "utf-8");
    const lines = raw.trim().split("\n");

    let lastUserIdx = -1;
    let userWrittenAt: number | undefined;
    for (let i = lines.length - 1; i >= 0; i--) {
      const line = lines[i].trim();
      if (!line) continue;
      try {
        const entry = JSON.parse(line) as Record<string, unknown>;
        if (entry.type !== "message") continue;
        const msg = entry.message as Record<string, unknown> | undefined;
        if (msg?.role === "user") {
          lastUserIdx = i;
          userWrittenAt = parseEntryWrittenAt(entry);
          break;
        }
      } catch {
        continue;
      }
    }

    if (lastUserIdx < 0) return { entries: [] };

    const entries: ReactEntry[] = [];
    for (let i = lastUserIdx + 1; i < lines.length; i++) {
      const line = lines[i].trim();
      if (!line) continue;
      try {
        const entry = JSON.parse(line) as Record<string, unknown>;
        if (entry.type !== "message") continue;
        const msg = entry.message as Record<string, unknown> | undefined;
        if (!msg) continue;

        const writtenAt = parseEntryWrittenAt(entry);

        if (msg.role === "assistant") {
          entries.push({
            type: "assistant",
            content: msg.content,
            provider: msg.provider as string | undefined,
            model: msg.model as string | undefined,
            usage: msg.usage as { input?: number; output?: number } | undefined,
            stopReason: msg.stopReason as string | undefined,
            timestamp: msg.timestamp as number | undefined,
            writtenAt,
          });
        } else if (msg.role === "toolResult") {
          entries.push({
            type: "toolResult",
            content: msg.content,
            toolCallId: msg.toolCallId as string | undefined,
            toolName: msg.toolName as string | undefined,
            isError: msg.isError as boolean | undefined,
            timestamp: msg.timestamp as number | undefined,
            writtenAt,
          });
        }
      } catch {
        continue;
      }
    }

    return { entries, userWrittenAt };
  } catch {
    return { entries: [] };
  }
}

function normalizeChannelId(input: string, defaultPlatform = "system"): string {
  if (!input || input === "unknown") {
    return `${defaultPlatform}/unknown`;
  }
  if (input.includes("/")) {
    return input;
  }
  const prefix = input.split(/[_:]/)[0];
  switch (prefix) {
    case "ou":
    case "oc":
    case "og":
      return `feishu/${input}`;
    case "user":
    case "chat":
      return `feishu/${input.slice(prefix.length + 1)}`;
    case "agent":
      return `agent/${input.slice(6)}`;
    default:
      return `${defaultPlatform}/${input}`;
  }
}

function resolveChannelId(
  ctx: PluginHookContext,
  eventFrom?: string,
  defaultValue = "system/unknown"
): string {
  if (ctx.conversationId && /^(user|chat):/.test(ctx.conversationId)) {
    return normalizeChannelId(ctx.conversationId);
  }
  if (eventFrom && /^feishu:/.test(eventFrom)) {
    const platformId = eventFrom.slice(7);
    return `feishu/${platformId}`;
  }
  if (ctx.channelId && /^feishu\/(ou|oc|og)_/.test(ctx.channelId)) {
    return ctx.channelId;
  }
  const raw = ctx.sessionKey || ctx.channelId || eventFrom || defaultValue;
  return normalizeChannelId(raw);
}

interface TraceContext {
  traceId: string;
  rootSpanId: string;
  runId: string;
  turnId: string;
  channelId: string;
  originalChannelId?: string;
  llmStartTime?: number;
  llmSpanId?: string;
  llmInput?: unknown;
  toolStartTime?: number;
  toolSpanId?: string;
  toolName?: string;
  toolInput?: unknown;
  reportedAgentStartIds?: Set<string>;
  agentSpanId?: string;
  agentStartTime?: number;
  userInput?: unknown;
  rootSpanStartTime?: number;
  lastOutput?: unknown;
  reactCount?: number;
  lastModelProvider?: string;
  lastModelId?: string;
  pendingToolSpans?: Array<{
    toolName: string;
    toolSpanId: string;
    toolStartTime: number;
    toolEndTime: number;
    toolInput: unknown;
    toolOutput: unknown;
    toolError?: string;
  }>;
  sessionBasedSpansCreated?: boolean;
  pendingCleanup?: {
    savedLastUserTraceContext: TraceContext | undefined;
    savedLastUserChannelId: string | undefined;
    originalChannelId: string;
    agentChannelId: string;
  };
}

let lastUserChannelId: string | undefined;
let lastUserTraceContext: TraceContext | undefined;

interface PendingToolCall {
  toolName: string;
  toolSpanId: string;
  toolStartTime: number;
  toolInput: unknown;
  traceContext: TraceContext;
  channelId: string;
}
let pendingToolCall: PendingToolCall | undefined;

const cozeloopTracePlugin: OpenClawPlugin = {
  id: "openclaw-cozeloop-trace",
  name: "OpenClaw CozeLoop Trace",
  version: "0.1.0",
  description: "Report OpenClaw execution traces to CozeLoop via OpenTelemetry",

  activate(api: OpenClawPluginApi) {
    const pluginConfig = api.pluginConfig || {};

    const authorization = pluginConfig.authorization as string | undefined;
    const workspaceId = pluginConfig.workspaceId as string | undefined;

    if (!authorization || !workspaceId) {
      api.logger.error(
        "[CozeloopTrace] Missing required configuration: 'authorization' and 'workspaceId' must be provided"
      );
      return;
    }

    const config: CozeloopTraceConfig = {
      endpoint: (pluginConfig.endpoint as string) || "https://api.coze.cn/v1/loop/opentelemetry",
      authorization,
      workspaceId,
      serviceName: (pluginConfig.serviceName as string) || "openclaw-agent",
      debug: (pluginConfig.debug as boolean) || false,
      batchSize: (pluginConfig.batchSize as number) || 10,
      batchInterval: (pluginConfig.batchInterval as number) || 5000,
      enabledHooks: pluginConfig.enabledHooks as string[] | undefined,
    };

    const exporter = new CozeloopExporter(api, config);
    const contextByChannelId = new Map<string, TraceContext>();
    const contextByRunId = new Map<string, TraceContext>();

    const shouldHookEnabled = (hookName: string): boolean => {
      if (!config.enabledHooks) return true;
      return config.enabledHooks.includes(hookName);
    };

    const getContextByChannel = (channelId: string): TraceContext | undefined => {
      return contextByChannelId.get(channelId);
    };

    const getContextByRun = (runId: string): TraceContext | undefined => {
      return contextByRunId.get(runId);
    };

    const getOriginalChannelId = (runId: string): string | undefined => {
      const ctx = contextByRunId.get(runId);
      return ctx?.originalChannelId || ctx?.channelId;
    };

    const startTurn = (runId: string, channelId: string, originalChannelId?: string): TraceContext => {
      const traceId = generateId(32);
      const ctx: TraceContext = {
        traceId,
        rootSpanId: generateId(16),
        runId,
        turnId: runId,
        channelId,
        originalChannelId: originalChannelId || channelId,
      };
      contextByChannelId.set(channelId, ctx);
      contextByRunId.set(runId, ctx);
      return ctx;
    };

    const endTurn = (channelId: string): void => {
      const ctx = contextByChannelId.get(channelId);
      if (ctx) {
        contextByChannelId.delete(channelId);
        contextByRunId.delete(ctx.runId);
      }
    };

    const getOrCreateContext = (rawChannelId: string, runId?: string, hookName?: string): { ctx: TraceContext; channelId: string; isNew: boolean } => {
      let channelId = rawChannelId;
      let activeCtx = getContextByChannel(rawChannelId);
      const effectiveRunId = runId || activeCtx?.runId || `run-${Date.now()}`;

      if (rawChannelId.startsWith("agent/") && effectiveRunId) {
        const originalChannelId = getOriginalChannelId(effectiveRunId);
        if (originalChannelId) {
          channelId = originalChannelId;
          activeCtx = getContextByChannel(originalChannelId) || activeCtx;
        }
      }

      if (!activeCtx) {
        activeCtx = getContextByRun(effectiveRunId);
      }

      if (!activeCtx && rawChannelId.startsWith("agent/") && lastUserTraceContext) {
        activeCtx = lastUserTraceContext;
        channelId = lastUserChannelId || channelId;
        contextByChannelId.set(rawChannelId, activeCtx);
        contextByRunId.set(effectiveRunId, activeCtx);
        if (config.debug) {
          api.logger.info(`[CozeloopTrace] LINKING agent to user context: hook=${hookName}, agentChannel=${rawChannelId}, userChannel=${channelId}, traceId=${activeCtx.traceId}`);
        }
      }

      let isNew = false;
      if (!activeCtx) {
        activeCtx = startTurn(effectiveRunId, channelId, rawChannelId !== channelId ? rawChannelId : undefined);
        isNew = true;
        if (config.debug) {
          api.logger.info(`[CozeloopTrace] NEW TraceContext created: hook=${hookName}, channelId=${channelId}, runId=${effectiveRunId}, traceId=${activeCtx.traceId}`);
        }
      } else if (config.debug) {
        api.logger.info(`[CozeloopTrace] REUSING TraceContext: hook=${hookName}, channelId=${channelId}, runId=${effectiveRunId}, traceId=${activeCtx.traceId}`);
      }

      return { ctx: activeCtx, channelId, isNew };
    };

    const createSpan = (
      ctx: TraceContext,
      channelId: string,
      name: string,
      type: string,
      startTime: number,
      endTime: number,
      attributes: Record<string, string | number | boolean> = {},
      input?: unknown,
      output?: unknown,
      parentSpanId?: string
    ): SpanData => {
      return {
        name,
        type: type as SpanData["type"],
        startTime,
        endTime,
        attributes: {
          ...attributes,
          "session.id": channelId,
          "run.id": ctx.runId,
          "turn.id": ctx.turnId,
        },
        input,
        output,
        traceId: ctx.traceId,
        spanId: generateId(16),
        parentSpanId: parentSpanId || ctx.rootSpanId,
      };
    };

    const buildReactSpans = async (
      ctx: TraceContext,
      channelId: string,
      entries: ReactEntry[],
      initialInput: unknown,
      agentStartTime: number,
      userWrittenAt?: number
    ): Promise<number> => {
      const reactMessages: Array<{ role: string; content: unknown }> = [];
      if (initialInput && typeof initialInput === "object") {
        const inputObj = initialInput as Record<string, unknown>;
        if ("messages" in inputObj && Array.isArray(inputObj.messages)) {
          for (const msg of inputObj.messages as Array<Record<string, unknown>>) {
            const m: { role: string; content: unknown; tool_call_id?: string } = { role: String(msg.role || ""), content: safeClone(msg.content) };
            if (msg.tool_call_id) {
              m.tool_call_id = String(msg.tool_call_id);
            }
            reactMessages.push(m);
          }
        }
      }

      let reactRound = 0;
      let modelSpanCount = 0;
      let prevWrittenAt = userWrittenAt || agentStartTime;

      for (let i = 0; i < entries.length; i++) {
        const entry = entries[i];
        const entryWrittenAt = entry.writtenAt || prevWrittenAt;

        if (entry.type === "assistant") {
          reactRound++;
          modelSpanCount++;

          const provider = entry.provider || ctx.lastModelProvider || "unknown";
          const model = entry.model || ctx.lastModelId || "unknown";
          const spanStartTime = prevWrittenAt;
          const spanEndTime = entryWrittenAt;

          const modelSpan = createSpan(
            ctx,
            channelId,
            `${provider}/${model}`,
            "model",
            spanStartTime,
            spanEndTime,
            {
              "gen_ai.provider.name": provider,
              "gen_ai.request.model": model,
              "gen_ai.usage.input_tokens": entry.usage?.input ?? 0,
              "gen_ai.usage.output_tokens": entry.usage?.output ?? 0,
              "react_round": reactRound,
            },
            { messages: reactMessages.map((msg) => safeClone(msg)) },
            formatAssistantOutput(entry.content, entry.stopReason)
          );

          await exporter.export(modelSpan);

          reactMessages.push({
            role: "assistant",
            content: convertAssistantContentForMessages(entry.content),
          });
          prevWrittenAt = entryWrittenAt;
        } else if (entry.type === "toolResult") {
          const toolSpanStartTime = prevWrittenAt;
          const toolSpanEndTime = entryWrittenAt;

          let toolInput: unknown = undefined;
          for (let j = i - 1; j >= 0; j--) {
            if (entries[j].type === "assistant") {
              const assistantContent = entries[j].content;
              if (Array.isArray(assistantContent)) {
                for (const item of assistantContent as Array<Record<string, unknown>>) {
                  if (item?.type === "toolCall" && item.id === entry.toolCallId) {
                    toolInput = { name: item.name, arguments: item.arguments ?? item.input };
                    break;
                  }
                }
              }
              break;
            }
          }

          const toolAttrs: Record<string, string | number | boolean> = {};
          if (entry.isError) {
            toolAttrs["error.msg"] = "tool returned error";
          }

          const toolSpan = createSpan(
            ctx,
            channelId,
            entry.toolName || "unknown_tool",
            "tool",
            toolSpanStartTime,
            toolSpanEndTime,
            toolAttrs,
            toolInput,
            entry.content
          );

          await exporter.export(toolSpan);

          const consecutiveToolResults: ReactEntry[] = [entry];
          while (i + 1 < entries.length && entries[i + 1].type === "toolResult") {
            i++;
            const nextTr = entries[i];
            consecutiveToolResults.push(nextTr);

            const nextWrittenAt = nextTr.writtenAt || prevWrittenAt;
            let nextToolInput: unknown = undefined;
            for (let j = i - 1; j >= 0; j--) {
              if (entries[j].type === "assistant") {
                const ac = entries[j].content;
                if (Array.isArray(ac)) {
                  for (const item of ac as Array<Record<string, unknown>>) {
                    if (item?.type === "toolCall" && item.id === nextTr.toolCallId) {
                      nextToolInput = { name: item.name, arguments: item.arguments ?? item.input };
                      break;
                    }
                  }
                }
                break;
              }
            }

            const nextToolAttrs: Record<string, string | number | boolean> = {};
            if (nextTr.isError) {
              nextToolAttrs["error.msg"] = "tool returned error";
            }

            const nextToolSpan = createSpan(
              ctx,
              channelId,
              nextTr.toolName || "unknown_tool",
              "tool",
              prevWrittenAt,
              nextWrittenAt,
              nextToolAttrs,
              nextToolInput,
              nextTr.content
            );

            await exporter.export(nextToolSpan);
            prevWrittenAt = nextWrittenAt;
          }

          const toolResultMsgs = convertToolResultsForMessages(consecutiveToolResults);
          reactMessages.push(...toolResultMsgs);
          prevWrittenAt = entryWrittenAt;
        }
      }

      return modelSpanCount;
    };

    api.on<GatewayStopEvent>("gateway_stop", async () => {
      await exporter.dispose();
    });

    if (shouldHookEnabled("gateway_start")) {
      api.on<GatewayStartEvent>("gateway_start", async (event) => {
        const now = Date.now();
        const { ctx, channelId } = getOrCreateContext("system/gateway", undefined, "gateway_start");
        const span = createSpan(
          ctx,
          channelId,
          "gateway_start",
          "gateway",
          now,
          now,
          {
            "gateway.version": event.version || "unknown",
            "gateway.working_dir": event.workingDir || process.cwd(),
          }
        );
        await exporter.export(span);
        if (config.debug) {
          api.logger.info(`[CozeloopTrace] Exported gateway_start span, traceId=${ctx.traceId}`);
        }
      });
    }

    if (shouldHookEnabled("session_start")) {
      api.on<SessionStartEvent>("session_start", async (event, hookCtx: PluginHookContext) => {
        const rawChannelId = resolveChannelId(hookCtx, event.sessionId);
        if (config.debug) {
          api.logger.info(`[CozeloopTrace] session_start hookCtx: ${JSON.stringify({ channelId: hookCtx.channelId, sessionKey: hookCtx.sessionKey, conversationId: hookCtx.conversationId })}`);
        }
        const { ctx, channelId } = getOrCreateContext(rawChannelId, undefined, "session_start");
        const now = Date.now();
        const span = createSpan(
          ctx,
          channelId,
          "session_start",
          "entry",
          now,
          now,
          { "event.type": "session_start" }
        );
        await exporter.export(span);
        if (config.debug) {
          api.logger.info(`[CozeloopTrace] Exported session_start: ${channelId}, traceId=${ctx.traceId}`);
        }
      });
    }

    if (shouldHookEnabled("session_end")) {
      api.on<SessionEndEvent>("session_end", async (event, hookCtx: PluginHookContext) => {
        const rawChannelId = resolveChannelId(hookCtx, event.sessionId);
        if (config.debug) {
          api.logger.info(`[CozeloopTrace] session_end hookCtx: ${JSON.stringify({ channelId: hookCtx.channelId, sessionKey: hookCtx.sessionKey, conversationId: hookCtx.conversationId })}`);
        }
        const { ctx, channelId } = getOrCreateContext(rawChannelId, undefined, "session_end");
        const now = Date.now();
        const span = createSpan(
          ctx,
          channelId,
          "session_end",
          "entry",
          now,
          now,
          {
            "session.duration_ms": event.duration || 0,
            "session.message_count": event.messageCount || 0,
            "session.total_tokens": event.totalTokens || 0,
          },
          undefined,
          { messageCount: event.messageCount, totalTokens: event.totalTokens }
        );
        await exporter.export(span);
        endTurn(channelId);
        if (config.debug) {
          api.logger.info(`[CozeloopTrace] Exported session_end: ${channelId}`);
        }
      });
    }

    if (shouldHookEnabled("message_received")) {
      api.on<MessageReceivedEvent>("message_received", async (event, hookCtx: PluginHookContext) => {
        const rawChannelId = resolveChannelId(hookCtx, event.from || event.metadata?.senderId);
        if (config.debug) {
          api.logger.info(`[CozeloopTrace] message_received hookCtx: ${JSON.stringify({ channelId: hookCtx.channelId, sessionKey: hookCtx.sessionKey, conversationId: hookCtx.conversationId })}, event.from=${event.from}`);
        }
        const { ctx, channelId, isNew } = getOrCreateContext(rawChannelId, undefined, "message_received");
        const now = Date.now();
        let role = event.role;
        if (!role && event.from) {
          role = "user";
        }

        const isNonAgentChannel = !rawChannelId.startsWith("agent/");

        if (isNonAgentChannel) {
          if (role === "user" || !role) {
            lastUserChannelId = channelId;
            lastUserTraceContext = ctx;
            ctx.userInput = event.content;
            if (config.debug) {
              api.logger.info(`[CozeloopTrace] Saved user context: channelId=${channelId}, traceId=${ctx.traceId}`);
            }
          }

          if (!ctx.rootSpanStartTime) {
            ctx.rootSpanStartTime = now;
            if (!ctx.userInput) {
              ctx.userInput = event.content;
            }
            const rootSpanData: SpanData = {
              name: "openclaw_request",
              type: "entry",
              startTime: now,
              attributes: {
                "session.id": channelId,
                "run.id": ctx.runId,
                "turn.id": ctx.turnId,
              },
              input: ctx.userInput,
              traceId: ctx.traceId,
              spanId: ctx.rootSpanId,
            };
            await exporter.startSpan(rootSpanData, ctx.rootSpanId);
            if (config.debug) {
              api.logger.info(`[CozeloopTrace] Started root span: traceId=${ctx.traceId}, spanId=${ctx.rootSpanId}`);
            }
          }

          if (!lastUserTraceContext) {
            lastUserTraceContext = ctx;
            lastUserChannelId = channelId;
          }
        }

        const span = createSpan(
          ctx,
          channelId,
          role === "user" ? "user_message" : "message_received",
          "message",
          now,
          now,
          {
            "message.role": role || "unknown",
            "message.from": event.from || "unknown",
          },
          event.content
        );
        await exporter.export(span);
        if (config.debug) {
          api.logger.info(`[CozeloopTrace] Exported message_received: ${channelId}, role=${role}, traceId=${ctx.traceId}`);
        }
      });
    }

    if (shouldHookEnabled("message_sending")) {
      api.on<MessageSendingEvent>("message_sending", async (event, hookCtx: PluginHookContext) => {
        if (lastUserTraceContext) {
          lastUserTraceContext.lastOutput = event.content;
          if (config.debug) {
            api.logger.info(`[CozeloopTrace] Captured output for root span: traceId=${lastUserTraceContext.traceId}, content=${typeof event.content === 'string' ? event.content.substring(0, 100) : 'non-string'}`);
          }
        } else {
          const rawChannelId = resolveChannelId(hookCtx, event.to);
          const { ctx } = getOrCreateContext(rawChannelId, undefined, "message_sending");
          ctx.lastOutput = event.content;
          if (config.debug) {
            api.logger.info(`[CozeloopTrace] Captured output (fallback) for root span: traceId=${ctx.traceId}`);
          }
        }
      });
    }

    if (shouldHookEnabled("message_sent")) {
      api.on<MessageSentEvent>("message_sent", async (event, hookCtx: PluginHookContext) => {
        if (event.content && event.success) {
          if (lastUserTraceContext) {
            lastUserTraceContext.lastOutput = event.content;
            if (config.debug) {
              api.logger.info(`[CozeloopTrace] Captured output from message_sent: traceId=${lastUserTraceContext.traceId}`);
            }
          } else {
            const rawChannelId = resolveChannelId(hookCtx, event.to);
            const { ctx } = getOrCreateContext(rawChannelId, undefined, "message_sent");
            ctx.lastOutput = event.content;
            if (config.debug) {
              api.logger.info(`[CozeloopTrace] Captured output from message_sent (fallback): traceId=${ctx.traceId}`);
            }
          }
        }
      });
    }

    let lastLlmInput: unknown = undefined;
    let lastLlmStartTime: number | undefined = undefined;
    let lastLlmSpanId: string | undefined = undefined;

    if (shouldHookEnabled("llm_input")) {
      api.on<LlmInputEvent>("llm_input", async (event, hookCtx: PluginHookContext) => {
        const rawChannelId = resolveChannelId(hookCtx);
        if (config.debug) {
          api.logger.info(`[CozeloopTrace] llm_input hookCtx: ${JSON.stringify({ channelId: hookCtx.channelId, sessionKey: hookCtx.sessionKey, conversationId: hookCtx.conversationId })}, event.runId=${event.runId}`);
        }
        const { ctx } = getOrCreateContext(rawChannelId, event.runId, "llm_input");
        ctx.llmStartTime = Date.now();
        ctx.llmSpanId = generateId(16);
        ctx.lastModelProvider = event.provider;
        ctx.lastModelId = event.model;
        ctx.reactCount = 0;

        const messages: Array<{ role: string; content: unknown }> = [];
        if (event.systemPrompt) {
          messages.push({ role: "system", content: safeClone(event.systemPrompt) });
        }
        if (event.historyMessages && event.historyMessages.length > 0) {
          messages.push(...event.historyMessages.map((msg) => safeClone(msg)));
        }
        if (event.prompt) {
          messages.push({ role: "user", content: safeClone(event.prompt) });
        }
        const convertToolCallInPlace = (target: Record<string, unknown>): void => {
          if (target.type !== "toolCall") return;
          target.type = "tool_use";
          if ("arguments" in target) {
            target.input = target.arguments;
            delete target.arguments;
          }
        };
        const convertToolCallDeepInPlace = (value: unknown): void => {
          if (!value) return;
          if (Array.isArray(value)) {
            for (const item of value) {
              convertToolCallDeepInPlace(item);
            }
            return;
          }
          if (typeof value !== "object") return;
          const obj = value as Record<string, unknown>;
          convertToolCallInPlace(obj);
          if ("content" in obj) {
            convertToolCallDeepInPlace(obj.content);
          }
        };
        for (const message of messages as unknown as Array<Record<string, unknown>>) {
          convertToolCallDeepInPlace(message);
          if ("toolCallId" in message) {
            message.tool_call_id = message.toolCallId;
            delete message.toolCallId;
          }
          if (message.role === "toolResult") {
            message.role = "tool";
          }
        }

        ctx.llmInput = {
          "messages": messages,
        };
        lastLlmInput = ctx.llmInput;
        lastLlmStartTime = ctx.llmStartTime;
        lastLlmSpanId = ctx.llmSpanId;

        if (config.debug) {
          api.logger.info(`[CozeloopTrace] LLM input started: ${event.provider}/${event.model}, runId=${event.runId}, traceId=${ctx.traceId}`);
        }
      });
    }

    if (shouldHookEnabled("llm_output")) {
      api.on<LlmOutputEvent>("llm_output", async (event, hookCtx: PluginHookContext) => {
        const rawChannelId = resolveChannelId(hookCtx);
        if (config.debug) {
          api.logger.info(`[CozeloopTrace][DEBUG] llm_output event.usage=${JSON.stringify(event.usage)}`);
          api.logger.info(`[CozeloopTrace][DEBUG] llm_output event.lastAssistant=${JSON.stringify(event.lastAssistant)}`);
          api.logger.info(`[CozeloopTrace][DEBUG] llm_output event keys=${JSON.stringify(Object.keys(event as unknown as object))}`);

          api.logger.info(`[CozeloopTrace] llm_output hookCtx: ${JSON.stringify({ channelId: hookCtx.channelId, sessionKey: hookCtx.sessionKey, conversationId: hookCtx.conversationId })}, event.runId=${event.runId}`);
        }
        const { ctx, channelId } = getOrCreateContext(rawChannelId, event.runId, "llm_output");
        const now = Date.now();
        const startTime = ctx.llmStartTime || lastLlmStartTime || now;

        if (event.assistantTexts && event.assistantTexts.length > 0) {
          const outputText = event.assistantTexts.join("\n");
          ctx.lastOutput = outputText;
          if (lastUserTraceContext) {
            lastUserTraceContext.lastOutput = outputText;
          }
          if (config.debug) {
            api.logger.info(`[CozeloopTrace] Captured output from llm_output (will use last): traceId=${ctx.traceId}, length=${outputText.length}`);
          }
        }

        const llmInput = ctx.llmInput || lastLlmInput;
        const llmSpanId = ctx.llmSpanId || lastLlmSpanId;

        if (config.debug) {
          api.logger.info(`[CozeloopTrace] llm_output ctx: traceId=${ctx.traceId}, rootSpanId=${ctx.rootSpanId}, llmSpanId=${llmSpanId || "none"}, hasInput=${!!llmInput}`);
        }

        let sessionBasedSuccess = false;

        try {
          const { entries, userWrittenAt } = readCurrentTurnReactSequence(hookCtx);
          const hasAssistantEntry = entries.some((e) => e.type === "assistant");

          if (entries.length > 0 && hasAssistantEntry) {
            const agentStart = ctx.agentStartTime || ctx.llmStartTime || lastLlmStartTime || now;
            const modelCount = await buildReactSpans(ctx, channelId, entries, llmInput, agentStart, userWrittenAt);
            if (modelCount > 0) {
              sessionBasedSuccess = true;
              ctx.sessionBasedSpansCreated = true;
              if (config.debug) {
                api.logger.info(`[CozeloopTrace] Session-based react spans created: modelCount=${modelCount}, traceId=${ctx.traceId}`);
              }
            }
          }
        } catch {
          if (config.debug) {
            api.logger.info(`[CozeloopTrace] Session-based span creation failed, falling back to hook data, traceId=${ctx.traceId}`);
          }
        }

        if (!sessionBasedSuccess) {
          if (ctx.pendingToolSpans) {
            for (const pts of ctx.pendingToolSpans) {
              const toolSpan = createSpan(
                ctx,
                channelId,
                pts.toolName,
                "tool",
                pts.toolStartTime,
                pts.toolEndTime,
                pts.toolError ? { "error.msg": String(pts.toolError) } : {},
                pts.toolInput,
                pts.toolError ? { error: pts.toolError } : pts.toolOutput
              );
              toolSpan.spanId = pts.toolSpanId;
              await exporter.export(toolSpan);
              if (config.debug) {
                api.logger.info(`[CozeloopTrace] Exported pending tool span (fallback): ${pts.toolName}, spanId=${pts.toolSpanId}, traceId=${ctx.traceId}`);
              }
            }
          }

          const lastAssistantUsage = (event.lastAssistant as { usage?: { input?: number; output?: number } } | undefined)?.usage;
          const inputTokens = event.usage?.input ?? lastAssistantUsage?.input ?? 0;
          const outputTokens = event.usage?.output ?? lastAssistantUsage?.output ?? 0;

          const spanAttributes: Record<string, string | number | boolean> = {
            "gen_ai.provider.name": event.provider,
            "gen_ai.request.model": event.model,
            "gen_ai.usage.input_tokens": inputTokens,
            "gen_ai.usage.output_tokens": outputTokens,
          };

          const finalOutput = formatAssistantOutput(
            event.assistantTexts?.map((t: string) => ({ type: "text", text: t })) ?? [],
            "stop"
          );

          const span = createSpan(
            ctx,
            channelId,
            `${event.provider}/${event.model}`,
            "model",
            startTime,
            now,
            spanAttributes,
            llmInput,
            finalOutput
          );

          if (llmSpanId) {
            span.spanId = llmSpanId;
          }

          if (config.debug) {
            api.logger.info(`[CozeloopTrace] llm_output span created (fallback): spanId=${span.spanId}, parentSpanId=${span.parentSpanId}`);
          }

          await exporter.export(span);
          if (config.debug) {
            api.logger.info(`[CozeloopTrace] Exported LLM span (fallback): ${event.provider}/${event.model}, duration=${now - startTime}ms, traceId=${ctx.traceId}`);
          }
        }

        ctx.llmStartTime = undefined;
        ctx.llmSpanId = undefined;
        ctx.llmInput = undefined;
        ctx.reactCount = 0;
        ctx.pendingToolSpans = undefined;
        ctx.sessionBasedSpansCreated = undefined;
        lastLlmInput = undefined;
        lastLlmStartTime = undefined;
        lastLlmSpanId = undefined;

        if (ctx.pendingCleanup) {
          const cleanup = ctx.pendingCleanup;
          ctx.pendingCleanup = undefined;

          const savedCtx = cleanup.savedLastUserTraceContext;
          if (savedCtx) {
            savedCtx.lastOutput = undefined;
          }
          lastUserChannelId = undefined;
          lastUserTraceContext = undefined;
          if (cleanup.savedLastUserChannelId) {
            endTurn(cleanup.savedLastUserChannelId);
          }
          if (cleanup.originalChannelId && cleanup.originalChannelId !== cleanup.savedLastUserChannelId) {
            endTurn(cleanup.originalChannelId);
          }

          const rootCtx = savedCtx || ctx;
          if (rootCtx.rootSpanStartTime) {
            const rootSpanId = rootCtx.rootSpanId;
            const rootSpanStartTime = rootCtx.rootSpanStartTime;
            const userInput = rootCtx.userInput;
            const traceId = rootCtx.traceId;
            const agentChannelId = cleanup.agentChannelId;

            setTimeout(async () => {
              const agentCtx = getContextByChannel(agentChannelId);
              const finalOutput = agentCtx?.lastOutput || rootCtx.lastOutput;
              if (config.debug) {
                api.logger.info(`[CozeloopTrace] Ending root span (delayed) with input=${userInput ? 'present' : 'missing'}, output=${finalOutput ? 'present' : 'missing'}`);
              }
              const endTime = Date.now();
              exporter.endSpanById(
                rootSpanId,
                endTime,
                {
                  "request.duration_ms": endTime - rootSpanStartTime,
                },
                finalOutput,
                userInput
              );

              if (config.debug) {
                api.logger.info(`[CozeloopTrace] Ended root span: spanId=${rootSpanId}, duration=${endTime - rootSpanStartTime}ms, traceId=${traceId}`);
              }

              await exporter.flush();
              exporter.endTrace();
            }, 100);
          } else {
            await exporter.flush();
            exporter.endTrace();
          }
        }
      });
    }

    if (shouldHookEnabled("before_tool_call")) {
      api.on<BeforeToolCallEvent>("before_tool_call", async (event, hookCtx: PluginHookContext) => {
        const rawChannelId = resolveChannelId(hookCtx);
        if (config.debug) {
          api.logger.info(`[CozeloopTrace] before_tool_call hookCtx: ${JSON.stringify({ channelId: hookCtx.channelId, sessionKey: hookCtx.sessionKey, conversationId: hookCtx.conversationId })}, toolName=${event.toolName}`);
        }
        const { ctx, channelId } = getOrCreateContext(rawChannelId, undefined, "before_tool_call");

        pendingToolCall = {
          toolName: event.toolName,
          toolSpanId: generateId(16),
          toolStartTime: Date.now(),
          toolInput: event.params,
          traceContext: ctx,
          channelId: channelId,
        };

        ctx.reactCount = (ctx.reactCount || 0) + 1;

        if (config.debug) {
          api.logger.info(`[CozeloopTrace] Tool call started: ${event.toolName}, spanId=${pendingToolCall.toolSpanId}, traceId=${ctx.traceId}`);
        }
      });
    }

    if (shouldHookEnabled("after_tool_call")) {
      api.on<AfterToolCallEvent>("after_tool_call", async (event, hookCtx: PluginHookContext) => {
        if (config.debug) {
          api.logger.info(`[CozeloopTrace] after_tool_call hookCtx: ${JSON.stringify({ channelId: hookCtx.channelId, sessionKey: hookCtx.sessionKey, conversationId: hookCtx.conversationId })}, toolName=${event.toolName}`);
        }

        if (!pendingToolCall || pendingToolCall.toolName !== event.toolName) {
          if (config.debug) {
            api.logger.info(`[CozeloopTrace] Skipping after_tool_call: no pending tool or name mismatch, toolName=${event.toolName}, pending=${pendingToolCall?.toolName}`);
          }
          return;
        }

        const { toolName, toolSpanId, toolStartTime, toolInput, traceContext } = pendingToolCall;
        pendingToolCall = undefined;

        const now = Date.now();

        if (!traceContext.pendingToolSpans) {
          traceContext.pendingToolSpans = [];
        }

        traceContext.pendingToolSpans.push({
          toolName,
          toolSpanId,
          toolStartTime,
          toolEndTime: now,
          toolInput,
          toolOutput: event.error ? { error: event.error } : event.result,
          toolError: event.error ? String(event.error) : undefined,
        });

        if (config.debug) {
          api.logger.info(`[CozeloopTrace] Collected pending tool span: ${toolName}, spanId=${toolSpanId}, duration=${now - toolStartTime}ms, traceId=${traceContext.traceId}`);
        }
      });
    }

    if (shouldHookEnabled("before_agent_start")) {
      api.on<BeforeAgentStartEvent>("before_agent_start", async (event, hookCtx: PluginHookContext) => {
        const rawChannelId = resolveChannelId(hookCtx);
        const agentId = hookCtx.agentId || event.agentId || "main";
        if (config.debug) {
          api.logger.info(`[CozeloopTrace] before_agent_start hookCtx: ${JSON.stringify({ channelId: hookCtx.channelId, sessionKey: hookCtx.sessionKey, conversationId: hookCtx.conversationId, agentId: hookCtx.agentId })}, event.agentId=${event.agentId}`);
        }
        const { ctx, channelId } = getOrCreateContext(rawChannelId, undefined, "before_agent_start");

        if (ctx.agentSpanId) {
          if (config.debug) {
            api.logger.info(`[CozeloopTrace] Agent span already started, skipping: ${agentId}, traceId=${ctx.traceId}`);
          }
          return;
        }

        const now = Date.now();
        ctx.agentStartTime = now;
        ctx.agentSpanId = generateId(16);

        const spanData: SpanData = {
          name: agentId,
          type: "agent",
          startTime: now,
          attributes: {
            "agent.id": agentId,
            "session.id": channelId,
            "run.id": ctx.runId,
            "turn.id": ctx.turnId,
          },
          traceId: ctx.traceId,
          spanId: ctx.agentSpanId,
          parentSpanId: ctx.rootSpanId,
        };

        await exporter.startSpan(spanData, ctx.agentSpanId);

        if (config.debug) {
          api.logger.info(`[CozeloopTrace] Started agent span: ${agentId}, spanId=${ctx.agentSpanId}, traceId=${ctx.traceId}`);
        }
      });
    }

    if (shouldHookEnabled("agent_end")) {
      api.on<AgentEndEvent>("agent_end", async (event, hookCtx: PluginHookContext) => {
        const rawChannelId = resolveChannelId(hookCtx);
        if (config.debug) {
          api.logger.info(`[CozeloopTrace] agent_end hookCtx: ${JSON.stringify({ channelId: hookCtx.channelId, sessionKey: hookCtx.sessionKey, conversationId: hookCtx.conversationId })}`);
        }
        const { ctx, channelId } = getOrCreateContext(rawChannelId, undefined, "agent_end");
        const now = Date.now();

        if (ctx.agentSpanId) {
          exporter.endSpanById(
            ctx.agentSpanId,
            now,
            {
              "agent.duration_ms": event.durationMs || 0,
              "agent.message_count": event.messageCount || 0,
              "agent.tool_call_count": event.toolCallCount || 0,
              "agent.total_tokens": event.usage?.total || 0,
            },
            { usage: event.usage, cost: event.cost }
          );

          if (config.debug) {
            api.logger.info(`[CozeloopTrace] Ended agent span: spanId=${ctx.agentSpanId}, duration=${event.durationMs}ms, traceId=${ctx.traceId}`);
          }

          ctx.agentSpanId = undefined;
          ctx.agentStartTime = undefined;
        }

        ctx.pendingCleanup = {
          savedLastUserTraceContext: lastUserTraceContext,
          savedLastUserChannelId: lastUserChannelId,
          originalChannelId: ctx.originalChannelId || lastUserChannelId || channelId,
          agentChannelId: channelId,
        };
      });
    }

    api.logger.info(
      `[CozeloopTrace] Plugin activated (endpoint: ${config.endpoint}, workspace: ${config.workspaceId})`
    );
  },
};

export default cozeloopTracePlugin;
