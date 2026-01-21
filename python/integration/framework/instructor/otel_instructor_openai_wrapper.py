# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import os
from pydantic import BaseModel
from openai import OpenAI
import instructor
from cozeloop import new_client
from cozeloop.decorator import observe
from cozeloop.integration.wrapper import openai_wrapper

# OpenAI env
os.environ['OPENAI_BASE_URL'] = 'https://ark.cn-beijing.volces.com/api/v3' # use ark model url by default, from https://www.volcengine.com/docs/82379/1361424
os.environ['OPENAI_API_KEY'] = '***'  # your api key
os.environ['OPENAI_MODEL_NAME'] = '***' # your model name, like doubao-1-5-vision-pro-32k-250115

# cozeloop client init
# Set the following environment variables first:
# os.environ["COZELOOP_WORKSPACE_ID"] = "your workspace id"
# os.environ["COZELOOP_API_TOKEN"] = "your pat or sat token"
cozeloop_client = new_client()

# Wrap OpenAI client with cozeloop's openai_wrapper to enable tracing.
# This ensures that LLM calls are captured by cozeloop.
# Then patch the wrapped client with instructor for structured data extraction.
patched_openai_client = openai_wrapper(OpenAI(
    api_key=os.environ.get('OPENAI_API_KEY'),
    base_url=os.environ.get('OPENAI_BASE_URL'),
))
client = instructor.patch(patched_openai_client)

class UserDetail(BaseModel):
    name: str
    age: int

@observe(span_type="workflow") # Customizing the span type
def extract_user_info(text: str):
    """
    This function is decorated with @observe, which creates a span in cozeloop.
    The nested LLM call via 'client.chat.completions.create' will be captured 
    by the 'openai_wrapper' and associated with this span.
    """
    user = client.chat.completions.create(
        model=os.environ.get('OPENAI_MODEL_NAME'),
        response_model=UserDetail,
        messages=[
            {"role": "user", "content": text},
        ],
    )
    return user

def main():
    # Example of a manual root span for even more control over the trace hierarchy.
    with cozeloop_client.start_span("Instructor_Root_Process", "root") as root_span:
        input_text = "Jason is 25 years old"
        root_span.set_input(input_text)
        
        print(f"Extracting info from: {input_text}")
        user_info = extract_user_info(input_text)
        
        print(f"Extracted info: {user_info}")
        root_span.set_output(user_info.model_dump_json())

    # Ensure all spans are sent to cozeloop
    cozeloop_client.flush()

if __name__ == "__main__":
    main()