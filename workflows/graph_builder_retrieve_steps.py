from typing import TypedDict, List, Optional, Literal, Annotated, Sequence
from langchain_core.messages import SystemMessage, BaseMessage, HumanMessage, AIMessage
from langgraph.graph.message import add_messages
import ast
from fastmcp import Client
import asyncio


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


async def format_steps(result) -> List[str]:
    """
    从工具调用结果中提取并格式化步骤列表
    参数:
        result: 工具调用返回的结果对象
    返回:
        步骤列表，如 ["1. 第一步", "2. 第二步"]
    """
    steps = []
    if hasattr(result, 'structured_content') and isinstance(result.structured_content, dict):
        steps = result.structured_content.get('result', [])

    # 格式化输出
    return [f"{i + 1}. {step}" for i, step in enumerate(steps)]


async def retrieve_steps(state: AgentState) -> AgentState:
    """
       处理"查找操作步骤"阶段的状态流转
       :param state: 当前状态（包含 选择的接口+场景 dict 等）
       :return: 更新后的状态（包含 origin_step_list 和 output）
       """
    # 使用 FastMCP 客户端直接调用服务端的工具
    async with Client('../mcp_servers/mcp_server_steps.py') as client:
        query = {
            "interface_name": state['selected_scene'].get('interface'),
            "scenario_name": state['selected_scene'].get('scene')
        }
        tool_result = await client.call_tool('get_operation_steps', query)
        # 提取并格式化步骤
        formatted_steps = await format_steps(tool_result)
        if formatted_steps:
            output = "我找到以下接口场景步骤，请确认是否修改：\n" + \
                     "\n".join([f"{step}" for i, step in enumerate(formatted_steps)])
        else:
            print("未获取到有效步骤")
        return {
            **state,
            "output": output,
            "origin_step_list": formatted_steps,
            "step_list": None,
            "current_stage": "confirm_steps",  # 转到确认步骤阶段
            "messages": [AIMessage(content=output)],  # 追加 AI 回复到对话历史
            "error_message": None  # 清除历史错误
        }


def main():
    """主函数：初始化状态并执行查询流程"""
    # 1. 初始化状态（根据 AgentState 定义）
    initial_state: AgentState = {
        "user_input": "我想要注册相关接口的所有场景列表",  # 用户输入
        "current_stage": "query_scene",  # 初始阶段
        "pending_action": None,
        "user_confirmed": None,
        "api_list": [],  # 空列表初始化
        "selected_scene": {"interface": "用户注册", "scene": "渠道推广注册"},
        "origin_step_list": [],
        "step_list": [],
        "current_step": 0,
        "step_outputs": [],
        "step_results": [],
        "error_message": None,
        "retry_payload": None,
        "output": "",
        "messages": [HumanMessage(content="我想要注册接口相关的所有场景列表")]  # 对话历史初始化
    }

    # 2. 执行异步查询（通过事件循环）
    loop = asyncio.get_event_loop()
    updated_state = loop.run_until_complete(retrieve_steps(initial_state))  # 执行异步函数

    # 3. 打印结果（模拟 LangGraph 流程输出）
    print("\n===== 流程执行结果 =====")
    print(f"当前阶段: {updated_state['current_stage']}")
    print(f"步骤列表: {updated_state['origin_step_list']}")
    print(f"AI 回复用户: \n{updated_state['output']}")


if __name__ == "__main__":
    main()  # 启动主函数