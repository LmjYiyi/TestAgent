from typing import TypedDict, List, Optional, Literal, Annotated, Sequence
from langchain_core.messages import SystemMessage, BaseMessage, HumanMessage, AIMessage
from langgraph.graph.message import add_messages
import ast
from fastmcp import Client
import asyncio
from utils import logger


# ========================
# 1. 定义状态结构（AgentState）
# ========================
class AgentState(TypedDict):
    user_input: str  # 用户原始输入
    current_stage: Literal[
        "confirm_scene", "retrieve_steps", "confirm_steps", "execute_step"
    ]  # 当前流程阶段
    pending_action: Optional[str]  # 挂起的动作（如等待用户确认）
    user_confirmed: Optional[bool]  # 用户是否确认场景/步骤
    api_list: List[str]  # 接口场景列表（从工具返回）
    selected_scene: dict  # 选中的接口场景详情
    origin_step_list: List[str]  # 原始步骤列表（从工具返回）
    step_list: List[str]  # 最终执行的步骤列表（可能经过用户调整）
    current_step: int  # 当前执行步骤索引（从0开始）
    step_outputs: List[str]  # 各步骤输出结果（原始字符串）
    step_results: List[dict]  # 各步骤解析后的结果（结构化数据）
    error_message: Optional[str]  # 错误信息（如工具调用失败）
    retry_payload: Optional[str]  # 重试时携带的参数
    output: str  # 最终输出给用户的消息
    messages: Annotated[Sequence[BaseMessage], add_messages]  # 对话历史


# ========================
# 2. 异步工具调用函数（核心）
# ========================
async def query_scene_from_tool(query: str) -> List[str]:
    """
    异步调用 FastMCP 工具，获取接口场景列表
    :param query: 用户查询（如"我想要用户注册接口相关的所有场景列表"）
    :return: 接口场景列表（如 ["接口中文名: 用户注册, 场景名: 普通注册", ...]）
    """
    logger.info("正在调用 FastMCP-RAG 工具...")
    print(f"用户输入：{query}")
    try:
        # 1. 连接 FastMCP 服务端
        async with Client("mcp_servers/mcp_server_rag.py") as client:
            # 2. 调用 rag_match 工具
            print("正在调用 rag_match 工具...")
            query = {"query": query}
            tool_result = await client.call_tool('rag_match', query)

            # 提取原始字符串
            raw_text = tool_result.content[0].text.strip()

            # 去掉前缀 `api_list = [` 和末尾 `]`
            if raw_text.startswith("api_list = [") and raw_text.endswith("]"):
                raw_text = raw_text[len("api_list = ["):-1].strip()

            # 用逗号拆分并组合成一项一项的字符串
            items = []
            parts = raw_text.split(", ")
            for i in range(0, len(parts), 2):
                if i + 1 < len(parts):
                    item = f'{parts[i]}, {parts[i + 1]}'
                    items.append(item)
            api_list = items
            return api_list

    except Exception as e:
        # 捕获所有异常（网络错误、格式错误等）
        raise RuntimeError(f"获取接口场景失败: {str(e)}")


# ========================
# 3. 状态处理函数（集成工具调用）
# ========================
async def query_scene2(state: AgentState) -> AgentState:
    """
    处理"查询接口场景"阶段的状态流转
    :param state: 当前状态（包含 user_input 等）
    :return: 更新后的状态（包含 api_list 和 output）
    """
    logger.info("===开始调用获取接口场景列表接口===")
    try:
        # 1. 调用异步工具获取接口场景列表
        api_list = await query_scene_from_tool(state["user_input"])
        state["api_list"] = api_list  # 更新状态中的接口列表

        # 2. 生成用户确认消息（格式化场景列表）
        if api_list:
            output = "我找到以下接口场景，请输入编号确认（如 1）：\n" + \
                     "\n".join([f"{i+1}. {scene}" for i, scene in enumerate(api_list)])
        else:
            output = "未找到相关接口场景，请尝试其他查询关键词。"

        # 3. 更新状态（进入确认阶段）
        return {
            **state,
            "output": output,
            "current_stage": "confirm_scene",  # 切换到场景确认阶段
            "messages": [AIMessage(content=output)],  # 追加 AI 回复到对话历史
            "error_message": None  # 清除历史错误
        }

    except Exception as e:
        # 错误处理（保留当前阶段，返回错误信息）
        error_msg = f"查询失败: {str(e)}"
        return {
            **state,
            "output": error_msg,
            "error_message": error_msg,
            "current_stage": "confirm_scene",  # 仍停留在确认阶段（等待用户重试）
            "messages": [AIMessage(content=error_msg)]
        }


# ========================
# 4. 主函数（执行入口）
# ========================
def main():
    """主函数：初始化状态并执行查询流程"""
    # 1. 初始化状态（根据 AgentState 定义）
    initial_state: AgentState = {
        "user_input": "我想要订单查询接口相关的所有场景列表",  # 用户输入
        "current_stage": "query_scene",  # 初始阶段
        "pending_action": None,
        "user_confirmed": None,
        "api_list": [],  # 空列表初始化
        "selected_scene": {},
        "origin_step_list": [],
        "step_list": [],
        "current_step": 0,
        "step_outputs": [],
        "step_results": [],
        "error_message": None,
        "retry_payload": None,
        "output": "",
        "messages": [HumanMessage(content="我想要订单查询接口相关的所有场景列表")]  # 对话历史初始化
    }

    # 2. 执行异步查询（通过事件循环）
    loop = asyncio.get_event_loop()
    updated_state = loop.run_until_complete(query_scene2(initial_state))  # 执行异步函数

    # 3. 打印结果（模拟 LangGraph 流程输出）
    print("\n===== 流程执行结果 =====")
    print(f"当前阶段: {updated_state['current_stage']}")
    print(f"接口场景列表: {updated_state['api_list']}")
    print(f"AI 回复用户: \n{updated_state['output']}")


if __name__ == "__main__":
    main()  # 启动主函数