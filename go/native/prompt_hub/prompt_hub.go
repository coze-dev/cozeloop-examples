// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

package main

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"strings"

	"github.com/cloudwego/eino-ext/components/model/openai"
	"github.com/cloudwego/eino/components/model"
	"github.com/cloudwego/eino/schema"
	"github.com/coze-dev/cozeloop-go"
	"github.com/coze-dev/cozeloop-go/entity"
	"github.com/coze-dev/cozeloop-go/spec/tracespec"
	"github.com/getkin/kin-openapi/openapi3"
)

// Set the following environment variables first.
// COZELOOP_WORKSPACE_ID=your workspace id
// COZELOOP_API_TOKEN=your pat or sat token
var (
	baseURL           = os.Getenv("OPENAI_BASE_URL")     // use ark model url("https://ark.cn-beijing.volces.com/api/v3") by default, refer: https://www.volcengine.com/docs/82379/1361424
	apiKey            = os.Getenv("OPENAI_API_KEY")      // your ark api key
	modelName         = os.Getenv("OPENAI_MODEL_NAME")   // ark model name, like doubao-1-5-vision-pro-32k-250115
	cozeloopPromptKey = os.Getenv("COZELOOP_PROMPT_KEY") // use CozeLoop_Oncall_Master by default, you can find it in Demo Workspace
)

var (
	maxTokens   = 1024
	temperature = 1
)

func acquireKnowledge(ctx context.Context, query string) (res string) {
	ctx, span := cozeloop.StartSpan(ctx, "acquire_knowledge", "acquire_knowledge", nil)
	defer cozeloop.Flush(ctx)
	defer span.Finish(ctx)
	span.SetInput(ctx, query)
	if (strings.Contains(query, "Windows") || strings.Contains(query, "windows")) && strings.Contains(query, "shut down") {
		res = "Find the shutdown button in the Windows icon, and click to shut down"
		span.SetOutput(ctx, res)
		return
	}
	res = "No relevant information found"
	span.SetOutput(ctx, res)
	return
}

func createOpenAIChatModel(ctx context.Context) model.ToolCallingChatModel {
	modelBaseURL := "https://ark.cn-beijing.volces.com/api/v3"
	if baseURL != "" {
		modelBaseURL = baseURL
	}
	chatModel, err := openai.NewChatModel(ctx, &openai.ChatModelConfig{
		BaseURL:     modelBaseURL,
		Model:       modelName,
		APIKey:      apiKey,
		MaxTokens:   Ptr(maxTokens),
		Temperature: Ptr(float32(temperature)),
	})
	if err != nil {
		fmt.Printf("create openai chat model failed, err=%v", err)
	}

	cm, _ := chatModel.WithTools([]*schema.ToolInfo{
		{
			Name: "acquire_knowledge",
			Desc: "windows system question tool",
			ParamsOneOf: schema.NewParamsOneOfByOpenAPIV3(&openapi3.Schema{
				Type: openapi3.TypeObject,
				Properties: map[string]*openapi3.SchemaRef{
					"query": {
						Value: &openapi3.Schema{
							Type:        openapi3.TypeString,
							Description: "The query to knowledge.",
						},
					},
				},
			}),
		},
	})

	return cm
}

func main() {
	// 1.Create a prompt on the platform
	// The Prompt of demo is CozeLoop_Oncall_Master, you can copy it from 'Demo Workspace',
	// add the following messages to the template, submit a version.

	ctx := context.Background()

	// Set the following environment variables first.
	// COZELOOP_WORKSPACE_ID=your workspace id
	// COZELOOP_API_TOKEN=your token
	// 2.New loop client
	client, err := cozeloop.NewClient(
		// Set whether to report a trace span when get or format prompt.
		// Default value is false.
		cozeloop.WithPromptTrace(true))
	if err != nil {
		panic(err)
	}

	llmRunner := llmRunner{
		client: client,
		model:  createOpenAIChatModel(ctx),
	}

	query := "How to shut down Windows 11 system？"

	// 1. start root span
	ctx, span := llmRunner.client.StartSpan(ctx, "root_span", "main_span", nil)
	span.SetInput(ctx, query)

	// 3.Get the prompt
	key := "CozeLoop_Oncall_Master"
	if cozeloopPromptKey != "" {
		key = cozeloopPromptKey
	}
	prompt, err := llmRunner.client.GetPrompt(ctx, cozeloop.GetPromptParam{
		PromptKey: key,
		// If version is not specified, the latest version of the corresponding prompt will be obtained
		//Version: "0.0.1",
	})
	if err != nil {
		fmt.Printf("get prompt failed: %v\n", err)
		return
	}
	if prompt != nil {
		// Get messages of the prompt
		if prompt.PromptTemplate != nil {
			messages, err := json.Marshal(prompt.PromptTemplate.Messages)
			if err != nil {
				fmt.Printf("json marshal failed: %v\n", err)
				return
			}
			fmt.Printf("prompt messages=%s\n", string(messages))
		}
		// Get llm config of the prompt
		if prompt.LLMConfig != nil {
			llmConfig, err := json.Marshal(prompt.LLMConfig)
			if err != nil {
				fmt.Printf("json marshal failed: %v\n", err)
			}
			fmt.Printf("prompt llm config=%s\n", llmConfig)
		}

		// 4.Format messages of the prompt
		messages, err := llmRunner.client.PromptFormat(ctx, prompt, map[string]any{
			"name":     "Windows system question tool",
			"platform": "windows system",
		})
		if err != nil {
			fmt.Printf("prompt format failed: %v\n", err)
			return
		}
		data, err := json.Marshal(messages)
		if err != nil {
			fmt.Printf("json marshal failed: %v\n", err)
			return
		}
		fmt.Printf("formatted messages=%s\n", string(data))

		messages = append(messages, &entity.Message{
			Role:    entity.RoleUser,
			Content: &query,
		})

		// 5. llm call
		generate, err := llmRunner.llmCall(ctx, messages)
		if err != nil {
			return
		}

		// 6. tool call
		for _, toolCall := range generate.ToolCalls {
			if toolCall.Function.Name == "acquire_knowledge" {
				m := make(map[string]any)
				_ = json.Unmarshal([]byte(toolCall.Function.Arguments), &m)
				query := m["query"].(string)
				toolCallRes := acquireKnowledge(ctx, query)
				span.SetOutput(ctx, toolCallRes)
				fmt.Printf("acquire knowledge, toolCallRes=%v\n", toolCallRes)
			}
		}
	}

	// 6. span finish
	span.Finish(ctx)

	// 7. (optional) flush or close
	// -- force flush, report all traces in the queue
	// Warning! In general, this method is not needed to be call, as spans will be automatically reported in batches.
	// Note that flush will block and wait for the report to complete, and it may cause frequent reporting,
	// affecting performance.
	llmRunner.client.Flush(ctx)
}

