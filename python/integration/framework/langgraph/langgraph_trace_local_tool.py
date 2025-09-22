# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from pprint import pprint
import time
import os

from cozeloop import new_client, set_default_client, set_log_level
from cozeloop.integration.langchain.trace_callback import LoopTracer
from langchain_core.runnables import RunnableConfig
from typing import TypedDict
import openai
from typing import (
    Annotated,
    Type
)

from openevals.types import ChatCompletionMessage
from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import AnyMessage, add_messages, MessagesState
from langchain_openai import AzureChatOpenAI, ChatOpenAI
from langgraph.prebuilt import ToolNode
from langchain_core.tools import tool, BaseTool
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.output_parsers import JsonOutputParser

# OpenAI env
os.environ['OPENAI_BASE_URL'] = 'https://ark.cn-beijing.volces.com/api/v3' # ark model url
os.environ['OPENAI_API_KEY'] = '***' # your ark model key, from https://www.volcengine.com/docs/82379/1361424
os.environ['OPENAI_MODEL_NAME'] = '***' # ark model name, like doubao-1-5-vision-pro-32k-250115

# cozeloop env
os.environ["COZELOOP_API_TOKEN"] = "sat_***"  # cozeloop pat or sat token, reference doc: https://loop.coze.cn/open/docs/cozeloop/authentication-for-sdk
os.environ["COZELOOP_WORKSPACE_ID"] = "***"  # your cozeloop spaceID

# Initialize OpenAI client
openai_client = openai.OpenAI()

# JSON processing
parser = JsonOutputParser()


# Local search tool implementation
class SearchToolInput(BaseModel):
    query: str = Field(description="Search query")


class LocalSearchTool(BaseTool):
    name: str = "search_tool"
    description: str = "A local search tool that provides search results for various queries"
    args_schema: Type[BaseModel] = SearchToolInput

    def _run(self, query: str):
        # Local implementation of search functionality
        # This is a mock implementation that returns sample search results
        search_results = [
            {
                "title": f"Search result for: {query}",
                "content": f"This is a sample search result for the query '{query}'. In a real implementation, this would connect to a search engine or local index.",
                "url": f"https://example.com/search?q={query.replace(' ', '+')}"
            },
            {
                "title": f"Related information about {query}",
                "content": f"Additional information related to '{query}'. This could include relevant articles, documents, or data sources.",
                "url": f"https://example.com/related/{query.replace(' ', '-')}"
            }
        ]

        result = "Search Results:\n"
        for i, item in enumerate(search_results, 1):
            result += f"{i}. {item['title']}\n"
            result += f"   Content: {item['content']}\n"
            result += f"   URL: {item['url']}\n\n"

        return result

    async def _arun(self, query: str):
        # Async version of the search functionality
        return self._run(query)


# Local law knowledge tool implementation
class LawToolInput(BaseModel):
    question: str = Field(description="Legal related question")


