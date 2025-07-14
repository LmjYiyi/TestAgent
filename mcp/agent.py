from langchain.agents import create_react_agent, AgentExecutor
from langchain_core.prompts import PromptTemplate
from langchain_openai import ChatOpenAI

import os
from dotenv import load_dotenv

from tools.calculator_tool import calculator_tool
from tools.qry_interfaces import qry_interface_tool

# 加载 .env 文件
load_dotenv()
# 读取环境变量
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
MODEL = os.getenv('MODEL')
BASE_URL = os.getenv('OPENAI_API_BASE')
# 创建 LLM
llm = ChatOpenAI(
    openai_api_key=OPENAI_API_KEY,
    base_url=BASE_URL,
    model=MODEL,
    temperature=0,
    streaming=False
)
#  tools：你定义的工具列表
tools = [
    calculator_tool,
    qry_interface_tool
]


# Step 3: 构造工具描述字符串
tool_descriptions = "\n".join([f"{t.name}: {t.description}" for t in tools])
tool_names = ", ".join([t.name for t in tools])

template = '''Answer the following questions as best you can. You have access to the following tools:

            {tools}

            Use the following format:

            Question: the input question you must answer
            Thought: you should always think about what to do
            Action: the action to take, should be one of [{tool_names}]
            Action Input: the input to the action
            Observation: the result of the action
            Thought: I now know the final answer
            Final Answer: the final answer to the original input question

            Begin!

            Question: {input}
            Thought:{agent_scratchpad}'''

prompt = PromptTemplate.from_template(template)
# 5. 创建 ReAct Agent（自动注入 tools/tool_names）
agent = create_react_agent(llm=llm, tools=tools, prompt=prompt)

# 6. 执行器
executor = AgentExecutor.from_agent_and_tools(agent=agent, tools=tools, verbose=True,handle_parsing_errors=True)
def simple_agent(input, session_id):
    result = executor.invoke(input)
    print("simple_agent："+result)
    return result