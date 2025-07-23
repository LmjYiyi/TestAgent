# 文件路径: agent/graph.py

import operator
from typing import Annotated, TypedDict, List

from langchain_core.messages import BaseMessage, HumanMessage
from models.dquestion import get_llm
from langgraph.graph import StateGraph, END

from utils.logger import setup_logger
from utils.db_utils import db_manager

logger = setup_logger()

# 这是一个简化的示例，你需要根据你的需求来定义状态、节点和图的结构
class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], operator.add]


def call_model(state):
    messages = state["messages"]
    # 在这里替换为你的模型，例如从配置中加载
    model = get_llm()
    response = model.invoke(messages)
    # 我们只返回响应，而不是整个状态，以便流式处理
    return {"messages": [response]}

# 定义图
workflow = StateGraph(AgentState)

# 定义节点
workflow.add_node("agent", call_model)

# 定义边
workflow.set_entry_point("agent")
workflow.add_edge("agent", END)

# 编译图的步骤将移至 app.py 的启动流程中
# 以确保 checkpointer 在编译时是可用的。
def build_graph(checkpointer=None):
    return workflow.compile(checkpointer=checkpointer)

app = build_graph()  # 默认编译，无检查点

logger.info("LangGraph Agent workflow defined.")

# 为了方便调试，我们可以添加一个简单的调用示例
if __name__ == '__main__':
    
    async def run_example():
        from langgraph.checkpoint.aiomysql import AIOMySQLSaver
        from utils.db_utils import db_manager

        await db_manager.initialize()
        memory = AIOMySQLSaver(conn=db_manager.get_pool())
        
        thread = {"configurable": {"thread_id": "test-thread-1"}}
        
        async for event in app.astream_events(
            {"messages": [HumanMessage(content="你好，我叫 Trae")]},
            thread,
            version="v1"
        ):
            kind = event["event"]
            if kind == "on_chat_model_stream":
                content = event["data"]["chunk"].content
                if content:
                    # Yielding content for streaming response
                    print(content, end="")

        await db_manager.close()

    import asyncio
    asyncio.run(run_example())