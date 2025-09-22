// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

package spring.ai.example.spring_ai_demo;

import io.opentelemetry.api.common.Attributes;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.prompt.Prompt;
import org.springframework.ai.model.tool.DefaultToolCallingChatOptions;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.boot.CommandLineRunner;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Bean;
import org.springframework.context.i18n.LocaleContextHolder;

import io.opentelemetry.exporter.otlp.http.trace.OtlpHttpSpanExporter;
import io.opentelemetry.sdk.trace.export.BatchSpanProcessor;
import io.opentelemetry.api.GlobalOpenTelemetry;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.Tracer;
import io.opentelemetry.context.Scope;
import io.opentelemetry.sdk.OpenTelemetrySdk;
import io.opentelemetry.sdk.trace.SdkTracerProvider;
import reactor.core.publisher.Flux;

import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.Map;
import java.util.function.Supplier;


@SpringBootApplication
public class Application {
    public static void initOpenTelemetry() { // for custom span, if you do not need custom span, can delete it
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
        OpenTelemetrySdk openTelemetrySdk = OpenTelemetrySdk.builder()
                .setTracerProvider(tracerProvider)
                .buildAndRegisterGlobal();
    }

    public static void main(String[] args) {
        SpringApplication app = new SpringApplication(Application.class);
        app.run(args);
    }

    static class DateTimeTools {

        @Tool(description = "Get the current date and time in the user's timezone")
        String getCurrentDateTime(String query) {
            return LocalDateTime.now().atZone(LocaleContextHolder.getTimeZone().toZoneId()).toString();
        }

        @Tool(description = "Get the current weather in the given location")
        String getCurrentWeather() {
            return "今天上海多云转晴，温度25摄氏度";
        }

    }

    @Bean
    CommandLineRunner cli(ChatClient.Builder builder) {
        return args -> {
            // Init OpenTelemetry, for custom span
            initOpenTelemetry();

            // create Tracer
            Tracer tracer = GlobalOpenTelemetry.getTracer("exampleTracer");
            // create root span with userID and sessionID
            Span span = tracer.spanBuilder("root-span")
                    .setAttribute("user.id", "user-123456")
                    .setAttribute("session.id", "session-123456")
                    .setAttribute("cozeloop.span_type", "model")
                    .startSpan();
            span.addEvent("gen_ai.system.message", Attributes.builder()
                    .put("content", "Hello World!")
                    .put("role", "system")
                    .build());
            span.addEvent("gen_ai.assistant.message", Attributes.builder()
                    .put("content", "Hello!")
                    .put("role", "assistant")
                    .build());
            try (Scope ignored = span.makeCurrent()) {
                invokeAI(builder);
            } finally {
                span.end();
            }
        };
    }

    private void invokeAI(ChatClient.Builder builder) {
        var chat = builder.build();
        var prompt = new Prompt("你是一个专业的沟通师，可以根据用户的问题给出准确的回答",
                DefaultToolCallingChatOptions.builder().model("doubao-1-5-pro-256k-250115").build()); // use your model

// not stream
        System.out.println(chat.prompt(prompt).system("回答用户问题").user("今天几月几号?")
                .tools(new DateTimeTools())
                .call()
                .content());

// stream
//        Flux<String> stream = chat.prompt(prompt).user("今天几月几号?")
//                .tools(new DateTimeTools())
//                .stream()
//                .content();
//        stream.subscribe(
//                System.out::print,
//                error -> System.err.println("Error: " + error.getMessage()),
//                System.out::println
//        );

    }
}

