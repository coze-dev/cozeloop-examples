package spring.ai.example.spring_ai_demo;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import io.micrometer.common.KeyValue;
import io.micrometer.observation.Observation;
import io.micrometer.observation.ObservationFilter;
import org.springframework.ai.chat.observation.ChatModelObservationContext;
import org.springframework.ai.chat.prompt.Prompt;
import org.springframework.ai.openai.OpenAiChatOptions;
import org.springframework.ai.tool.ToolCallback;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.Map;

@Component
public class ChatModelCompletionContentObservationFilter implements ObservationFilter {

    private final ObjectMapper objectMapper;

    public ChatModelCompletionContentObservationFilter(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    @Override
    public Observation.Context map(Observation.Context context) {
        if (!(context instanceof ChatModelObservationContext chatModelObservationContext)) {
            return context;
        }

        var prompts = processPrompts(chatModelObservationContext);
        var completions = processCompletion(chatModelObservationContext);

        chatModelObservationContext.addHighCardinalityKeyValue(new KeyValue() {
            @Override
            public String getKey() {
                return "cozeloop.input";
            }

            @Override
            public String getValue() {
                return prompts;
            }
        });

        chatModelObservationContext.addHighCardinalityKeyValue(new KeyValue() {
            @Override
            public String getKey() {
                return "cozeloop.output";
            }

            @Override
            public String getValue() {
                return completions;
            }
        });

        return chatModelObservationContext;
    }

    private String processPrompts(ChatModelObservationContext chatModelObservationContext) {
        try {
            Prompt request = chatModelObservationContext.getRequest();

            // transform request to cozeloop format
            Map<String, Object> transformedRequest = transformRequest(request);

            return objectMapper.writeValueAsString(transformedRequest);
        } catch (Exception e) {
            return "Error serializing request: " + e.getMessage();
        }
    }

    private Map<String, Object> transformRequest(Prompt request) {
        try {
            // use ObjectMapper copy with JavaTimeModule，support JDK17 java.time
            ObjectMapper mapperWithJavaTime = objectMapper.copy().registerModule(new JavaTimeModule());
            JsonNode requestNode = mapperWithJavaTime.valueToTree(request);

            Map<String, Object> result = new HashMap<>();
            List<Map<String, Object>> messages = new ArrayList<>();

            // process instructions
            JsonNode instructions = requestNode.get("instructions");
            if (instructions != null && instructions.isArray()) {
                for (JsonNode instruction : instructions) {
                    if (instruction.has("text")) {
                        String text = instruction.get("text").asText();
                        if (!text.isEmpty()) {
                            Map<String, Object> userMsg = new HashMap<>();
                            userMsg.put("role", instruction.get("messageType").asText());
                            userMsg.put("content", text);
                            messages.add(userMsg);
                        } else if (!instruction.get("responses").isEmpty()){ // tool
                            Map<String, Object> userMsg = new HashMap<>();
                            userMsg.put("role", instruction.get("messageType").asText());

                            String responsesStr = instruction.get("responses").toString();
                            try {
                                JsonNode responsesArray = objectMapper.readTree(responsesStr);
                                if (responsesArray.isArray() && responsesArray.size() > 0) {
                                    JsonNode firstResponse = responsesArray.get(0);

                                    JsonNode responseData = firstResponse.get("responseData");
                                    if (responseData != null) {
                                        String content = responseData.asText();
                                        if (content.startsWith("\"") && content.endsWith("\"")) {
                                            content = content.substring(1, content.length() - 1);
                                        }
                                        userMsg.put("content", content);
                                    }

                                    List<Map<String, Object>> toolCalls = new ArrayList<>();
                                    for (JsonNode response : responsesArray) {
                                        Map<String, Object> toolCall = new HashMap<>();

                                        JsonNode idNode = response.get("id");
                                        if (idNode != null) {
                                            toolCall.put("id", idNode.asText());
                                        }

                                        toolCall.put("type", "tool");

                                        Map<String, Object> function = new HashMap<>();
                                        JsonNode nameNode = response.get("name");
                                        if (nameNode != null) {
                                            function.put("name", nameNode.asText());
                                        }
                                        toolCall.put("function", function);

                                        toolCalls.add(toolCall);
                                    }

                                    userMsg.put("tool_calls", toolCalls);
                                } else {
                                    userMsg.put("content", responsesStr);
                                }
                            } catch (Exception e) {
                                userMsg.put("content", responsesStr);
                            }

                            messages.add(userMsg);
                        }
                    }
                }
            }

            result.put("messages", messages);

            List<Map<String, Object>> tools = new ArrayList<>();
            if (request.getOptions() instanceof OpenAiChatOptions toolCallingChatOptions) {
                List<ToolCallback> toolCallbacks = toolCallingChatOptions.getToolCallbacks();
                for (ToolCallback toolCallback : toolCallbacks) {
                    Map<String, Object> tool = new HashMap<>();
                    tool.put("type", "function");
                    Map<String, Object> function = new HashMap<>();
                    // name
                    String toolName = toolCallback.getToolDefinition().name();
                    function.put("name", toolName);
                    // description
                    String toolDescription = toolCallback.getToolDefinition().description();
                    function.put("description", toolDescription);
                    // parameters
                    String inputTypeSchemaNode = toolCallback.getToolDefinition().inputSchema();
                    JsonNode inputTypeSchemaNodeJson = objectMapper.readTree(inputTypeSchemaNode);
                    function.put("parameters", inputTypeSchemaNodeJson);

                    tool.put("function", function);
                    tools.add(tool);
                }

                result.put("tools", tools);
            }

            return result;
        } catch (Exception e) {
            // convert fail, use basic format
            Map<String, Object> errorResult = new HashMap<>();
            errorResult.put("messages", List.of());
            errorResult.put("tools", List.of());
            errorResult.put("error", "Failed to transform request: " + e.getMessage());
            return errorResult;
        }
    }

    private String processCompletion(ChatModelObservationContext context) {
        try {
            Object response = context.getResponse();
            if (response == null) {
                return "Response is null";
            }

            // transform response to cozeloop format
            Map<String, Object> transformedResponse = transformResponse(response);

            return objectMapper.writeValueAsString(transformedResponse);
        } catch (Exception e) {
            return "Error serializing response: " + e.getMessage();
        }
    }

    private Map<String, Object> transformResponse(Object response) {
        try {
            // use ObjectMapper copy with JavaTimeModule，support JDK17 java.time
            ObjectMapper mapperWithJavaTime = objectMapper.copy().registerModule(new JavaTimeModule());
            JsonNode responseNode = mapperWithJavaTime.valueToTree(response);

            Map<String, Object> result = new HashMap<>();
            List<Map<String, Object>> choices = new ArrayList<>();

            // process results
            JsonNode resultsNode = responseNode.get("results");
            List<JsonNode> outputs = new ArrayList<>();

            if (resultsNode != null && resultsNode.isArray()) {
                for (JsonNode item : resultsNode) {
                    outputs.add(item);
                }
            }

            for (int i = 0; i < outputs.size(); i++) {
                JsonNode output = outputs.get(i);
                Map<String, Object> choice = new HashMap<>();

                choice.put("index", i);

                Map<String, Object> message = new HashMap<>();

                JsonNode outputNode = output.get("output");
                if (outputNode != null) {
                    JsonNode messageTypeNode = outputNode.get("messageType");
                    if (messageTypeNode != null) {
                        message.put("role", messageTypeNode.asText());
                    } else {
                        message.put("role", "ai");
                    }

                    JsonNode textNode = outputNode.get("text");
                    if (textNode != null) {
                        message.put("content", textNode.asText());
                    } else {
                        message.put("content", "");
                    }

                    JsonNode toolCallsNode = outputNode.get("toolCalls");
                    if (toolCallsNode != null && toolCallsNode.isArray()) {
                        List<Map<String, Object>> toolCalls = new ArrayList<>();

                        for (JsonNode toolCall : toolCallsNode) {
                            Map<String, Object> transformedToolCall = new HashMap<>();

                            JsonNode idNode = toolCall.get("id");
                            if (idNode != null) {
                                transformedToolCall.put("id", idNode.asText());
                            }

                            JsonNode typeNode = toolCall.get("type");
                            if (typeNode != null) {
                                transformedToolCall.put("type", typeNode.asText());
                            }

                            Map<String, Object> function = new HashMap<>();

                            JsonNode nameNode = toolCall.get("name");
                            if (nameNode != null) {
                                function.put("name", nameNode.asText());
                            }

                            function.put("arguments", toolCall.get("arguments"));
                            transformedToolCall.put("function", function);

                            toolCalls.add(transformedToolCall);
                        }

                        message.put("tool_calls", toolCalls);
                    }
                } else {
                    message.put("content", "");
                }

                choice.put("message", message);

                // finish_reason
                JsonNode metadataNode = output.get("metadata");
                if (metadataNode != null) {
                    JsonNode finishReasonNode = metadataNode.get("finishReason");
                    if (finishReasonNode != null) {
                        String finishReason = finishReasonNode.asText();
                        switch (finishReason) {
                            case "TOOL_CALLS":
                                choice.put("finish_reason", "tool_calls");
                                break;
                            case "STOP":
                                choice.put("finish_reason", "stop");
                                break;
                            default:
                                choice.put("finish_reason", finishReason.toLowerCase());
                                break;
                        }
                    } else {
                        choice.put("finish_reason", "stop");
                    }
                } else {
                    choice.put("finish_reason", "stop");
                }

                choices.add(choice);
            }

            // use basic format by default
            if (choices.isEmpty()) {
                Map<String, Object> defaultChoice = new HashMap<>();
                defaultChoice.put("index", 0);
                Map<String, Object> defaultMessage = new HashMap<>();
                defaultMessage.put("role", "ai");
                defaultMessage.put("content", "");
                defaultChoice.put("message", defaultMessage);
                defaultChoice.put("finish_reason", "stop");
                choices.add(defaultChoice);
            }

            result.put("choices", choices);

            return result;
        } catch (Exception e) {
            // convert fail, use basic format by default
            Map<String, Object> errorResult = new HashMap<>();
            List<Map<String, Object>> errorChoices = new ArrayList<>();
            Map<String, Object> errorChoice = new HashMap<>();
            errorChoice.put("index", 0);
            Map<String, Object> errorMessage = new HashMap<>();
            errorMessage.put("role", "ai");
            errorMessage.put("content", "Failed to transform response: " + e.getMessage());
            errorChoice.put("message", errorMessage);
            errorChoice.put("finish_reason", "stop");
            errorChoices.add(errorChoice);
            errorResult.put("choices", errorChoices);
            return errorResult;
        }
    }
}