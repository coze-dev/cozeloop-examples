# How to Run

# Set global environment variable
OPENAI_BASE_URL=***
OPENAI_API_KEY=***
OPENAI_MODEL_NAME=***
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=https://api.coze.cn/v1/loop/opentelemetry/v1/traces
OTEL_EXPORTER_OTLP_HEADERS=cozeloop-workspace-id=***,Authorization=Bearer ***

cozeloop-workspace-id is spaceID in cozeloop, from https://loop.coze.cn/
Authorization is pat token or sat token, which has trace upload permission for this spaceID, reference doc: https://loop.coze.cn/open/docs/cozeloop/authentication-for-sdk