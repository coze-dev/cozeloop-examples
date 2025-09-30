import os

from openai import OpenAI

from cozeloop import new_client
from cozeloop.decorator import observe
from cozeloop.integration.wrapper import openai_wrapper

# cozeloop client init env
os.environ["COZELOOP_WORKSPACE_ID"] = "your workspace id"
os.environ["COZELOOP_API_TOKEN"] = "your token"

# model env
base_url = os.environ.get('OPENAI_BASE_URL') or "http://0.0.0.0:4000"  # litellm proxy url
api_key = os.environ.get('OPENAI_API_KEY') or "anything" # anything, because we are using litellm proxy
model_name = os.environ.get('OPENAI_MODEL_NAME') or "my-gpt-model" # use model name you set in litellm proxy config

openai_client = openai_wrapper(OpenAI(
    base_url=base_url,
    api_key=api_key,
))


def retriever():
    results = ["John worked at Beijing"]
    return results


@observe
def rag(question):
    docs = retriever()
    system_message = """Answer the question using only the provided information below:

    {docs}""".format(docs="\n".join(docs))

    res = openai_client.chat.completions.create(    # chat completion
        messages=[
            {"role": "system", "content": system_message},
            {"role": "user", "content": question},
        ],
        model=model_name,
    )
    print(res)


if __name__ == '__main__':
    # Set the following environment variables first (Assuming you are using a PAT token.).
    # os.environ["COZELOOP_WORKSPACE_ID"] = "your workspace id"
    # os.environ["COZELOOP_API_TOKEN"] = "your token"

    client = new_client()
    rag("Where is John worked?")
    client.flush()