class LocalLawTool(BaseTool):
    name: str = "law_knowledge_tool"
    description: str = "A local legal knowledge tool for answering questions about minor protection law, copyright law, company law and other related legal knowledge"
    args_schema: Type[BaseModel] = LawToolInput

    def _run(self, question: str):
        # Local implementation of legal knowledge base
        # This is a mock implementation with sample legal knowledge
        legal_knowledge_base = {
            "minor protection": {
                "school protection": "Schools shall establish and improve the campus safety management system, take necessary measures to prevent and stop bullying and violence on campus, and protect the physical and mental health of minors.",
                "social protection": "Social organizations should actively participate in the protection of minors, provide necessary support and assistance, and create a good social environment for the healthy growth of minors."
            },
            "copyright": {
                "basic rights": "Copyright owners have the exclusive rights to reproduce, distribute, display, perform, and create derivative works based on their original works.",
                "fair use": "Fair use allows limited use of copyrighted material without permission for purposes such as criticism, comment, news reporting, teaching, scholarship, or research."
            },
            "company law": {
                "corporate governance": "Companies must establish proper governance structures including board of directors, supervisory committees, and shareholder meetings.",
                "fiduciary duties": "Directors and officers owe fiduciary duties to the company and shareholders, including duties of care and loyalty."
            }
        }

        # Simple keyword matching for demonstration
        question_lower = question.lower()
        result = "Legal Knowledge Response:\n\n"

        if "minor" in question_lower or "protection" in question_lower:
            if "school" in question_lower:
                result += f"School Protection Law: {legal_knowledge_base['minor protection']['school protection']}\n\n"
            elif "social" in question_lower:
                result += f"Social Protection Law: {legal_knowledge_base['minor protection']['social protection']}\n\n"
            else:
                result += f"Minor Protection - School: {legal_knowledge_base['minor protection']['school protection']}\n"
                result += f"Minor Protection - Social: {legal_knowledge_base['minor protection']['social protection']}\n\n"

        elif "copyright" in question_lower:
            result += f"Copyright Basic Rights: {legal_knowledge_base['copyright']['basic rights']}\n"
            result += f"Fair Use: {legal_knowledge_base['copyright']['fair use']}\n\n"

        elif "company" in question_lower:
            result += f"Corporate Governance: {legal_knowledge_base['company law']['corporate governance']}\n"
            result += f"Fiduciary Duties: {legal_knowledge_base['company law']['fiduciary duties']}\n\n"

        else:
            result += f"General legal information for question: {question}\n"
            result += "For specific legal advice, please consult with a qualified attorney.\n\n"

        result += "Note: This is a local implementation providing general legal information only."
        return result

    async def _arun(self, question: str):
        # Async version of the legal knowledge functionality
        return self._run(question)


# Initialize LLM and local tools
search_tool = LocalSearchTool()
toolList = [LocalSearchTool(), LocalLawTool()]
tool_node = ToolNode(toolList)

model_with_tools = ChatOpenAI(
    base_url=os.environ['OPENAI_BASE_URL'],
    model=os.environ['OPENAI_MODEL_NAME']
).bind_tools(tools=toolList)

model_4o = ChatOpenAI(
    base_url=os.environ['OPENAI_BASE_URL'],
    model=os.environ['OPENAI_MODEL_NAME']
)

model_o1 = ChatOpenAI(
    base_url=os.environ['OPENAI_BASE_URL'],
    model=os.environ['OPENAI_MODEL_NAME'],
    max_tokens=8192,
)

sp = """
# Role 
You are a data generation expert
Your goal is to help users generate required data


## Work Steps 
1. Understand user intent from input
2. Generate data

### Step 1: Understand user intent from input
1. Understand user intent from user input, including the scenario for data generation, field meanings and formats, classification requirements and quantity requirements

### Step 2: Generate data(Only use the tool once)
1. If tool exists in message history, do not use tool, directly generate data based on input.
2. If tool does not exist in message history, use tool to generate data based on user input.
3. Use appropriate data generation tools, generate each type of data according to user's scenario requirements, field meanings and classification requirements. The response format should be a JSON array, where each element in the JSON array follows the field format requirements given in the user input. Note that each element's structure needs to include an additional field 'classification', example as follows:
[
{
"input": "A minimalist white cotton shirt with classic pointed collar design and delicate buttons on the cuffs",
"output": "https://s.coze.cn/t/W-ljD1vr8tE/",
"classification": "E-commerce domain"
},
{
"input": "A scene from an ancient costume fantasy short drama, with misty fairy sect where disciples are practicing martial arts",
"output": "https://s.coze.cn/t/RMt2pu04iRM/",
"classification": "Film and TV domain"
}
]
"""

score_sp = """
# Role 
You are a scoring expert
Your goal is to score each row of data in the data list

## Work Steps 
1. Understand context
2. Score and filter

### Step 1: Understand context
1. Understand user intent and related supplementary information based on the context field

### Step 2: Score and filter
1. Score each row of data according to the following scoring rules:
    If data doesn't match user's expected data generation scenario, score 0
    If data doesn't match user's required classification, score 0
    If data doesn't match user's required field format, score 0
    The more data matches user requirements, the higher the score; the higher data complexity, the higher the score, for example, rarer and harder to understand data gets higher scores; the more specific the data, the higher the score
2. Add a 'score' field to each element in the JSON array and fill in the score
"""

