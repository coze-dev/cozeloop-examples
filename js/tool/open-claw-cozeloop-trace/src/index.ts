import type {
  OpenClawPlugin,
  OpenClawPluginApi,
  PluginHookContext,
  FornaxTraceConfig,
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
import { FornaxExporter } from "./fornax-exporter.js";

function generateId(length = 16): string {
  const chars = "0123456789abcdef";
  let result = "";
  for (let i = 0; i < length; i++) {
    result += chars[Math.floor(Math.random() * chars.length)];
  }
  return result;
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

const fornaxTracePlugin: OpenClawPlugin = {
  id: "openclaw-fornax-trace",
  name: "OpenClaw Fornax Trace",
  version: "0.1.0",
  description: "Report OpenClaw execution traces to Fornax via OpenTelemetry",

  activate(api: OpenClawPluginApi) {
    const pluginConfig = api.pluginConfig || {};
    
    const ak = pluginConfig.ak as string | undefined;
    const sk = pluginConfig.sk as string | undefined;
    const authorization = pluginConfig.authorization as string | undefined;
    const workspaceId = pluginConfig.workspaceId as string | undefined;
    
    const hasAkSk = ak && sk;
    const hasAuthWorkspace = authorization && workspaceId;
    
    if (!hasAkSk && !hasAuthWorkspace) {
      api.logger.error(
        "[FornaxTrace] Missing required configuration: either 'ak'+'sk' or 'authorization'+'workspaceId' must be provided"
      );
      return;
    }

    const region = (pluginConfig.region as FornaxTraceConfig['region']) || "CN";
    
    const getDefaultEndpoint = (r: FornaxTraceConfig['region']): string => {
      switch (r) {
        case "I18N":
          return "https://fornax.byteintl.net/open-api/observability/opentelemetry";
        case "I18N_VA":
          return "https://fornax-va.byteintl.net/open-api/observability/opentelemetry";
        case "NON_TT":
          return "https://fornax-i18nbd.byteintl.net/open-api/observability/opentelemetry";
        case "CN":
        default:
          return "https://fornax.bytedance.net/open-api/observability/opentelemetry";
      }
    };

    const config: FornaxTraceConfig = {
      endpoint: (pluginConfig.endpoint as string) || getDefaultEndpoint(region),
      ak,
      sk,
      region,
      authorization,
      workspaceId: workspaceId || "",
      serviceName: (pluginConfig.serviceName as string) || "openclaw-agent",
      debug: (pluginConfig.debug as boolean) || false,
      batchSize: (pluginConfig.batchSize as number) || 10,
      batchInterval: (pluginConfig.batchInterval as number) || 5000,
      enabledHooks: pluginConfig.enabledHooks as string[] | undefined,
    };

    const exporter = new FornaxExporter(api, config);
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
          api.logger.info(`[FornaxTrace] LINKING agent to user context: hook=${hookName}, agentChannel=${rawChannelId}, userChannel=${channelId}, traceId=${activeCtx.traceId}`);
        }
      }

      let isNew = false;
      if (!activeCtx) {
        activeCtx = startTurn(effectiveRunId, channelId, rawChannelId !== channelId ? rawChannelId : undefined);
        isNew = true;
        if (config.debug) {
          api.logger.info(`[FornaxTrace] NEW TraceContext created: hook=${hookName}, channelId=${channelId}, runId=${effectiveRunId}, traceId=${activeCtx.traceId}`);
        }
      } else if (config.debug) {
        api.logger.info(`[FornaxTrace] REUSING TraceContext: hook=${hookName}, channelId=${channelId}, runId=${effectiveRunId}, traceId=${activeCtx.traceId}`);
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
          api.logger.info(`[FornaxTrace] Exported gateway_start span, traceId=${ctx.traceId}`);
        }
      });
    }

    if (shouldHookEnabled("session_start")) {
      api.on<SessionStartEvent>("session_start", async (event, hookCtx: PluginHookContext) => {
        const rawChannelId = resolveChannelId(hookCtx, event.sessionId);
        if (config.debug) {
          api.logger.info(`[FornaxTrace] session_start hookCtx: ${JSON.stringify({channelId: hookCtx.channelId, sessionKey: hookCtx.sessionKey, conversationId: hookCtx.conversationId})}`);
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
          api.logger.info(`[FornaxTrace] Exported session_start: ${channelId}, traceId=${ctx.traceId}`);
        }
      });
    }

    if (shouldHookEnabled("session_end")) {
      api.on<SessionEndEvent>("session_end", async (event, hookCtx: PluginHookContext) => {
        const rawChannelId = resolveChannelId(hookCtx, event.sessionId);
        if (config.debug) {
          api.logger.info(`[FornaxTrace] session_end hookCtx: ${JSON.stringify({channelId: hookCtx.channelId, sessionKey: hookCtx.sessionKey, conversationId: hookCtx.conversationId})}`);
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
          api.logger.info(`[FornaxTrace] Exported session_end: ${channelId}`);
        }
      });
    }

    if (shouldHookEnabled("message_received")) {
      api.on<MessageReceivedEvent>("message_received", async (event, hookCtx: PluginHookContext) => {
        const rawChannelId = resolveChannelId(hookCtx, event.from || event.metadata?.senderId);
        if (config.debug) {
          api.logger.info(`[FornaxTrace] message_received hookCtx: ${JSON.stringify({channelId: hookCtx.channelId, sessionKey: hookCtx.sessionKey, conversationId: hookCtx.conversationId})}, event.from=${event.from}`);
        }
        const { ctx, channelId, isNew } = getOrCreateContext(rawChannelId, undefined, "message_received");
        const now = Date.now();
        let role = event.role;
        if (!role && event.from) {
          role = "user";
        }
        
        if (role === "user" && !rawChannelId.startsWith("agent/")) {
          lastUserChannelId = channelId;
          lastUserTraceContext = ctx;
          ctx.userInput = event.content;
          if (config.debug) {
            api.logger.info(`[FornaxTrace] Saved user context: channelId=${channelId}, traceId=${ctx.traceId}`);
          }
          
          if (isNew) {
            ctx.rootSpanStartTime = now;
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
            exporter.startSpan(rootSpanData, ctx.rootSpanId);
            if (config.debug) {
              api.logger.info(`[FornaxTrace] Started root span: traceId=${ctx.traceId}, spanId=${ctx.rootSpanId}`);
            }
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
          api.logger.info(`[FornaxTrace] Exported message_received: ${channelId}, role=${role}, traceId=${ctx.traceId}`);
        }
      });
    }

    if (shouldHookEnabled("message_sending")) {
      api.on<MessageSendingEvent>("message_sending", async (event, hookCtx: PluginHookContext) => {
        if (lastUserTraceContext) {
          lastUserTraceContext.lastOutput = event.content;
          if (config.debug) {
            api.logger.info(`[FornaxTrace] Captured output for root span: traceId=${lastUserTraceContext.traceId}, content=${typeof event.content === 'string' ? event.content.substring(0, 100) : 'non-string'}`);
          }
        } else {
          const rawChannelId = resolveChannelId(hookCtx, event.to);
          const { ctx } = getOrCreateContext(rawChannelId, undefined, "message_sending");
          ctx.lastOutput = event.content;
          if (config.debug) {
            api.logger.info(`[FornaxTrace] Captured output (fallback) for root span: traceId=${ctx.traceId}`);
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
              api.logger.info(`[FornaxTrace] Captured output from message_sent: traceId=${lastUserTraceContext.traceId}`);
            }
          } else {
            const rawChannelId = resolveChannelId(hookCtx, event.to);
            const { ctx } = getOrCreateContext(rawChannelId, undefined, "message_sent");
            ctx.lastOutput = event.content;
            if (config.debug) {
              api.logger.info(`[FornaxTrace] Captured output from message_sent (fallback): traceId=${ctx.traceId}`);
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
          api.logger.info(`[FornaxTrace] llm_input hookCtx: ${JSON.stringify({channelId: hookCtx.channelId, sessionKey: hookCtx.sessionKey, conversationId: hookCtx.conversationId})}, event.runId=${event.runId}`);
        }
        const { ctx } = getOrCreateContext(rawChannelId, event.runId, "llm_input");
        ctx.llmStartTime = Date.now();
        ctx.llmSpanId = generateId(16);
        
        const messages: Array<{ role: string; content: unknown }> = [];
        if (event.systemPrompt) {
          messages.push({ role: "system", content: event.systemPrompt });
        }
        if (event.historyMessages && event.historyMessages.length > 0) {
          messages.push(...event.historyMessages);
        }
        if (event.prompt) {
          messages.push({ role: "user", content: event.prompt });
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
        }
        
        ctx.llmInput = {
          "messages": messages,
        };
        lastLlmInput = ctx.llmInput;
        lastLlmStartTime = ctx.llmStartTime;
        lastLlmSpanId = ctx.llmSpanId;
        
        if (config.debug) {
          api.logger.info(`[FornaxTrace] LLM input started: ${event.provider}/${event.model}, runId=${event.runId}, traceId=${ctx.traceId}`);
        }
      });
    }
    
    if (shouldHookEnabled("llm_output")) {
      api.on<LlmOutputEvent>("llm_output", async (event, hookCtx: PluginHookContext) => {
        const rawChannelId = resolveChannelId(hookCtx);
        if (config.debug) {
          // DEBUG: dump full event to diagnose token fields
          api.logger.info(`[FornaxTrace][DEBUG] llm_output event.usage=${JSON.stringify(event.usage)}`);
          api.logger.info(`[FornaxTrace][DEBUG] llm_output event.lastAssistant=${JSON.stringify(event.lastAssistant)}`);
          api.logger.info(`[FornaxTrace][DEBUG] llm_output event keys=${JSON.stringify(Object.keys(event as unknown as object))}`);

          api.logger.info(`[FornaxTrace] llm_output hookCtx: ${JSON.stringify({channelId: hookCtx.channelId, sessionKey: hookCtx.sessionKey, conversationId: hookCtx.conversationId})}, event.runId=${event.runId}`);
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
            api.logger.info(`[FornaxTrace] Captured output from llm_output (will use last): traceId=${ctx.traceId}, length=${outputText.length}`);
          }
        }
        
        const llmInput = ctx.llmInput || lastLlmInput;
        const llmSpanId = ctx.llmSpanId || lastLlmSpanId;

        if (config.debug) {
          api.logger.info(`[FornaxTrace] llm_output ctx: traceId=${ctx.traceId}, rootSpanId=${ctx.rootSpanId}, llmSpanId=${llmSpanId || "none"}, hasInput=${!!llmInput}`);
        }

        // event.usage comes from getUsageTotals() which may be undefined when the
        // stream wrapper doesn't populate assistantMessage.usage (regression in 2026.3.7+).
        // Fall back to lastAssistant.usage which is the pi-ai Usage object and always
        // carries the per-call token counts directly from the provider response.
        const lastAssistantUsage = (event.lastAssistant as { usage?: { input?: number; output?: number } } | undefined)?.usage;
        const inputTokens = event.usage?.input ?? lastAssistantUsage?.input ?? 0;
        const outputTokens = event.usage?.output ?? lastAssistantUsage?.output ?? 0;

        const span = createSpan(
          ctx,
          channelId,
          `${event.provider}/${event.model}`,
          "model",
          startTime,
          now,
          {
            "gen_ai.provider.name": event.provider,
            "gen_ai.request.model": event.model,
            "gen_ai.usage.input_tokens": inputTokens,
            "gen_ai.usage.output_tokens": outputTokens,
          },
          llmInput,
          { assistantTexts: event.assistantTexts?.slice(0, 3) }
        );
        
        if (llmSpanId) {
          span.spanId = llmSpanId;
        }
        ctx.llmStartTime = undefined;
        ctx.llmSpanId = undefined;
        ctx.llmInput = undefined;
        lastLlmInput = undefined;
        lastLlmStartTime = undefined;
        lastLlmSpanId = undefined;
        
        if (config.debug) {
          api.logger.info(`[FornaxTrace] llm_output span created: spanId=${span.spanId}, parentSpanId=${span.parentSpanId}`);
        }
        
        await exporter.export(span);
        if (config.debug) {
          api.logger.info(`[FornaxTrace] Exported LLM span: ${event.provider}/${event.model}, duration=${now - startTime}ms, traceId=${ctx.traceId}`);
        }
      });
    }

    if (shouldHookEnabled("before_tool_call")) {
      api.on<BeforeToolCallEvent>("before_tool_call", async (event, hookCtx: PluginHookContext) => {
        const rawChannelId = resolveChannelId(hookCtx);
        if (config.debug) {
          api.logger.info(`[FornaxTrace] before_tool_call hookCtx: ${JSON.stringify({channelId: hookCtx.channelId, sessionKey: hookCtx.sessionKey, conversationId: hookCtx.conversationId})}, toolName=${event.toolName}`);
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
        
        if (config.debug) {
          api.logger.info(`[FornaxTrace] Tool call started: ${event.toolName}, spanId=${pendingToolCall.toolSpanId}, traceId=${ctx.traceId}`);
        }
      });
    }

    if (shouldHookEnabled("after_tool_call")) {
      api.on<AfterToolCallEvent>("after_tool_call", async (event, hookCtx: PluginHookContext) => {
        if (config.debug) {
          api.logger.info(`[FornaxTrace] after_tool_call hookCtx: ${JSON.stringify({channelId: hookCtx.channelId, sessionKey: hookCtx.sessionKey, conversationId: hookCtx.conversationId})}, toolName=${event.toolName}`);
        }
        
        if (!pendingToolCall || pendingToolCall.toolName !== event.toolName) {
          if (config.debug) {
            api.logger.info(`[FornaxTrace] Skipping after_tool_call: no pending tool or name mismatch, toolName=${event.toolName}, pending=${pendingToolCall?.toolName}`);
          }
          return;
        }
        
        const { toolName, toolSpanId, toolStartTime, toolInput, traceContext, channelId } = pendingToolCall;
        pendingToolCall = undefined;
        
        const now = Date.now();
        
        const span = createSpan(
          traceContext,
          channelId,
          toolName,
          "tool",
          toolStartTime,
          now,
          {
            "tool.name": toolName,
            "tool.duration_ms": event.durationMs || (now - toolStartTime),
            "tool.error": event.error ? true : false,
          },
          toolInput,
          event.error ? { error: event.error } : event.result
        );
        
        span.spanId = toolSpanId;
        
        await exporter.export(span);
        if (config.debug) {
          api.logger.info(`[FornaxTrace] Exported tool span: ${toolName}, spanId=${toolSpanId}, duration=${now - toolStartTime}ms, traceId=${traceContext.traceId}`);
        }
      });
    }

    if (shouldHookEnabled("before_agent_start")) {
      api.on<BeforeAgentStartEvent>("before_agent_start", async (event, hookCtx: PluginHookContext) => {
        const rawChannelId = resolveChannelId(hookCtx);
        const agentId = hookCtx.agentId || event.agentId || "main";
        if (config.debug) {
          api.logger.info(`[FornaxTrace] before_agent_start hookCtx: ${JSON.stringify({channelId: hookCtx.channelId, sessionKey: hookCtx.sessionKey, conversationId: hookCtx.conversationId, agentId: hookCtx.agentId})}, event.agentId=${event.agentId}`);
        }
        const { ctx, channelId } = getOrCreateContext(rawChannelId, undefined, "before_agent_start");
        
        if (ctx.agentSpanId) {
          if (config.debug) {
            api.logger.info(`[FornaxTrace] Agent span already started, skipping: ${agentId}, traceId=${ctx.traceId}`);
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
        
        exporter.startSpan(spanData, ctx.agentSpanId);
        
        if (config.debug) {
          api.logger.info(`[FornaxTrace] Started agent span: ${agentId}, spanId=${ctx.agentSpanId}, traceId=${ctx.traceId}`);
        }
      });
    }

    if (shouldHookEnabled("agent_end")) {
      api.on<AgentEndEvent>("agent_end", async (event, hookCtx: PluginHookContext) => {
        const rawChannelId = resolveChannelId(hookCtx);
        if (config.debug) {
          api.logger.info(`[FornaxTrace] agent_end hookCtx: ${JSON.stringify({channelId: hookCtx.channelId, sessionKey: hookCtx.sessionKey, conversationId: hookCtx.conversationId})}`);
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
            api.logger.info(`[FornaxTrace] Ended agent span: spanId=${ctx.agentSpanId}, duration=${event.durationMs}ms, traceId=${ctx.traceId}`);
          }
          
          ctx.agentSpanId = undefined;
          ctx.agentStartTime = undefined;
        }
        
        const savedLastUserTraceContext = lastUserTraceContext;
        if (savedLastUserTraceContext) {
          savedLastUserTraceContext.lastOutput = undefined;
        }
        const savedLastUserChannelId = lastUserChannelId;
        const originalChannelId = ctx.originalChannelId || savedLastUserChannelId || channelId;
        lastUserChannelId = undefined;
        lastUserTraceContext = undefined;
        if (savedLastUserChannelId) {
          endTurn(savedLastUserChannelId);
        }
        if (originalChannelId && originalChannelId !== savedLastUserChannelId) {
          endTurn(originalChannelId);
        }
        
        const rootCtx = savedLastUserTraceContext || ctx;
        const agentChannelId = channelId;
        if (rootCtx.rootSpanStartTime) {
          const rootSpanId = rootCtx.rootSpanId;
          const rootSpanStartTime = rootCtx.rootSpanStartTime;
          const userInput = rootCtx.userInput;
          const traceId = rootCtx.traceId;
          
          setTimeout(async () => {
            const agentCtx = getContextByChannel(agentChannelId);
            const finalOutput = agentCtx?.lastOutput || rootCtx.lastOutput;
            if (config.debug) {
              api.logger.info(`[FornaxTrace] Ending root span (delayed) with input=${userInput ? 'present' : 'missing'}, output=${finalOutput ? 'present' : 'missing'}`);
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
              api.logger.info(`[FornaxTrace] Ended root span: spanId=${rootSpanId}, duration=${endTime - rootSpanStartTime}ms, traceId=${traceId}`);
            }
            
            await exporter.flush();
            exporter.endTrace();
          }, 100);
        } else {
          await exporter.flush();
          exporter.endTrace();
        }
      });
    }

    api.logger.info(
      `[FornaxTrace] Plugin activated (endpoint: ${config.endpoint}, workspace: ${config.workspaceId})`
    );
  },
};

export default fornaxTracePlugin;
