# How to Run

# Set global environment variable
- ANTHROPIC_API_KEY=***
- OTEL_EXPORTER_OTLP_ENDPOINT=https://api.coze.cn/v1/loop/opentelemetry
- OTEL_EXPORTER_OTLP_HEADERS=cozeloop-workspace-id=***,Authorization=Bearer ***
- LANGSMITH_OTEL_ENABLED=true
- LANGSMITH_OTEL_ONLY=true
- LANGSMITH_TRACING=true

cozeloop-workspace-id is spaceID in cozeloop, from https://loop.coze.cn/

Authorization is pat token or sat token, which has trace upload permission for this spaceID, reference doc: https://loop.coze.cn/open/docs/cozeloop/authentication-for-sdk
