# How to Run

# Set global variable in litellm_config.yaml
demo:
model_list:
  - model_name: my-gpt-model
    litellm_params:
      model: azure/gpt-5-2025-08-07
      api_base: <azure-api-endpoint>
      api_key: <azure-api-key>

model_name is user-facing model alias, can use any name you want

model is litellm model name, use model provider as prefix, like azure/gpt-5-2025-08-07

api_base is model url

api_key is model key

# Set global environment variable
- export OTEL_EXPORTER="otlp_http"
- export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT="https://api.coze.cn/v1/loop/opentelemetry/v1/traces"
- export OTEL_EXPORTER_OTLP_TRACES_HEADERS="cozeloop-workspace-id={COZELOOP_WORKSPACE_ID},Authorization=Bearer {COZELOOP_API_TOKEN}"

COZELOOP_WORKSPACE_ID is spaceID in cozeloop, from https://loop.coze.cn/

COZELOOP_API_TOKEN is pat token or sat token, which has trace upload permission for this spaceID, reference doc: https://loop.coze.cn/open/docs/cozeloop/authentication-for-sdk

# Run proxy by cmd(The environment of running proxy must be same with the environment of setting global environment variable)
litellm --config litellm_config.yaml