type llmRunner struct {
	client cozeloop.Client
	model  model.ToolCallingChatModel
}

func (r *llmRunner) llmCall(ctx context.Context, messages []*entity.Message) (generate *schema.Message, err error) {
	ctx, span := r.client.StartSpan(ctx, "llmCall", tracespec.VModelSpanType, nil)
	defer span.Finish(ctx)

	generate, err = r.model.Generate(ctx, convertMessagesEntity2Eino(messages))
	if err != nil {
		return nil, err
	}
	fmt.Printf("model generate=%v\n", generate)

	respPromptTokens := generate.ResponseMeta.Usage.PromptTokens
	respCompletionTokens := generate.ResponseMeta.Usage.CompletionTokens

	span.SetInput(ctx, convertModelInputEntity2TraceSpec(messages))
	span.SetOutput(ctx, convertModelOutputEino2TraceSpec(generate))
	span.SetModelProvider(ctx, "openai")
	span.SetInputTokens(ctx, respPromptTokens)
	span.SetOutputTokens(ctx, respCompletionTokens)
	span.SetModelName(ctx, os.Getenv("OPENAI_MODEL_NAME"))
	span.SetTags(ctx, map[string]interface{}{
		tracespec.CallOptions: tracespec.ModelCallOption{
			Temperature: float32(temperature),
			MaxTokens:   int64(maxTokens),
		},
	})

	return generate, nil
}

func convertMessagesEntity2Eino(messages []*entity.Message) []*schema.Message {
	result := make([]*schema.Message, 0, len(messages))
	for _, message := range messages {
		result = append(result, &schema.Message{
			Role:    schema.RoleType(message.Role),
			Content: *message.Content,
		})
	}
	return result
}

func convertModelInputEntity2TraceSpec(messages []*entity.Message) *tracespec.ModelInput {
	modelMessages := make([]*tracespec.ModelMessage, 0)
	for _, message := range messages {
		modelMessages = append(modelMessages, &tracespec.ModelMessage{
			Role:    string(message.Role),
			Content: PtrValue(message.Content),
		})
	}

	return &tracespec.ModelInput{
		Messages: modelMessages,
	}
}

func convertToolCallsEino2TraceSpec(toolCalls []schema.ToolCall) []*tracespec.ModelToolCall {
	result := make([]*tracespec.ModelToolCall, 0)
	for _, toolCall := range toolCalls {
		result = append(result, &tracespec.ModelToolCall{
			ID:   toolCall.ID,
			Type: string(toolCall.Type),
			Function: &tracespec.ModelToolCallFunction{
				Name:      toolCall.Function.Name,
				Arguments: toolCall.Function.Arguments,
			},
		})
	}
	return result
}

func convertModelOutputEino2TraceSpec(msg *schema.Message) *tracespec.ModelOutput {
	choice := &tracespec.ModelChoice{
		FinishReason: msg.ResponseMeta.FinishReason,
		Index:        0,
		Message: &tracespec.ModelMessage{
			Role:      string(msg.Role),
			Content:   msg.Content,
			ToolCalls: convertToolCallsEino2TraceSpec(msg.ToolCalls),
		},
	}

	return &tracespec.ModelOutput{
		Choices: []*tracespec.ModelChoice{choice},
	}
}

func PtrValue[T any](s *T) T {
	if s != nil {
		return *s
	}
	var empty T
	return empty
}

func Ptr[T any](s T) *T {
	return &s
}
