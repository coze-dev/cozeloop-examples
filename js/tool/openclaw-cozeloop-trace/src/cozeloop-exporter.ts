import type { SpanData, CozeloopTraceConfig, OpenClawPluginApi } from "./types.js";
import { trace, context, SpanKind, SpanStatusCode, Context, Span as ApiSpan } from "@opentelemetry/api";
import { BasicTracerProvider, BatchSpanProcessor } from "@opentelemetry/sdk-trace-base";
import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-proto";
import { Resource } from "@opentelemetry/resources";
import { ATTR_SERVICE_NAME, ATTR_SERVICE_INSTANCE_ID } from "@opentelemetry/semantic-conventions";
import { hostname } from "os";
import { basename } from "path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { version: PLUGIN_VERSION } = require("../package.json") as { version: string };

export class CozeloopExporter {
  private config: CozeloopTraceConfig;
  private api: OpenClawPluginApi;
  private provider: BasicTracerProvider | null = null;
  private tracer: ReturnType<typeof trace.getTracer> | null = null;
  private initialized: boolean = false;
  private initPromise: Promise<void> | null = null;

  // Per-trace context: keyed by the plugin-level rootSpanId so that
  // concurrent or overlapping traces never stomp on each other.
  private traceContexts: Map<string, { rootSpan: ApiSpan; rootContext: Context; agentSpan?: ApiSpan; agentContext?: Context }> = new Map();
  private openSpans: Map<string, ApiSpan> = new Map();

  constructor(api: OpenClawPluginApi, config: CozeloopTraceConfig) {
    this.api = api;
    this.config = config;
  }

  private async ensureInitialized(): Promise<void> {
    if (this.initialized) return;
    if (this.initPromise) return this.initPromise;

    this.initPromise = this.initialize();
    await this.initPromise;
  }

  private async initialize(): Promise<void> {
    this.api.logger.info(`[CozeloopTrace] Initializing exporter...`);

    const instanceName = this.config.serviceName || basename(process.cwd()) || "openclaw-agent";
    const instanceId = `${instanceName}@${hostname()}:${process.pid}`;

    const resource = new Resource({
      [ATTR_SERVICE_NAME]: this.config.serviceName,
      [ATTR_SERVICE_INSTANCE_ID]: instanceId,
      "host.name": hostname(),
    });

    const authorization = this.config.authorization;
    const workspaceId = this.config.workspaceId;

    this.api.logger.info(`[CozeloopTrace] Using authorization, workspaceId=${workspaceId}, tokenLength=${authorization?.length}`);

    const exporter = new OTLPTraceExporter({
      url: `${this.config.endpoint}/v1/traces`,
      headers: {
        "Authorization": authorization!,
        "cozeloop-workspace-id": workspaceId!,
      },
    });

    this.provider = new BasicTracerProvider({ resource });
    this.provider.addSpanProcessor(new BatchSpanProcessor(exporter, {
      maxQueueSize: 100,
      maxExportBatchSize: this.config.batchSize || 10,
      scheduledDelayMillis: this.config.batchInterval || 5000,
    }));

    // Do NOT call this.provider.register() — it sets the global TracerProvider
    // singleton, so if the plugin is activated more than once (e.g. gateway +
    // plugins subsystem), the second instance would silently get a NOOP tracer
    // while its hooks override those of the first instance, causing all trace
    // operations to become no-ops.  Instead, obtain the tracer directly from
    // our own provider instance.
    this.tracer = this.provider.getTracer("openclaw-cozeloop-trace", PLUGIN_VERSION);
    this.initialized = true;

    this.api.logger.info(`[CozeloopTrace] Exporter initialized with Authorization, workspaceId=${workspaceId}`);
  }

  async startSpan(spanData: SpanData, spanId: string): Promise<void> {
    try {
      await this.ensureInitialized();
      this.doStartSpan(spanData, spanId);
    } catch (err) {
      this.api.logger.error(`[CozeloopTrace] Failed to start span: ${err}`);
    }
  }

