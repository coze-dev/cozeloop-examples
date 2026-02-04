package org.example;

import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.Map;

import com.coze.loop.client.CozeLoopClient;
import com.coze.loop.client.CozeLoopClientBuilder;
import com.coze.loop.entity.ExecuteParam;
import com.coze.loop.entity.ExecuteResult;
import com.coze.loop.internal.JsonUtils;
import com.coze.loop.spec.tracespec.ModelChoice;
import com.coze.loop.spec.tracespec.ModelInput;
import com.coze.loop.spec.tracespec.ModelMessage;
import com.coze.loop.spec.tracespec.ModelOutput;
import com.coze.loop.trace.CozeLoopSpan;

/**
 * CozeLoop Core 非 Spring Boot 环境使用示例
 *
 * <p>本示例展示了如何在原生 Java 应用中手动初始化 CozeLoopClient 并进行 Trace 上报和 Prompt 执行。
 *
 * <p>使用前请设置以下环境变量：
 * - COZELOOP_WORKSPACE_ID: 你的工作空间 ID
 * - COZELOOP_API_TOKEN: 你的访问令牌 (PAT)
 * - COZELOOP_PROMPT_KEY: 你的 Prompt Key (可选，用于测试 Prompt 执行)
 */
public class Main {
  private static final int ERROR_CODE_LLM_CALL = 600789111;

  public static void main(String[] args) {
    // 1. 从环境变量获取配置
    String workspaceId = System.getenv("COZELOOP_WORKSPACE_ID");
    String apiToken = System.getenv("COZELOOP_API_TOKEN");
    String promptKey = System.getenv("COZELOOP_PROMPT_KEY");

    if (workspaceId == null || apiToken == null) {
      System.err.println("错误：请设置环境变量 COZELOOP_WORKSPACE_ID 和 COZELOOP_API_TOKEN");
      System.out.println("示例：");
      System.out.println("  export COZELOOP_WORKSPACE_ID=your_workspace_id");
      System.out.println("  export COZELOOP_API_TOKEN=your_pat_token");
      return;
    }

    // 2. 初始化 CozeLoopClient
    // 在非 Spring Boot 环境中，我们需要手动通过 Builder 构建客户端
    try (CozeLoopClient client =
        new CozeLoopClientBuilder()
            .workspaceId(workspaceId)
            .tokenAuth(apiToken)
            .serviceName("non-spring-boot-example")
            .build()) {

      System.out.println("CozeLoopClient 初始化成功");

      // 3. 示例：手动 Trace 上报
      // 使用 try-with-resources 确保 span 正确关闭（关闭时会自动结束 span）
      try (CozeLoopSpan span = client.startSpan("main_process", "custom")) {
        span.setTag("user_id", "user_12345");
        span.setTag("env", "development");

        System.out.println("已开启 Span: main_process");

        // 模拟业务逻辑
        doBusinessLogic(client, span);

        // 4. 示例：Prompt 执行 (如果提供了 promptKey)
        if (promptKey != null && !promptKey.isEmpty()) {
          executePromptDemo(client, promptKey);
        } else {
          System.out.println("\n提示：设置环境变量 COZELOOP_PROMPT_KEY 以测试 Prompt 执行功能");
        }
      }

      // 5. 强制刷新 Trace 数据 (可选)
      // 在短时间运行的程序（如命令行工具）末尾，建议调用 flush 确保所有 span 都已上报
      client.flush();
      System.out.println("\n示例运行完毕");

    } catch (Exception e) {
      System.err.println("运行过程中出现异常: " + e.getMessage());
      e.printStackTrace();
    }
  }

  private static void doBusinessLogic(CozeLoopClient client, CozeLoopSpan parentSpan) {
    // 可以在业务代码中创建子 Span
    try (CozeLoopSpan span = client.startSpan("business_logic", "logic", parentSpan)) {
      System.out.println("正在执行业务逻辑...");
      span.setTag("logic_type", "demo");
      // 模拟耗时
      try {
        Thread.sleep(100);
      } catch (InterruptedException ignored) {
      }


      // 模拟模型调用
      boolean success = callLLM(client);
      if (!success) {
        // 如果失败，设置错误状态码和错误信息
        span.setStatusCode(ERROR_CODE_LLM_CALL);
        span.setError(new RuntimeException("LLM 调用失败"));
      } else {
        span.setStatusCode(0); // 0 表示成功
      }
    }
  }

  /** 模拟 LLM 调用 */
  private static boolean callLLM(CozeLoopClient client) {
    // 创建 LLM 调用的 span
    try (CozeLoopSpan span = client.startSpan("llmCall", "model")) {
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
        return false;
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
      return false;
    }
  }

  private static void executePromptDemo(CozeLoopClient client, String promptKey) {
    System.out.println("\n--- 开始执行 Prompt 示例 ---");

    // 准备执行参数
    Map<String, Object> variableVals = new HashMap<>();
    variableVals.put("query", "你好，请自我介绍一下");

    ExecuteParam param = ExecuteParam.builder()
        .promptKey(promptKey)
        .variableVals(variableVals)
        .build();

    try {
      // 同步执行
      ExecuteResult result = client.execute(param);

      System.out.println("Prompt 执行结果:");
      if (result.getMessage() != null) {
        System.out.println("内容: " + result.getMessage().getContent());
      }
      if (result.getUsage() != null) {
        System.out.println("Token 使用情况: " + JsonUtils.toJson(result.getUsage()));
      }
    } catch (Exception e) {
      System.err.println("Prompt 执行失败: " + e.getMessage());
    }
  }
}
