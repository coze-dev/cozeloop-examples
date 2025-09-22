# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT


"""
PTaaS Basic Example
"""

import asyncio
import json
import os

from cozeloop.decorator import observe
from cozeloop import new_client, Client
from cozeloop.entities.prompt import Message, Role, ExecuteResult


# Set the following environment variables first.
# COZELOOP_WORKSPACE_ID=your workspace id
# COZELOOP_API_TOKEN=your pat or sat token
cozeloop_prompt_key = os.environ["COZELOOP_PROMPT_KEY"] or "CozeLoop_Oncall_Master" # your prompt key, use CozeLoop_Oncall_Master by default, you can find it in Demo Workspace


def setup_client() -> Client:
    """
    Unified client setup function

    Environment variables:
    - COZELOOP_WORKSPACE_ID: workspace ID
    - COZELOOP_API_TOKEN: API token
    """
    # Set the following environment variables first.
    # COZELOOP_WORKSPACE_ID=your workspace id
    # COZELOOP_API_TOKEN=your token
    client = new_client(
        workspace_id=os.getenv("COZELOOP_WORKSPACE_ID"),
        api_token=os.getenv("COZELOOP_API_TOKEN"),
    )
    return client


@observe(
    span_type="tool",
)
def acquire_knowledge(query: str):
    if (query.__contains__("Windows") or query.__contains__("windows")) and query.__contains__("shut down"):
        return "Find the shutdown button in the Windows icon, and click to shut down"
    return "No relevant information found"


def print_execute_result(result: ExecuteResult) -> None:
    if result.message:
        print(f"Message: {result.message}")
    if result.finish_reason:
        print(f"FinishReason: {result.finish_reason}")
    if result.usage:
        print(f"Usage: {result.usage}")


async def async_non_stream_example(client: Client) -> None:
    query = "How to shut down Windows 11 system？"
    print(f"Query: {query}")
    result = await client.aexecute_prompt(
        prompt_key=cozeloop_prompt_key,
        # version="0.0.1", # If no specific version is specified, the latest version of the corresponding prompt will be obtained
        variable_vals={
            "name": "Windows system question tool",
            "platform": "windows system"
        },
        # You can also append messages to the prompt.
        messages=[
            Message(role=Role.USER, content=query)
        ],
        stream=False
    )
    print_execute_result(result)
    if result.message and len(result.message.tool_calls) > 0:
        for tool_call in result.message.tool_calls:
            if tool_call.function_call.name == "acquire_knowledge":
                data_dict = json.loads(tool_call.function_call.arguments)
                query = data_dict.get('query', '')
                tool_call_result = acquire_knowledge(query)
                print(f'Final Result: {tool_call_result}')


async def main():
    # 1.Create a prompt on the platform
    # The Prompt of demo is CozeLoop_Oncall_Master, you can copy it from 'Demo Workspace',
    # add the following messages to the template, submit a version.

    # Set the following environment variables first.
    # COZELOOP_WORKSPACE_ID=your workspace id
    # COZELOOP_API_TOKEN=your token
    # 2.New loop client
    client = setup_client()

    try:
        # Async non-stream call
        await async_non_stream_example(client)

    finally:
        # Close client
        if hasattr(client, 'close'):
            client.close()


if __name__ == "__main__":
    asyncio.run(main())