  private doStartSpan(spanData: SpanData, spanId: string): void {
    if (!this.tracer) return;

    const spanKind = this.getSpanKind(spanData.type);
    const isRoot = !spanData.parentSpanId;
    const isAgent = spanData.type === "agent";

    // Resolve parent context:
    // - Root spans: no parent, use active context.
    // - Agent/child spans: look up traceContexts by parentSpanId (which is
    //   always the rootSpanId set by index.ts createSpan / ensureRootSpan).
    const traceCtx = spanData.parentSpanId
      ? this.traceContexts.get(spanData.parentSpanId)
      : undefined;

    if (!isRoot && !traceCtx && this.config.debug) {
      const keys = Array.from(this.traceContexts.keys());
      this.api.logger.info(
        `[CozeloopTrace] doStartSpan() cannot find parent context: ` +
        `parentSpanId=${spanData.parentSpanId}, spanName=${spanData.name}, type=${spanData.type}, ` +
        `traceContextKeys=[${keys.join(",")}]`
      );
    }

    let parentContext: Context;
    if (isRoot) {
      parentContext = context.active();
    } else if (isAgent) {
      parentContext = traceCtx?.rootContext || context.active();
    } else {
      parentContext = traceCtx?.agentContext || traceCtx?.rootContext || context.active();
    }

    const runtimeTag: Record<string, string> = {
      language: "nodejs",
      library: "openclaw",
    };
    if (process.env.COZELOOP_SCENE) {
      runtimeTag.scene = process.env.COZELOOP_SCENE;
    }
    const systemTagRuntime = JSON.stringify(runtimeTag);

    const span = this.tracer.startSpan(
      spanData.name,
      {
        kind: spanKind,
        startTime: spanData.startTime,
        attributes: {
          "cozeloop.span_type": spanData.type,
          "cozeloop.system_tag_runtime": systemTagRuntime,
          ...this.flattenAttributes(spanData.attributes),
        },
      },
      parentContext
    );

    if (isRoot) {
      const rootContext = trace.setSpan(context.active(), span);
      this.traceContexts.set(spanId, { rootSpan: span, rootContext });

      if (this.config.debug) {
        const sc = span.spanContext();
        this.api.logger.info(`[CozeloopTrace] Created ROOT span: name=${spanData.name}, traceId=${sc.traceId}, spanId=${sc.spanId}`);
      }
    }

    if (isAgent && traceCtx) {
      traceCtx.agentSpan = span;
      traceCtx.agentContext = trace.setSpan(traceCtx.rootContext, span);

      if (this.config.debug) {
        const sc = span.spanContext();
        this.api.logger.info(`[CozeloopTrace] Created AGENT span: name=${spanData.name}, traceId=${sc.traceId}, spanId=${sc.spanId}`);
      }
    }

    this.setSpanInputOutput(span, spanData);
    this.openSpans.set(spanId, span);

    if (this.config.debug && !isRoot && !isAgent) {
      const spanContext = span.spanContext();
      this.api.logger.info(
        `[CozeloopTrace] Started span: name=${spanData.name}, type=${spanData.type}, ` +
        `traceId=${spanContext.traceId}, spanId=${spanContext.spanId}`
      );
    }
  }

  endSpanById(spanId: string, endTime?: number, additionalAttrs?: Record<string, string | number | boolean>, output?: unknown, input?: unknown): void {
    const span = this.openSpans.get(spanId);
    if (!span) {
      if (this.config.debug) {
        this.api.logger.info(`[CozeloopTrace] Span not found for ending: spanId=${spanId}`);
      }
      return;
    }

    if (additionalAttrs) {
      for (const [key, value] of Object.entries(additionalAttrs)) {
        if (value !== undefined && value !== null) {
          span.setAttribute(key, value);
        }
      }
    }

    if (input !== undefined) {
      const inputStr = typeof input === "string" ? input : JSON.stringify(input);
      span.setAttribute("cozeloop.input", inputStr.substring(0, 3200000));
    }

    if (output !== undefined) {
      const outputStr = typeof output === "string" ? output : JSON.stringify(output);
      span.setAttribute("cozeloop.output", outputStr.substring(0, 3200000));
    }

    span.setStatus({ code: SpanStatusCode.OK });
    span.end(endTime || Date.now());
    this.openSpans.delete(spanId);

    if (this.config.debug) {
      const sc = span.spanContext();
      this.api.logger.info(`[CozeloopTrace] Ended span: spanId=${spanId}, traceId=${sc.traceId}`);
    }
  }

