from langchain.agents import AgentExecutor
from langchain.agents import create_tool_calling_agent
from models.dquestion import get_llm
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from utils import logger

llm = get_llm()

# 全局缓存
_agent_executor_cache = None
_client_instance = None


async def get_mcp_agent():
    global _agent_executor_cache, _client_instance

    if _agent_executor_cache is not None:
        return _agent_executor_cache

    logger.info("开始构造MCP代理>>>>......")

    if _client_instance is None:
        _client_instance = MultiServerMCPClient(
            {
                # 本地服务，注意args参数
                "math": {
                    "command": "python",
                    "args": ["mcp_servers/mcp_server_math.py"],
                    "transport": "stdio",
                },
                # 远程服务，需要启起来
                "weather": {
                    "url": "http://127.0.0.1:8000/sse",
                    "transport": "sse",
                }
            }
        )

    # 获取工具
    logger.info("开始获取工具>>>>......")
    tools = await _client_instance.get_tools()

    system_prompt = """你是一个智能助手，请优先调用工具来回答用户的问题。
    不要依赖内部知识库或猜测结果，所有回答都应尽可能基于工具返回的数据。
    不要编造不存在的问题，请完全基于用户提供的内容进行回答。
    """

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system_prompt),
            ("user", "{input}"),
            # 模型思考过程
            MessagesPlaceholder(variable_name="agent_scratchpad", optional=True),
        ]
    )

    agent = create_tool_calling_agent(llm, tools, prompt)

    # 执行器
    executor = AgentExecutor.from_agent_and_tools(
        agent=agent,
        tools=tools,
        verbose=True,
        # return_intermediate_steps=True, # 返回中间步骤
        early_stopping_method="generate",  # 超时自动生成答案
        max_iterations=5,  # 最多执行5步，不输入的话默认15
        handle_parsing_errors=True
    )
    # 获取到执行器
    logger.info("MCP代理构建完成>>>>......")
    _agent_executor_cache = executor
    return executor


async def close_mcp_agent():
    global _client_instance
    if _client_instance:
        await _client_instance.close_servers()
        _client_instance = None