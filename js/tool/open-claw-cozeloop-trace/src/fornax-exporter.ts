import type { SpanData, FornaxTraceConfig, OpenClawPluginApi } from "./types.js";
import { trace, context, SpanKind, SpanStatusCode, Context, Span as ApiSpan } from "@opentelemetry/api";
import { BasicTracerProvider, BatchSpanProcessor, Span } from "@opentelemetry/sdk-trace-base";
import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-proto";
import { Resource } from "@opentelemetry/resources";
import { ATTR_SERVICE_NAME, ATTR_SERVICE_INSTANCE_ID } from "@opentelemetry/semantic-conventions";
import { hostname } from "os";
import { basename } from "path";

interface AuthResult {
  authorization: string;
  workspaceId: string;
}

async function getAuthFromFornaxSDK(config: FornaxTraceConfig, api: OpenClawPluginApi): Promise<AuthResult | null> {
  if (!config.ak || !config.sk) {
    return null;
  }
  
  try {
    api.logger.info(`[FornaxTrace] Importing @next-ai/fornax-api...`);
    const { FornaxHttp } = await import("@next-ai/fornax-api");
    api.logger.info(`[FornaxTrace] Creating FornaxHttp instance with region=${config.region || "CN"}...`);
    const http = new FornaxHttp({
      ak: config.ak,
      sk: config.sk,
      region: config.region || "CN",
    });
    api.logger.info(`[FornaxTrace] Calling http.getAccessToken()...`);
    const token = await http.getAccessToken();
    api.logger.info(`[FornaxTrace] Got token (length=${token.length}), now calling http.getSpaceId()...`);
    const spaceId = await http.getSpaceId();
    api.logger.info(`[FornaxTrace] Got spaceId=${spaceId}`);
    return { authorization: token, workspaceId: spaceId };
  } catch (error) {
    api.logger.error(`[FornaxTrace] Failed to get auth from Fornax SDK: ${error}`);
    throw error;
  }
}

export class FornaxExporter {
  private config: FornaxTraceConfig;
  private api: OpenClawPluginApi;
  private provider: BasicTracerProvider | null = null;
  private tracer: ReturnType<typeof trace.getTracer> | null = null;
  private initialized: boolean = false;
  private initPromise: Promise<void> | null = null;
  
  private currentRootSpan: ApiSpan | null = null;
  private currentRootContext: Context | null = null;
  private currentAgentSpan: ApiSpan | null = null;
  private currentAgentContext: Context | null = null;
  private openSpans: Map<string, ApiSpan> = new Map();

  private cachedToken: string | null = null;
  private cachedWorkspaceId: string | null = null;
  private tokenExpireTime: number = 0;

  constructor(api: OpenClawPluginApi, config: FornaxTraceConfig) {
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
    this.api.logger.info(`[FornaxTrace] Initializing exporter...`);
    
    const instanceName = this.config.serviceName || basename(process.cwd()) || "openclaw-agent";
    const instanceId = `${instanceName}@${hostname()}:${process.pid}`;

    const resource = new Resource({
      [ATTR_SERVICE_NAME]: this.config.serviceName,
      [ATTR_SERVICE_INSTANCE_ID]: instanceId,
      "host.name": hostname(),
    });

    await this.refreshAuth();
    
    this.api.logger.info(`[FornaxTrace] Auth refreshed, workspaceId=${this.cachedWorkspaceId}, tokenLength=${this.cachedToken?.length}`);

    const exporter = new OTLPTraceExporter({
      url: `${this.config.endpoint}/v1/traces`,
      headers: {
        "Authorization": this.cachedToken!,
        "cozeloop-workspace-id": this.cachedWorkspaceId!,
      },
    });

    this.provider = new BasicTracerProvider({ resource });
    this.provider.addSpanProcessor(new BatchSpanProcessor(exporter, {
      maxQueueSize: 100,
      maxExportBatchSize: this.config.batchSize || 10,
      scheduledDelayMillis: this.config.batchInterval || 5000,
    }));
    this.provider.register();

    this.tracer = trace.getTracer("openclaw-fornax-trace", "0.1.0");
    this.initialized = true;

    this.api.logger.info(`[FornaxTrace] Exporter initialized with ${this.config.ak ? 'AK/SK' : 'Authorization'}, workspaceId=${this.cachedWorkspaceId}`);
  }

