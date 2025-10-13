# How to Run

# 1. Open project
Open this project as root directory.

# 2. Set global environment variable
- OPENAI_MODEL_NAME=***
- OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=https://api.coze.cn/v1/loop/opentelemetry/v1/traces
- OTEL_EXPORTER_OTLP_HEADERS=cozeloop-workspace-id=***,Authorization=Bearer ***
- COZELOOP_API_TOKEN=Bearer ***
- COZELOOP_WORKSPACE_ID=***


OPENAI_MODEL_NAME is your model name, ark model by default, get ark api-key and model from https://www.volcengine.com/docs/82379/1361424

COZELOOP_API_TOKEN is pat token or sat token, which has trace upload permission for this spaceID, reference doc: https://loop.coze.cn/open/docs/cozeloop/authentication-for-sdk

COZELOOP_WORKSPACE_ID is spaceID in cozeloop, from https://loop.coze.cn/

# 3. Set application.yaml
spring.ai.openai.api-key=***

api-key is ark model key by default, get ark api-key from https://www.volcengine.com/docs/82379/1361424
