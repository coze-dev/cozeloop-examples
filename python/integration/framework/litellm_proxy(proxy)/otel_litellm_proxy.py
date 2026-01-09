import os
from openai import OpenAI

# model env
base_url = os.environ.get('OPENAI_BASE_URL') or "http://0.0.0.0:4000"  # litellm proxy url
api_key = os.environ.get('OPENAI_API_KEY') or "anything"  # anything, because we are using litellm proxy
model_name = os.environ.get('OPENAI_MODEL_NAME') or "my-gpt-model"  # use model name you set in litellm proxy config

openai_client = OpenAI(
    base_url=base_url,
    api_key=api_key,
)

tools = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the current weather in a given location",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "The city and state, e.g. San Francisco, CA",
                    },
                    "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
                },
                "required": ["location", "unit"],
            }
        }
    }
]


def retriever():
    results = ["John worked at Beijing"]
    return results


def rag(question):
    docs = retriever()
    system_message = """Answer the question using only the provided information below:

    {docs}""".format(docs="\n".join(docs))

    res = openai_client.chat.completions.create(  # chat completion
        messages=[
            {"role": "system", "content": system_message},
            {"role": "user", "content": question},
        ],
        model=model_name,
        tools=tools,
    )
    print(res)


if __name__ == '__main__':
    rag("Where is John worked?")