  private async refreshAuth(): Promise<void> {
    this.api.logger.info(`[FornaxTrace] refreshAuth called, hasAK=${!!this.config.ak}, hasSK=${!!this.config.sk}`);
    
    const now = Date.now();
    if (this.cachedToken && this.cachedWorkspaceId && this.tokenExpireTime > now + 60000) {
      this.api.logger.info(`[FornaxTrace] Using cached token`);
      return;
    }

    this.api.logger.info(`[FornaxTrace] Calling getAuthFromFornaxSDK...`);
    const authResult = await getAuthFromFornaxSDK(this.config, this.api);
    this.api.logger.info(`[FornaxTrace] getAuthFromFornaxSDK returned: ${authResult ? 'success' : 'null'}`);
    
    if (authResult) {
      this.cachedToken = authResult.authorization;
      this.cachedWorkspaceId = authResult.workspaceId;
      this.tokenExpireTime = now + 2.5 * 60 * 60 * 1000;
    } else if (this.config.authorization && this.config.workspaceId) {
      this.api.logger.info(`[FornaxTrace] Using static authorization`);
      this.cachedToken = this.config.authorization;
      this.cachedWorkspaceId = this.config.workspaceId;
      this.tokenExpireTime = Number.MAX_SAFE_INTEGER;
    } else {
      throw new Error("[FornaxTrace] Either 'ak'+'sk' or 'authorization'+'workspaceId' must be provided");
    }
  }

  startSpan(spanData: SpanData, spanId: string): void {
    this.ensureInitialized().then(() => {
      this.doStartSpan(spanData, spanId);
    }).catch(err => {
      this.api.logger.error(`[FornaxTrace] Failed to start span: ${err}`);
    });
  }

  private doStartSpan(spanData: SpanData, spanId: string): void {
    if (!this.tracer) return;
    
    const spanKind = this.getSpanKind(spanData.type);
    const isRoot = !spanData.parentSpanId;
    const isAgent = spanData.type === "agent";
    
    let parentContext: Context;
    
    if (isRoot) {
      this.currentRootSpan = null;
      this.currentRootContext = null;
      this.currentAgentSpan = null;
      this.currentAgentContext = null;
      parentContext = context.active();
    } else if (isAgent) {
      parentContext = this.currentRootContext || context.active();
    } else {
      parentContext = this.currentAgentContext || this.currentRootContext || context.active();
    }

    const systemTagRuntime = JSON.stringify({
      language: "nodejs",
      library: "openclaw",
    });

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
      this.currentRootSpan = span;
      this.currentRootContext = trace.setSpan(context.active(), span);
      
      if (this.config.debug) {
        const sc = span.spanContext();
        this.api.logger.info(`[FornaxTrace] Created ROOT span: name=${spanData.name}, traceId=${sc.traceId}, spanId=${sc.spanId}`);
      }
    }
    
    if (isAgent) {
      this.currentAgentSpan = span;
      this.currentAgentContext = trace.setSpan(this.currentRootContext || context.active(), span);
      
      if (this.config.debug) {
        const sc = span.spanContext();
        this.api.logger.info(`[FornaxTrace] Created AGENT span: name=${spanData.name}, traceId=${sc.traceId}, spanId=${sc.spanId}`);
      }
    }

    this.setSpanInputOutput(span, spanData);
    this.openSpans.set(spanId, span);

    if (this.config.debug && !isRoot && !isAgent) {
      const spanContext = span.spanContext();
      this.api.logger.info(
        `[FornaxTrace] Started span: name=${spanData.name}, type=${spanData.type}, ` +
        `traceId=${spanContext.traceId}, spanId=${spanContext.spanId}`
      );
    }
  }

  endSpanById(spanId: string, endTime?: number, additionalAttrs?: Record<string, string | number | boolean>, output?: unknown, input?: unknown): void {
    const span = this.openSpans.get(spanId);
    if (!span) {
      if (this.config.debug) {
        this.api.logger.info(`[FornaxTrace] Span not found for ending: spanId=${spanId}`);
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
      this.api.logger.info(`[FornaxTrace] Ended span: spanId=${spanId}, traceId=${sc.traceId}`);
    }
  }

  async export(spanData: SpanData): Promise<void> {
    await this.ensureInitialized();
    if (!this.tracer) return;

    const spanKind = this.getSpanKind(spanData.type);
    const isRoot = !spanData.parentSpanId;
    const isAgent = spanData.type === "agent";
    
    let parentContext: Context;
    
    if (isRoot) {
      this.currentRootSpan = null;
      this.currentRootContext = null;
      parentContext = context.active();
    } else if (isAgent) {
      parentContext = this.currentRootContext || context.active();
    } else {
      parentContext = this.currentAgentContext || this.currentRootContext || context.active();
    }

    const systemTagRuntime = JSON.stringify({
      language: "nodejs",
      library: "openclaw",
    });

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
      this.currentRootSpan = span;
      this.currentRootContext = trace.setSpan(context.active(), span);
      
      if (this.config.debug) {
        const sc = span.spanContext();
        this.api.logger.info(`[FornaxTrace] Created ROOT span: name=${spanData.name}, traceId=${sc.traceId}, spanId=${sc.spanId}`);
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
        `[FornaxTrace] Created span: name=${spanData.name}, type=${spanData.type}, ` +
        `traceId=${spanContext.traceId}, spanId=${spanContext.spanId}, isRoot=${isRoot}`
      );
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

  endTrace(): void {
    this.currentRootSpan = null;
    this.currentRootContext = null;
    this.currentAgentSpan = null;
    this.currentAgentContext = null;
    this.openSpans.clear();
    if (this.config.debug) {
      this.api.logger.info(`[FornaxTrace] Trace ended, context cleared`);
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
