// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

package main

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"time"

	"github.com/coze-dev/coze-go"
	"github.com/coze-dev/cozeloop-go"
)

type newTransport struct {
	TraceContextFunc func(ctx context.Context) map[string]string
}

func (n *newTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	if n.TraceContextFunc != nil && len(n.TraceContextFunc(req.Context())) > 0 {
		for key, value := range n.TraceContextFunc(req.Context()) {
			req.Header.Set(key, value)
		}
	}
	return http.DefaultTransport.RoundTrip(req)
}

var httpCli *http.Client
var cozeloopClient cozeloop.Client

func init() {
	var err error
	// init cozeloop client
	// global env COZELOOP_WORKSPACE_ID=your workspace id
	// global env COZELOOP_API_TOKEN=your token
	cozeloopClient, err = cozeloop.NewClient()
	if err != nil {
		panic(err)
	}

	httpCli = &http.Client{Timeout: time.Second * 20}
	httpCli.Transport = &newTransport{
		TraceContextFunc: func(ctx context.Context) map[string]string {
			header, err := cozeloop.GetSpanFromContext(ctx).ToHeader()
			if err != nil {
				fmt.Printf("cozeloop.GetSpanFromContext ToHeader err: %v", err)
				return nil
			}
			return header
		},
	}
}

func main() {
	// Should use the ctx passed down from upstream (for automatic concatenation of traces), and here for simplicity, we will directly use Background
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()

	// Set the following environment variables first.
	// COZELOOP_WORKSPACE_ID=your workspace id, for cozeloop client init by default
	// COZELOOP_API_TOKEN=your token, for cozeloop client init by default
	userID := os.Getenv("USER_ID")
	token := os.Getenv("COZELOOP_API_TOKEN")
	botID := os.Getenv("PUBLISHED_BOT_ID")
	authCli := coze.NewTokenAuth(token)
	cozeApiBase := "https://api.coze.cn" // os.Getenv("COZE_API_BASE")

	// This is a span of cozeloop sdk.
	ctx, span := cozeloopClient.StartSpan(ctx, "my_span", "MyType")

	// Init the Coze client through the access_token.
	cozeCli := coze.NewCozeAPI(authCli,
		coze.WithBaseURL(cozeApiBase),
		coze.WithHttpClient(httpCli),
	)

	// Step one, create chats
	req := &coze.CreateChatsReq{
		BotID:  botID,
		UserID: userID,
		Messages: []*coze.Message{
			coze.BuildUserQuestionText("What can you do?", nil),
		},
	}

	resp, err := cozeCli.Chat.Stream(ctx, req) // Ctx must be transmitted throughout the entire chain, otherwise trace cannot be concatenated
	if err != nil {
		fmt.Printf("Error starting chats: %v\n", err)
		return
	}

	defer resp.Close()
	for {
		event, err := resp.Recv()
		if errors.Is(err, io.EOF) {
			fmt.Println("Stream finished")
			break
		}
		if err != nil {
			fmt.Println(err)
			break
		}
		if event.Event == coze.ChatEventConversationMessageDelta {
			fmt.Print(event.Message.Content)
		} else if event.Event == coze.ChatEventConversationChatCompleted {
			fmt.Printf("Token usage:%d\n", event.Chat.Usage.TokenCount)
		} else {
			fmt.Printf("\n")
		}
	}

	fmt.Printf("done, log:%s\n", resp.Response().LogID())

	span.Finish(ctx) // span finish
	cozeloop.Flush(ctx)
}
