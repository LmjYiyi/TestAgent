from langchain.agents import AgentExecutor
from langchain.agents import create_tool_calling_agent
from models.dquestion import get_llm
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from utils import logger
from prompts.agent_prompts import SYSTEM_PROMPT

llm = get_llm()

# 全局缓存
_agent_executor_cache = None
_client_instance = None

# 清除缓存函数
def clear_agent_cache():
    global _agent_executor_cache, _client_instance
    _agent_executor_cache = None
    _client_instance = None


async def get_mcp_agent():
    global _agent_executor_cache, _client_instance

    # --- 启用缓存机制 ---
    # 如果缓存中已有实例，则直接返回，确保状态在步骤间传递
    if _agent_executor_cache:
        logger.info("从缓存中返回已存在的MCP代理实例>>>>......")
        return _agent_executor_cache

    logger.info("首次创建MCP代理实例>>>>......")

    try:
        # 如果没有客户端实例，则创建一个
        if not _client_instance:
            _client_instance = MultiServerMCPClient(
                {
                    # "math": {
                    #     "command": "python",
                    #     "args": ["mcp_servers/mcp_server_math.py"],
                    #     "transport": "stdio",
                    # },
                    "mysql": {
                        "url": "http://127.0.0.1:8003/sse",
                        "transport": "sse",
                    },
                    "test_project": {
                        "url": "http://localhost:8001/sse",
                        "transport": "sse",
                    }
                }
            )

        # 获取工具
        logger.info("开始获取工具>>>>......")
        tools = await _client_instance.get_tools()
    except Exception as e:
        logger.error(f"获取MCP工具失败: {e}")
        # 如果失败，清除实例以便下次重试
        _client_instance = None
        return None

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT),
            ("user", "{input}"),
            # 模型思考过程
            MessagesPlaceholder(variable_name="agent_scratchpad", optional=True),
        ]
    )

    agent = create_tool_calling_agent(llm, tools, prompt)

    # 创建Agent执行器
    executor = AgentExecutor.from_agent_and_tools(
        agent=agent,
        tools=tools,
        verbose=True,
        max_iterations=10,
        handle_parsing_errors=True,
        early_stopping_method="force",
        return_intermediate_steps=True
    )
    
    # 将执行器存入缓存
    _agent_executor_cache = executor
    logger.info("MCP代理构建完成并已缓存>>>>......")
    
    return _agent_executor_cache


async def close_mcp_agent():
    global _client_instance
    if _client_instance:
        await _client_instance.close()
        _client_instance = None
