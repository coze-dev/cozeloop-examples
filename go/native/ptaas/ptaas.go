// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

package main

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"strings"

	"github.com/coze-dev/cozeloop-go"
	"github.com/coze-dev/cozeloop-go/entity"
)

// Set the following environment variables first.
// COZELOOP_WORKSPACE_ID=your workspace id
// COZELOOP_API_TOKEN=your pat or sat token
var (
	cozeloopPromptKey = os.Getenv("COZELOOP_PROMPT_KEY") // use CozeLoop_Oncall_Master by default, you can find it in Demo Workspace
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

func main() {
	// 1.Create a prompt on the platform
	// The Prompt of demo is CozeLoop_Oncall_Master, you can copy it from 'Demo Workspace',
	// add the following messages to the template, submit a version.
	ctx := context.Background()

	// Set the following environment variables first.
	// COZELOOP_WORKSPACE_ID=your workspace id
	// COZELOOP_API_TOKEN=your token
	// 2.New loop client
	client, err := cozeloop.NewClient()
	if err != nil {
		panic(err)
	}
	defer client.Close(ctx)

	// 3. Execute prompt
	key := "CozeLoop_Oncall_Master"
	if cozeloopPromptKey != "" {
		key = cozeloopPromptKey
	}
	executeRequest := &entity.ExecuteParam{
		PromptKey: key,
		Version:   "0.0.1",
		VariableVals: map[string]any{
			"name":     "Windows system question tool",
			"platform": "windows system",
		},
		// You can also append messages to the prompt.
		Messages: []*entity.Message{
			{
				Role:    entity.RoleUser,
				Content: Ptr("How to shut down Windows 11 system？"),
			},
		},
	}
	// 3.1 Non stream execute
	result, err := nonStreamExecutePrompt(ctx, client, executeRequest)
	if err != nil {
		panic(err)
	}
	// 6. tool call
	for _, toolCall := range result.Message.ToolCalls {
		if toolCall.FunctionCall.Name == "acquire_knowledge" {
			m := make(map[string]any)
			_ = json.Unmarshal([]byte(*toolCall.FunctionCall.Arguments), &m)
			query := m["query"].(string)
			toolCallRes := acquireKnowledge(ctx, query)
			fmt.Printf("Final Result: %v\n", toolCallRes)
		}
	}
}

func nonStreamExecutePrompt(ctx context.Context, client cozeloop.Client, executeRequest *entity.ExecuteParam) (*entity.ExecuteResult, error) {
	result, err := client.Execute(ctx, executeRequest)
	if err != nil {
		return nil, err
	}
	printExecuteResult(result)

	return &result, nil
}

func printExecuteResult(result entity.ExecuteResult) {
	if result.Message != nil {
		fmt.Printf("Message: %s\n", ToJSON(result.Message))
	}
	if PtrValue(result.FinishReason) != "" {
		fmt.Printf("FinishReason: %s\n", PtrValue(result.FinishReason))
	}
	if result.Usage != nil {
		fmt.Printf("Usage: %s\n", ToJSON(result.Usage))
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

func ToJSON(param interface{}) string {
	if param == nil {
		return ""
	}
	if paramStr, ok := param.(string); ok {
		return paramStr
	}
	byteRes, err := json.Marshal(param)
	if err != nil {
		return ""
	}
	return string(byteRes)
}
