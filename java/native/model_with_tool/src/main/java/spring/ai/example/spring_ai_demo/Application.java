package spring.ai.example.spring_ai_demo;

import com.fasterxml.jackson.databind.JsonNode;
import com.volcengine.ark.runtime.model.completion.chat.ChatCompletionResult;
import io.opentelemetry.api.common.Attributes;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.boot.CommandLineRunner;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Bean;

import io.opentelemetry.exporter.otlp.http.trace.OtlpHttpSpanExporter;
import io.opentelemetry.sdk.trace.export.BatchSpanProcessor;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.Tracer;
import io.opentelemetry.context.Scope;
import io.opentelemetry.sdk.OpenTelemetrySdk;
import io.opentelemetry.sdk.trace.SdkTracerProvider;

import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.Map;
import java.util.function.Supplier;

import com.volcengine.ark.runtime.Const;
import com.volcengine.ark.runtime.model.completion.chat.ChatCompletionRequest;
import com.volcengine.ark.runtime.model.completion.chat.ChatMessage;
import com.volcengine.ark.runtime.model.completion.chat.ChatMessageRole;
import com.volcengine.ark.runtime.service.ArkService;
import com.volcengine.ark.runtime.model.completion.chat.ChatTool;
import com.volcengine.ark.runtime.model.completion.chat.ChatFunction;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.context.i18n.LocaleContextHolder;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;


@SpringBootApplication
public class Application {
    // global OpenTelemetry instance
    private static OpenTelemetrySdk openTelemetrySdk;

    public static OpenTelemetrySdk initOpenTelemetry() {
        // create otel trace HTTP exporter
        Supplier<Map<String, String>> headersSupplier = () -> {
            Map<String, String> headers = new HashMap<>();
            headers.put("cozeloop-workspace-id", System.getenv("COZELOOP_WORKSPACE_ID")); // your cozeloop workspaceID
            headers.put("Authorization", System.getenv("COZELOOP_API_TOKEN")); // your cozeloop pat token or sat token
            return headers;
        };
        OtlpHttpSpanExporter otlpExporter = OtlpHttpSpanExporter.builder()
                .setEndpoint(System.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")) // set cozeloop otel endpoint url
                .setHeaders(headersSupplier)
                .build();

        // create TracerProvider, and add BatchSpanProcessor
        SdkTracerProvider tracerProvider = SdkTracerProvider.builder()
                .addSpanProcessor(BatchSpanProcessor.builder(otlpExporter).build())
                .build();

        // create OpenTelemetrySdk instance
        return OpenTelemetrySdk.builder()
                .setTracerProvider(tracerProvider)
                .build();
    }

    String getCurrentDateTime() {
        return LocalDateTime.now().atZone(LocaleContextHolder.getTimeZone().toZoneId()).toString();
    }

    public static void main(String[] args) {
        // Init OpenTelemetry, for custom span
        openTelemetrySdk = initOpenTelemetry();
        SpringApplication app = new SpringApplication(Application.class);
        app.run(args);
    }

    @Bean
    CommandLineRunner cli(ChatClient.Builder builder) {
        return args -> {
            // create Tracer
            Tracer tracer = openTelemetrySdk.getTracer("exampleTracer");
            // create root span with userID and sessionID
            Span span = tracer.spanBuilder("root-span")
                    .setAttribute("user.id", "user-123456")
                    .setAttribute("session.id", "session-123456")
                    .setAttribute("cozeloop.span_type", "root")
                    .startSpan();
            try (Scope ignored = span.makeCurrent()) {
                // create child model span in root span scope
                Span childSpan = tracer.spanBuilder("ark-model")
                        .setAttribute("user.id", "user-123456")
                        .setAttribute("session.id", "session-123456")
                        .setAttribute("cozeloop.span_type", "model")
                        .startSpan();

                String apiKey = System.getenv("ARK_API_KEY");
                String modelName = System.getenv("ARK_MODEL_NAME");

                ArkService service = ArkService.builder().apiKey(apiKey).build();
                final List<ChatMessage> messages = new ArrayList<>();
                final ChatMessage userMessage = ChatMessage.builder().role(ChatMessageRole.USER).content("今天几号？").build();
                messages.add(userMessage);

                // get time tool
                ChatFunction function = new ChatFunction();
                function.setName("get_current_time");
                function.setDescription("获取当前系统时间");
                ObjectMapper mapper = new ObjectMapper();
                Map<String, Object> parameters = Map.of(
                        "type", "object",
                        "properties", Map.of(),
                        "required", new ArrayList<>()
                );
                function.setParameters(mapper.valueToTree(parameters));
                ChatTool timeTool = new ChatTool("function", function);

                ChatCompletionRequest chatCompletionRequest = ChatCompletionRequest.builder()
                        .model(modelName)
                        .messages(messages)
                        .tools(List.of(timeTool))
                        .toolChoice("auto")
                        .build();
                ChatCompletionResult res = service.createChatCompletion(chatCompletionRequest, new HashMap<String, String>() {
                });
                System.out.println(res);
                childSpan.addEvent("gen_ai.user.message", Attributes.builder()
                        .put("content", "今天几号？")
                        .put("role", "user")
                        .build());

                res.getChoices().forEach(choice -> {
                    childSpan.addEvent("gen_ai.choice", Attributes.builder()
                            .put("index", choice.getIndex())
                            .put("finish_reason", choice.getFinishReason())
                            .put("message.content", choice.getMessage().getContent().toString())
                            .put("message.role", choice.getMessage().getRole().value())
                            .put("message.tool_calls.0.id", choice.getMessage().getToolCalls().get(0).getId())
                            .put("message.tool_calls.0.type", choice.getMessage().getToolCalls().get(0).getType())
                            .put("message.tool_calls.0.function.name", choice.getMessage().getToolCalls().get(0).getFunction().getName())
                            .put("message.tool_calls.0.function.arguments", choice.getMessage().getToolCalls().get(0).getFunction().getArguments())
                            .build());

                    if (!choice.getMessage().getToolCalls().isEmpty()) {
                        // create tool span in root span scope
                        Span toolSpan = tracer.spanBuilder("getCurrentDateTime")
                                .setAttribute("cozeloop.span_type", "tool")
                                .startSpan();
                        String toolCallRes = getCurrentDateTime();
                        toolSpan.setAttribute("cozeloop.input", "{}");
                        toolSpan.setAttribute("cozeloop.output", toolCallRes);
                        toolSpan.end();
                    }
                });

                childSpan.end();
            } finally {
                span.end();
            }
        };
    }
}