score_leader_sp = """
# Role 
You are a score merging expert. You receive multiple groups of data, extract data at each position based on index, and calculate the average score of their scores

# Work Steps 
1. Traverse and extract elements at corresponding positions in each group based on index, calculate the average score. Filter out those below 0.5, and write those equal to or above 0.5 into a new list
2. Output the new list, which is a JSON array

# User input example as follows
First group scores:
[
{
"input":"Hello",
"output":"I'm fine"
"classification":"Q&A",
"score":1
},
{
"input":"How's the weather today",
"output":"Not bad"
"classification":"Q&A",
"score":0.6
}
]

Second group scores:
[
{
"input":"Hello",
"output":"I'm fine"
"classification":"Q&A",
"score":0
},
{
"input":"How's the weather today",
"output":"Not bad"
"classification":"Q&A",
"score":0.2
}
]

First group first element score=1, second group first element score=0, so output first element score=0.5. First group second element score=0.6, second group second element score=0.2, so output second element score=0.4. Final output example as follows:
[
{
"input":"Hello",
"output":"I'm fine"
"classification":"Q&A",
"score":0.5
},
{
"input":"How's the weather today",
"output":"Not bad"
"classification":"Q&A",
"score":0.4
}
]

# Note
Do not output scoring process and reasons, only output the final JSON array
"""


class MyState(TypedDict):
    messages_list: Annotated[list[AnyMessage], add_messages]
    messages: Annotated[list[AnyMessage], add_messages]
    score_by_4o: bool = False
    score_by_4o_res: str = ""
    score_by_o1: bool = False
    score_by_o1_res: str = ""


def should_continue(state: MyState):
    messages = state["messages"]
    last_message = messages[-1]
    if last_message.tool_calls:
        return "tools"
    return "score_leader"


def organize(state: MyState):
    if 'score_by_o1' not in state:
        return "score_o1"
    if not state["score_by_o1"]:
        return "score_o1"
    if 'score_by_4o' not in state:
        return "score_by_4o"
    if not state["score_by_4o"]:
        return "score_4o"
    return END


def call_model(state: MyState):
    messages = state["messages"]
    messages.append(SystemMessage(content=sp))
    response = model_with_tools.invoke(messages, RunnableConfig(tags=["tool_selection_node"]))
    return {"messages": [response]}


def scorer_leader(state: MyState) -> dict | str:
    if 'score_by_o1' in state and state["score_by_o1"] and 'score_by_4o' in state and state["score_by_4o"]:
        input = "First group scores:" + state["score_by_o1_res"] + "Second group scores:" + state["score_by_4o_res"]
        human_message = HumanMessage(content=input)
        system_message = SystemMessage(content=score_leader_sp)
        response = model_with_tools.invoke([system_message, human_message])
        try:
            parsed_output = parser.parse(response.content)
            response.content = parsed_output
        except Exception as e:
            print(f"Parsing failed: {e}, original output: {response}")
        return {"messages": [response]}
    return


def scorer_4o(state: MyState) -> dict:
    messages = state["messages"]
    messages.append(SystemMessage(content=score_sp))
    response = model_4o.invoke(messages)
    return {"messages": [response], "score_by_o1": True, "score_by_4o": True, "score_by_4o_res": response.content}


def scorer_o1(state: MyState) -> dict:
    messages = state["messages"]
    messages.append(SystemMessage(content=score_sp))
    response = model_o1.invoke(messages)
    return {"messages": [response], "score_by_o1": True, "score_by_4o": False, "score_by_o1_res": response.content,
            "score_by_4o_res": ""}


workflow = StateGraph(MyState)

