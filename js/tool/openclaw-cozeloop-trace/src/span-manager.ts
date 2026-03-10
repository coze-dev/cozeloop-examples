import type { SpanData, SpanType } from "./types.js";

function generateId(length = 16): string {
  const chars = "0123456789abcdef";
  let result = "";
  for (let i = 0; i < length; i++) {
    result += chars[Math.floor(Math.random() * chars.length)];
  }
  return result;
}

export class SpanManager {
  private activeSpans: Map<string, SpanData> = new Map();
  private sessionTraceMap: Map<string, string> = new Map();
  private turnSpanMap: Map<string, string> = new Map();

  generateTraceId(): string {
    return generateId(32);
  }

  generateSpanId(): string {
    return generateId(16);
  }

  getOrCreateTraceId(sessionId: string): string {
    let traceId = this.sessionTraceMap.get(sessionId);
    if (!traceId) {
      traceId = this.generateTraceId();
      this.sessionTraceMap.set(sessionId, traceId);
    }
    return traceId;
  }

  startSpan(
    sessionId: string,
    name: string,
    type: SpanType,
    attributes: Record<string, string | number | boolean> = {},
    input?: unknown,
    parentSpanId?: string
  ): SpanData {
    const traceId = this.getOrCreateTraceId(sessionId);
    const spanId = this.generateSpanId();
    
    const span: SpanData = {
      name,
      type,
      startTime: Date.now(),
      attributes: {
        ...attributes,
        "session.id": sessionId,
      },
      input,
      parentSpanId,
      traceId,
      spanId,
    };
    
    this.activeSpans.set(spanId, span);
    return span;
  }

  endSpan(spanId: string, output?: unknown, additionalAttributes?: Record<string, string | number | boolean>): SpanData | undefined {
    const span = this.activeSpans.get(spanId);
    if (!span) return undefined;
    
    span.endTime = Date.now();
    span.output = output;
    if (additionalAttributes) {
      Object.assign(span.attributes, additionalAttributes);
    }
    
    this.activeSpans.delete(spanId);
    return span;
  }

  getSpan(spanId: string): SpanData | undefined {
    return this.activeSpans.get(spanId);
  }

  setTurnSpan(turnId: string, spanId: string): void {
    this.turnSpanMap.set(turnId, spanId);
  }

  getTurnSpanId(turnId: string): string | undefined {
    return this.turnSpanMap.get(turnId);
  }

  clearSession(sessionId: string): void {
    this.sessionTraceMap.delete(sessionId);
    for (const [turnId, spanId] of this.turnSpanMap.entries()) {
      const span = this.activeSpans.get(spanId);
      if (span && span.attributes["session.id"] === sessionId) {
        this.turnSpanMap.delete(turnId);
        this.activeSpans.delete(spanId);
      }
    }
  }
}
