from langchain.agents import  Tool, AgentExecutor
from langchain.agents import create_react_agent
from langchain_core.prompts import PromptTemplate, StringPromptTemplate
from models.dquestion import get_llm
from langchain_openai import OpenAI  # 确保这是正确的导入路径
import os
# from tools.calculator_tool import calculator_tool
# from tools.qry_interfaces import qry_interface_tool


def get_mcp_agent():
    # 1. 创建 LLM
    llm = get_llm()
    #  tools：你定义的工具列表
    tools = [
        # calculator_tool,
        #tool_web_search,
        #tool_get_current_weather,
        #tool_get_weather_forecast,
        #tool_search_city,
        # qry_interface_tool
    ]

    # Step 3: 构造工具描述字符串
    tool_descriptions = "\n".join([f"{t.name}: {t.description}" for t in tools])
    tool_names = ", ".join([t.name for t in tools])

    # 3. 构建 Prompt（保留变量：tools、tool_names）
    template = """你是一个智能体，能一步步思考并调用工具解决问题。
        
        工具列表：
        {tools}
        
        你可以使用这些工具：{tool_names}
        
        请严格使用以下格式回答：
        
        Question: <用户提问>...................
        Thought: <你的思考>
        Action: <工具名称，如 Search>
        Action Input: <传给工具的输入内容>
        Observation: <工具返回的结果>
        ...（多轮 Thought / Action / Action Input / Observation）
        Thought: 我已得到答案
        Final Answer: <最终回答>
        
        示例：
        Question: 天气怎么样？
        Thought: 我需要查询天气
        Action: Search
        Action Input: 北京天气
        Observation: 今天晴，25度
        Thought: 我已得到答案
        Final Answer: 北京今天晴，25度。
        
        现在开始：
        
        Question: {input}
        {agent_scratchpad}
    """

    # 4. 构造 PromptTemplate（保留 tools/tool_names）
    prompt = PromptTemplate.from_template(template)

    # 5. 创建 ReAct Agent（自动注入 tools/tool_names）
    agent = create_react_agent(llm=llm, tools=tools, prompt=prompt)

    # 6. 执行器
    executor = AgentExecutor.from_agent_and_tools(agent=agent, tools=tools, verbose=True,handle_parsing_errors=True)
    return executor