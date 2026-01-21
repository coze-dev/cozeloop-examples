# Instructor Integration with CozeLoop

This example demonstrates how to integrate the [Instructor](https://python.useinstructor.com/) framework with CozeLoop using the CozeLoop SDK's `@observe` decorator and `openai_wrapper`.

## How to Run

### 1. Set Environment Variables

You need to provide your OpenAI API key and CozeLoop workspace credentials.

```bash
export OPENAI_API_KEY="your-api-key"
export OPENAI_MODEL_NAME="your-model-name"
export COZELOOP_WORKSPACE_ID="your-cozeloop-workspace-id"
export COZELOOP_API_TOKEN="your-cozeloop-pat-or-sat-token"
```

### 2. Run the Demo

```bash
python otel_instructor_openai_wrapper.py
```

## Key Features

- **Automatic LLM Tracing**: Uses `openai_wrapper` to intercept and report all LLM calls made by Instructor.
- **Custom Spans**: Uses the `@observe` decorator to create functional spans and `client.start_span` for manual root span control.
- **Structured Data**: Demonstrates Instructor's core capability of extracting Pydantic models while maintaining full trace visibility in CozeLoop.
