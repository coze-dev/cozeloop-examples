# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import json
import os

import cozeloop
from openai import OpenAI
from cozeloop.decorator import observe
from cozeloop.integration.wrapper import openai_wrapper

# Set the following environment variables first.
# COZELOOP_WORKSPACE_ID=your workspace id
# COZELOOP_API_TOKEN=your pat or sat token
base_url = os.environ["OPENAI_BASE_URL"] or "https://ark.cn-beijing.volces.com/api/v3" # use ark model url by default, refer: https://www.volcengine.com/docs/82379/1361424
api_key = os.environ["OPENAI_API_KEY"] # your ark model key
model_name = os.environ["OPENAI_MODEL_NAME"] # ark model name, like doubao-1-5-vision-pro-32k-250115
cozeloop_prompt_key = os.environ["COZELOOP_PROMPT_KEY"] or "CozeLoop_Oncall_Master" # your prompt key, use CozeLoop_Oncall_Master by default, you can find it in Demo Workspace


openai_client = openai_wrapper(OpenAI(
    base_url=base_url,
    api_key=api_key,
))


@observe(
    span_type="tool",
)
def acquire_knowledge(query: str):
    if (query.__contains__("Windows") or query.__contains__("windows")) and query.__contains__("shut down"):
        return "Find the shutdown button in the Windows icon, and click to shut down"
    return "No relevant information found"


class LLMRunner:
    def __init__(self, client):
        self.client = client

    def llm_call(self, input_data, user_query):
        input_data.append(
            {
                "role": "user",
                "content": user_query,
            }
        )

        res = openai_client.chat.completions.create(  # chat completion
            messages=input_data,
            model=model_name, # ark model name, like doubao-1-5-vision-pro-32k-250115
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "acquire_knowledge",
                        "description": "获取平台知识库作为上下文信息",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "用户想要查询的关于平台的信息"
                                }
                            },
                            "required": [
                                "query"
                            ]
                        }
                    },
                }
            ]

        )
        print(f'llm_call res: {res}')
        return res


if __name__ == '__main__':
    # 1.Create a prompt on the platform
    # The Prompt of demo is CozeLoop_Oncall_Master, you can copy it from 'Demo Workspace',
    # add the following messages to the template, submit a version.

    # Set the following environment variables first.
    # COZELOOP_WORKSPACE_ID=your workspace id
    # COZELOOP_API_TOKEN=your token
    # 2.New loop client
    client = cozeloop.new_client(
        # Set whether to report a trace span when get or format prompt.
        # Default value is false.
        prompt_trace=True)

    # 3. New root span
    rootSpan = client.start_span("root_span", "main_span")
    user_input = "How to shut down Windows 11 system？"
    rootSpan.set_input(user_input)

    # 4. Get the prompt
    # If no specific version is specified, the latest version of the corresponding prompt will be obtained
    prompt = client.get_prompt(prompt_key=cozeloop_prompt_key)
    if prompt is not None:
        # Get messages of the prompt
        if prompt.prompt_template is not None:
            messages = prompt.prompt_template.messages
            print(
                f"prompt messages: {json.dumps([message.model_dump(exclude_none=True) for message in messages], ensure_ascii=False)}")
        # Get llm config of the prompt
        if prompt.llm_config is not None:
            llm_config = prompt.llm_config
            print(f"prompt llm_config: {llm_config.model_dump_json(exclude_none=True)}")

        # 5.Format messages of the prompt
        formatted_messages = client.prompt_format(prompt, {
            "name": "Windows system question tool",
            "platform": "windows system"
        })
        formatted_messages_dump = [message.model_dump(exclude_none=True) for message in formatted_messages]
        print(f"formatted_messages: {formatted_messages_dump}")

        # 6.LLM call
        llm_runner = LLMRunner(client)
        llm_res = llm_runner.llm_call(formatted_messages_dump, user_input)
        if llm_res and llm_res.choices:
            if llm_res.choices[-1].message.tool_calls:
                tool_call = llm_res.choices[-1].message.tool_calls[0]
                if tool_call.function.name == "acquire_knowledge":
                    tool_call_res = acquire_knowledge(tool_call.function.arguments)
                    rootSpan.set_output(tool_call_res)
                    print(f'acquire knowledge, tool_call res: {tool_call_res}')

    rootSpan.finish()
    # 4. (optional) flush or close
    # -- force flush, report all traces in the queue
    # Warning! In general, this method is not needed to be call, as spans will be automatically reported in batches.
    # Note that flush will block and wait for the report to complete, and it may cause frequent reporting,
    # affecting performance.
    client.flush()
