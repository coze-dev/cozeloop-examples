package org.example;

import com.coze.loop.client.CozeLoopClient;
import com.coze.loop.entity.ExecuteParam;
import com.coze.loop.entity.ExecuteResult;
import com.coze.loop.spec.tracespec.ModelChoice;
import com.coze.loop.spec.tracespec.ModelInput;
import com.coze.loop.spec.tracespec.ModelMessage;
import com.coze.loop.spec.tracespec.ModelOutput;
import com.coze.loop.spring.annotation.CozeTrace;
import com.coze.loop.trace.CozeLoopSpan;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.Map;

@Service
public class ChatService {

    private static final Logger log = LoggerFactory.getLogger(ChatService.class);

    @Autowired
    private CozeLoopClient cozeLoopClient;

    /**
     * 合合示例：在一个接口中同时展示：
     * 1. 使用 @CozeTrace 自动追踪
     * 2. 手动创建子 Span 并模拟 LLM 调用（参考 non_spring_boot 示例）
     * 3. 执行 CozeLoop Prompt
     */
    @CozeTrace(
            name = "combined_chat_process",
            spanType = "business",
            captureArgs = true,
            captureReturn=true
    )
    public String chat(String promptKey, String query) {
        log.info("Starting combined process for query: {}", query);

        // 1. 模拟 LLM 调用追踪 (参考 non_spring_boot 中的 callLLM 逻辑)
        simulateLLMCall(query);
        // 2. 执行 CozeLoop Prompt
        return executeCozePrompt(promptKey, query);
    }

    private void simulateLLMCall(String query) {
        // 创建 LLM 调用的 span
        try (CozeLoopSpan span = cozeLoopClient.startSpan("llmCall", "model")) {
            long startTime = System.currentTimeMillis() * 1000;

            // set baggage
            span.setBaggage("llm_id", "01");

            System.out.println("llmCall TraceID: " + span.getTraceID());
            System.out.println("llmCall SpanID: " + span.getSpanID());
            System.out.println("llmCall Baggage: " + span.getBaggage());

            // 模拟 LLM 处理
            String modelName = "gpt-4o-2024-05-13";
            ModelInput input = new ModelInput();
            input.setMessages(Collections.singletonList(new ModelMessage("user", "上海天气怎么样？")));

            // 模拟 API 调用（实际使用时替换为真实的 LLM API 调用）
            // 这里只是模拟
            try {
                Thread.sleep(1000); // 模拟网络延迟
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                return;
            }

            // 模拟响应
            ModelOutput output = new ModelOutput();
            output.setChoices(
                    Collections.singletonList(
                            new ModelChoice(new ModelMessage("assistant", "上海天气晴朗，气温25摄氏度。"), "stop", 0L)));
            int respPromptTokens = 11;
            int respCompletionTokens = 52;

            // 设置 span 的输入
            span.setInput(input);

            // 设置 span 的输出
            span.setOutput(output);

            // 设置 model provider，例如：openai, anthropic 等
            span.setModelProvider("openai");

            // 设置 model name，例如：gpt-4-1106-preview 等
            span.setModelName(modelName);

            // 设置模型参数
            span.setModelTopP(0.6);
            span.setModelTopK(2);
            span.setModelMaxTokens(2096);
            span.setModelTemperature(0.8);
            span.setModelFrequencyPenalty(0.7);
            span.setModelPresencePenalty(0.8);
            span.setModelStopSequences(Arrays.asList("finish", "tool_calls"));

            // 设置输入 tokens 数量
            // 当设置了 input_tokens 和 output_tokens 后，会自动计算 total_tokens
            span.setInputTokens(respPromptTokens);

            // 设置输出 tokens 数量
            span.setOutputTokens(respCompletionTokens);

            // 设置首次响应时间（微秒）
            // 当设置了 start_time_first_resp 后，会根据 span 的 StartTime 计算
            // 一个名为 latency_first_resp 的标签，表示首次数据包的延迟
            long firstRespTime = startTime + 200000; // 假设用了200ms，转换为微秒
            span.setStartTimeFirstResp(firstRespTime);

            // set service name
            span.setServiceName("a.b.c");

            // set logID
            span.setLogID("log-123456");

            // set deployment env
            span.setDeploymentEnv("boe");

            // set code and error
            span.setStatusCode(112);
            span.setError(new RuntimeException("llmCall")); // when set error, if status_code is 0 or null, it'll be set -1 by default

            System.out.println("LLM 调用成功");
            System.out.println("  输入: " + input);
            System.out.println("  输出: " + output);
            System.out.println("  模型: " + modelName);
            System.out.println("  输入 tokens: " + respPromptTokens);
            System.out.println("  输出 tokens: " + respCompletionTokens);
        }
    }

    private String executeCozePrompt(String promptKey, String query) {
        if (promptKey == null || promptKey.isEmpty()) {
            return "No prompt key provided, skipped prompt execution.";
        }

        Map<String, Object> variables = new HashMap<>();
        variables.put("query", query);

        ExecuteParam param = ExecuteParam.builder()
                .promptKey(promptKey)
                .variableVals(variables)
                .build();

        log.info("Executing CozeLoop prompt with key: {}", promptKey);
        ExecuteResult result = cozeLoopClient.execute(param);
        return result.getMessage().getContent();
    }
}