  async export(spanData: SpanData): Promise<void> {
    try {
    await this.ensureInitialized();
    if (!this.tracer) return;

    const spanKind = this.getSpanKind(spanData.type);
    const isRoot = !spanData.parentSpanId;
    const isAgent = spanData.type === "agent";

    const traceCtx = spanData.parentSpanId
      ? this.traceContexts.get(spanData.parentSpanId)
      : undefined;

    if (!isRoot && !traceCtx) {
      // Only warn for span types that are expected to be inside a trace
      // (agent, model, tool). message/session/gateway spans may fire before
      // the root span is created and that is normal.
      const criticalTypes = new Set(["agent", "model", "tool"]);
      if (criticalTypes.has(spanData.type) && this.config.debug) {
        const keys = Array.from(this.traceContexts.keys());
        this.api.logger.info(
          `[CozeloopTrace] export() cannot find parent context: ` +
          `parentSpanId=${spanData.parentSpanId}, spanName=${spanData.name}, type=${spanData.type}, ` +
          `traceContextKeys=[${keys.join(",")}]`
        );
      }
    }

    let parentContext: Context;
    if (isRoot) {
      parentContext = context.active();
    } else if (isAgent) {
      parentContext = traceCtx?.rootContext || context.active();
    } else {
      parentContext = traceCtx?.agentContext || traceCtx?.rootContext || context.active();
    }

    const runtimeTag: Record<string, string> = {
      language: "nodejs",
      library: "openclaw",
    };
    if (process.env.COZELOOP_SCENE) {
      runtimeTag.scene = process.env.COZELOOP_SCENE;
    }
    const systemTagRuntime = JSON.stringify(runtimeTag);

    const span = this.tracer.startSpan(
      spanData.name,
      {
        kind: spanKind,
        startTime: spanData.startTime,
        attributes: {
          "cozeloop.span_type": spanData.type,
          "cozeloop.system_tag_runtime": systemTagRuntime,
          ...this.flattenAttributes(spanData.attributes),
        },
      },
      parentContext
    );

    if (isRoot) {
      const rootContext = trace.setSpan(context.active(), span);
      const spanId = spanData.spanId || "export-root";
      this.traceContexts.set(spanId, { rootSpan: span, rootContext });

      if (this.config.debug) {
        const sc = span.spanContext();
        this.api.logger.info(`[CozeloopTrace] Created ROOT span: name=${spanData.name}, traceId=${sc.traceId}, spanId=${sc.spanId}`);
      }
    }

    this.setSpanInputOutput(span, spanData);

    const hasError = spanData.attributes["error"] === true || spanData.attributes["tool.error"] === true;
    if (hasError) {
      span.setStatus({ code: SpanStatusCode.ERROR });
    } else {
      span.setStatus({ code: SpanStatusCode.OK });
    }

    span.end(spanData.endTime || Date.now());

    if (this.config.debug) {
      const spanContext = span.spanContext();
      this.api.logger.info(
        `[CozeloopTrace] Created span: name=${spanData.name}, type=${spanData.type}, ` +
        `traceId=${spanContext.traceId}, spanId=${spanContext.spanId}, isRoot=${isRoot}`
      );
    }
    } catch (err) {
      this.api.logger.error(`[CozeloopTrace] Failed to export span: ${err}`);
    }
  }

  private setSpanInputOutput(span: ApiSpan, spanData: SpanData): void {
    if (spanData.input !== undefined) {
      const inputStr = typeof spanData.input === "string"
        ? spanData.input
        : JSON.stringify(spanData.input);
      span.setAttribute("cozeloop.input", inputStr.substring(0, 3200000));
    }

    if (spanData.output !== undefined) {
      const outputStr = typeof spanData.output === "string"
        ? spanData.output
        : JSON.stringify(spanData.output);
      span.setAttribute("cozeloop.output", outputStr.substring(0, 3200000));
    }
  }

  hasTraceContext(rootSpanId: string): boolean {
    return this.traceContexts.has(rootSpanId);
  }

  endTrace(rootSpanId?: string): void {
    if (rootSpanId) {
      this.traceContexts.delete(rootSpanId);
    } else {
      this.traceContexts.clear();
      this.openSpans.clear();
    }
    if (this.config.debug) {
      this.api.logger.info(`[CozeloopTrace] Trace ended, context cleared${rootSpanId ? ` for rootSpanId=${rootSpanId}` : ' (all)'}`);
    }
  }

  private getSpanKind(type: string): SpanKind {
    switch (type) {
      case "entry":
      case "gateway":
        return SpanKind.SERVER;
      case "model":
        return SpanKind.CLIENT;
      case "tool":
        return SpanKind.CLIENT;
      default:
        return SpanKind.INTERNAL;
    }
  }

  private flattenAttributes(attrs: Record<string, string | number | boolean>): Record<string, string | number | boolean> {
    const result: Record<string, string | number | boolean> = {};
    for (const [key, value] of Object.entries(attrs)) {
      if (value !== undefined && value !== null) {
        result[key] = value;
      }
    }
    return result;
  }

  async flush(): Promise<void> {
    if (this.provider) {
      await this.provider.forceFlush();
    }
  }

  async dispose(): Promise<void> {
    if (this.provider) {
      await this.provider.shutdown();
    }
  }
}