# Define the two nodes we will cycle between
workflow.add_node("agents", call_model)
workflow.add_node("tools", tool_node)
workflow.add_node("score_leader", scorer_leader)
workflow.add_node("score_4o", scorer_4o)
workflow.add_node("score_o1", scorer_o1)

workflow.add_edge(START, "agents")
workflow.add_conditional_edges("agents", should_continue, ["tools", "score_leader"])
workflow.add_edge("tools", "agents")
workflow.add_conditional_edges("score_leader", organize, ["score_4o", "score_o1", END])
workflow.add_edge("score_4o", "score_leader")
workflow.add_edge("score_o1", "score_leader")

app = workflow.compile()

reference_outputs_1 = []
reference_outputs_1.append(ChatCompletionMessage(role="ai", content="", tool_calls=[
    {'name': 'law_knowledge_tool',
     'args': {'question': 'What are the legal regulations for schools to protect minor students?'}},
    {'name': 'law_knowledge_tool',
     'args': {'question': 'What legal responsibilities do social organizations have in protecting minors?'}}
]))

reference_outputs_2 = []
reference_outputs_2.append(ChatCompletionMessage(role="ai", content="", tool_calls=[
    {'name': 'search_tool', 'args': {'query': 'Latest technology news in 2025'}},
    {'name': 'search_tool', 'args': {'query': 'Latest entertainment news in 2025'}}
]))

examples = [
    {
        "inputs": {
            "question": "I need to conduct legal knowledge evaluation for AI applications. Please generate some data that can evaluate minor protection law. Expected data categories: School Protection: legal knowledge related to school protection, need to generate 1 item. Social Protection: knowledge related to social protection, need to generate 1 item. Expected field format as JSON: {\"input\":\"Question about minor protection law\",\"output\":\"Related answer\",\"provision\":\"Referenced legal provision\"}",
        },
        "outputs": {"messages": reference_outputs_1}
    },
    {
        "inputs": {
            "question": "I need to conduct news headline summarization evaluation for AI applications. Please generate some data that can evaluate news headlines, requiring latest news from 2025. Expected data categories: Technology: technology-related news, need to generate 1 item. Entertainment: entertainment-related news, need to generate 1 item. Expected field format as JSON: {\"content\":\"Complete content of latest 2025 news, requiring more than 100 words\",\"title\":\"Corresponding news headline\"}",
        },
        "outputs": {"messages": reference_outputs_2}
    }
]


# Target function
def run_graph(inputs: dict) -> dict:
    content = ""
    # Set subgraph=True to stream events from subgraphs of the main graph: https://langchain-ai.github.io/langgraph/how-tos/streaming-subgraphs/
    # Set stream_mode="debug" to stream all possible events: https://langchain-ai.github.io/langgraph/concepts/streaming
    cozeloop_handler = LoopTracer.get_callback_handler()

    # Non-streaming request
    resp = app.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": inputs["question"],
                }
            ]
        },
        RunnableConfig(callbacks=[cozeloop_handler]),
        subgraphs=True,
        stream_mode="debug",
    )
    pprint(resp)

    # Streaming request
    # for namespace, chunk in app.stream(
    #         {
    #             "messages": [
    #                 {
    #                     "role": "user",
    #                     "content": inputs["question"],
    #                 }
    #             ]
    #         },
    #         RunnableConfig(callbacks=[cozeloop_handler]),
    #         subgraphs=True,
    #         stream_mode="debug",
    # ):
    #     # Event type for entering a node
    #     # Get final result
    #     # if chunk["type"] == "task_result":
    #     #     if chunk["payload"]["name"] == "score_leader":
    #     #         if len(chunk["payload"]["result"]) > 0:
    #     #             content = chunk["payload"]["result"][-1][-1][-1].content


if __name__ == '__main__':
    # Initialize cozeloop sdk and set default client
    client = new_client(ultra_large_report=True)
    set_default_client(client)

    # Execute graph
    run_graph(examples[0]["inputs"])
    time.sleep(2)
