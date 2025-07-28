import sys
import os
import json
import asyncio
import re
from typing import TypedDict, List, Optional, Literal

# 将项目根目录添加到sys.path 我识别不到agents包。。。
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from langgraph.graph import StateGraph, END
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import SystemMessage, HumanMessage

from agents.mcp_agent import get_mcp_agent
from models.dquestion import get_llm
from utils import logger
from workflows.api_scene import TEST_SCENARIOS, get_scenario_steps, get_scenario_by_name


# --- 状态定义 ---
class AgentState(TypedDict):
    user_input: str
    current_stage: Literal[
        "confirm_scene", "retrieve_steps", "confirm_steps", "execute_step"]
    pending_action: Optional[str]
    user_confirmed: Optional[bool]
    api_list: List[str]
    selected_scene: dict
    origin_step_list: List[str]
    step_list: List[str]
    current_step: int
    step_outputs: List[str]
    step_results: List[dict]
    error_message: Optional[str]
    retry_payload: Optional[str]
    output: str
    history: List[str]
    db_schema: Optional[str]
    db_sample_data: Optional[str]
    current_request_params: Optional[dict]
    api_request_payload: Optional[dict]
    test_data: Optional[List[dict]]
    last_api_response: Optional[dict]
    assertion_result: Optional[dict]


# --- LangGraph 节点与边函数定义 ---

# 2.1 获取场景列表节点
def query_scene(state: AgentState) -> AgentState:
    logger.info("开始获取场景列表.....")
    
    # 直接从配置中加载场景列表
    api_list = list(TEST_SCENARIOS.keys())
    state["api_list"] = api_list

    output = "我找到以下场景，请输入编号确认：\n" + \
             "\n".join([f"{i + 1}. {s}" for i, s in enumerate(api_list)])
    return {
        **state,
        "output": output,
        "current_stage": "confirm_scene",
        "history": state["history"] + [f"助手：{output}"]
    }


# 2.2 用户确认场景节点
def confirm_scene(state: AgentState) -> AgentState:
    logger.info("用户进行场景选择.....")
    text = state["user_input"].strip()
    try:
        idx = int(text) - 1
        scene_name = state["api_list"][idx]
        selected_scene_data = TEST_SCENARIOS[scene_name]
        output = f"已选择场景：{scene_name}，开始查询执行步骤..."
        print(output)
        return {
            **state,
            "selected_scene": {"name": scene_name, "data": selected_scene_data},
            "origin_step_list": None,
            "step_list": None,
            "current_step": 0,
            "step_outputs": [],
            "step_results": [],
            "current_stage": "retrieve_steps",
            "output": "",
            "history": state["history"] + [f"助手：{output}"]
        }
    except Exception as e:
        output = f"输入无效，请重新输入编号确认场景。错误：{str(e)}"
        return {
            **state,
            "output": output,
            "history": state["history"] + [f"助手：{output}"]
        }


# 2.3 获取预定义步骤节点 (从 api_scene.py 获取)
def retrieve_steps(state: AgentState) -> AgentState:
    logger.info("开始获取预定义测试步骤....")
    
    scene_name = state["selected_scene"]["name"]
    
    # 从 api_scene.py 获取预定义的步骤
    step_list = get_scenario_steps(scene_name)
    
    if not step_list:
        logger.error(f"场景 {scene_name} 没有找到预定义的步骤")
        output = f"错误：场景 {scene_name} 没有找到预定义的步骤。"
        return {
            **state,
            "output": output,
            "error_message": "No predefined steps found",
            "history": state["history"] + [f"助手：{output}"]
        }
    
    logger.info(f"获取到预定义步骤: {step_list}")

    doc = "\n".join([f"{i+1}. {step}" for i, step in enumerate(step_list)])
    output = f"已获取到预定义的执行步骤：\n\n{doc}\n\n共 {len(step_list)} 步，请确认是否按此计划执行？若确认，请输入\"继续\"。"
    
    return {
        **state,
        "output": output,
        "origin_step_list": step_list,
        "step_list": None,
        "current_step": 0,
        "step_outputs": [],
        "step_results": [],
        "current_stage": "confirm_steps",  # 转到确认步骤阶段
        "history": state["history"] + [f"助手：{output}"]
    }


# 2.4 步骤确认节点
def confirm_steps(state: AgentState) -> AgentState:
    logger.info("开始进行场景步骤修改与合并....")
    text = state["user_input"].strip()
    
    # 暂时不使用LLM修改，用户输入“继续”则使用原始步骤
    step_list = state["origin_step_list"]
    
    output = f"根据用户要求，最终步骤为：\n{step_list}，共 {len(step_list)} 步。\n开始执行步骤..."
    print(output)
    return {
        **state,
        "step_list": step_list,
        "current_step": 0,
        "step_outputs": [],
        "step_results": [],
        "current_stage": "execute_step",
        "output": "",
        "history": state["history"] + [f"助手：{output}"]
    }


# 2.5 执行步骤Agent节点
async def execute_step(state: AgentState) -> AgentState:
    # 异步获取执行agent执行器
    agent_executor = await get_mcp_agent()

    # 如果无法获取Agent（例如MCP服务未启动），则进入错误处理流程
    if agent_executor is None:
        output = "无法连接到MCP服务，请确保 `mysql_mcp_server.py` 和 `tested_project_mcp_server.py` 正在运行。\n请输入“继续”重试，或输入“停止”终止流程。"
        i = state["current_step"]
        return {
            **state,
            "error_message": "MCP agent could not be initialized.",
            "pending_action": f"step_{i}_error", # 复用现有的错误处理流程
            "user_confirmed": None,
            "output": output,
            "history": state["history"] + [f"助手：{output}"]
        }

    i = state["current_step"]
    step = state["step_list"][i]
    retry_input = state.get("retry_payload")
    if retry_input is not None:
        step = retry_input
    
    logger.info(f"开始执行步骤{i + 1}: {step}")
    print(f"开始执行步骤{i + 1}: {step}")
    
    # --- 全局业务上下文注入 ---
    full_scene_context = state.get("selected_scene", {})
    scene_data = full_scene_context.get("data", {})
    
    # --- 动态构建针对当前步骤的指令 ---
    step_specific_instructions = ""
    # 步骤索引 i 来判断，比用文本匹配可靠
    if i == 0: # 步骤一
        step_specific_instructions = """
### 当前任务：准备测试数据
- **核心目标**: 安全地查询数据库，获取测试所需的前置数据。
### **严格执行步骤 (必须遵守)**:
1.  **执行数据库描述**:
    - **你的唯一指令**: 你 **必须** 调用 `run_sql_query` 工具，查询 `teller_info` 表的结构。
    - **工具输入示例**: `{"query": "DESCRIBE teller_info;"}`
2.  **执行数据查询**:
    - **你的唯一指令**: 在上一步成功获取表结构后，你 **必须** 调用 `run_sql_query` 工具，根据 `场景定义` 中的 `ssic_type` 和 `ssic_id` 查询 `teller_info` 表中的数据。
    - **工具输入示例**: `{"query": "SELECT * FROM teller_info WHERE ssic_type = '3' AND ssic_id = 'B234567(8)' LIMIT 1;"}` (请根据实际场景定义中的值替换 `ssic_type` 和 `ssic_id`)
3.  **保存测试数据**:
    - **你的唯一指令**: 在上一步成功查询到数据后，你 **必须** 调用 `update_state` 工具，将查询到的数据保存到状态中。
    - **工具输入示例**: `{"state_object": {"test_data": [<你从数据库查询到的数据>]}}`
- **禁止**: 在没有先执行 `DESCRIBE` 的情况下，直接执行 `SELECT` 查询。
- **重要提示**: 确保严格按照顺序执行上述工具调用。
"""
    elif i == 1: # 步骤二
        step_specific_instructions = """
### 当前任务：构造请求报文
- **核心目标**: 使用上一步从数据库查询到的 `test_data`，动态填充 `request_payload` 模板，生成最终的API请求报文。
### 数据源:
1.  **模板**: 上下文中的 `场景定义` -> `request_payload`。这是请求的基础结构。
2.  **真实数据**: 上下文中的 `test_data` -> **第一条记录** (`test_data[0]`)。这是要填充的数据。
### 当前任务：构造并保存API请求报文
- **核心目标**: 调用 `update_state` 工具来创建并保存下一步API调用所需的 `api_request_payload`。
- **你的唯一指令**: 你 **必须** 调用 `update_state` 工具一次。

### `update_state` 的参数构造规则 (必须严格遵守):
1.  **准备数据**:
    - **模板**: 从上下文的 `场景定义` -> `request_payload` 中获取。
    - **真实数据**: 从上下文的 `已获取的测试数据 (Test Data)` -> `test_data[0]` 中获取。

2.  **构建 `api_request_payload` 对象**:
    - 复制 `场景定义` 中的 `request_payload` 模板 (包含 url, method, headers, json_body)。
    - **修改 `json_body`**: 使用 `test_data[0]` 的值替换 `json_body` 中的占位符：
        - `json_body['ssicId']`   应被替换为 `test_data[0]['ssic_id']` 的值。
        - `json_body['username']` 应被替换为 `test_data[0]['username']` 的值。
        - `json_body['email']`    应被替换为 `test_data[0]['email']` 的值。
        - `json_body['phone']`    应被替换为 `test_data[0]['phone']` 的值。
    - **保持 `ssicType`**: 确保 `json_body['ssicType']` 的值与 `场景定义` 中指定的值一致。

3.  **调用工具**:
    - 将你构造好的、完整的 `api_request_payload` 对象包装起来。
    - 调用 `update_state`，其 `state_object` 参数必须是：`{{"api_request_payload": <你构造的完整请求报文>}}`
"""
    elif i == 2: # 步骤三
        step_specific_instructions = """
### 当前任务：执行API调用并保存结果
这是一个严格的顺序过程。你必须一步一步地执行。

**第一阶段：调用API**
1.  **检查前提条件**: 首先，你必须检查上下文中 `已构造的请求体 (API Request Payload)` 是否存在且不为 `null`。
2.  **决策**:
    - **如果 `api_request_payload` 缺失 (为 `null`)**: 你 **必须** 停止执行并输出一条错误消息，明确指出"无法执行API调用，因为上一步未能成功构造请求报文"。
    - **如果 `api_request_payload` 存在**: 继续执行下面的指令。
3.  **你的唯一任务**: 调用 `call_api` 工具。
4.  **输入**: **必须**使用上下文中已保存的、完整的 `api_request_payload` 作为 `call_api` 的参数。
5.  **行动**: 调用 `call_api`。然后，**你必须停止并等待工具返回的API响应**。

**第二阶段：保存响应**
1.  **触发条件**: 在你从 `call_api` 工具那里收到了一个JSON响应之后。
2.  **你的唯一任务**: 调用 `update_state` 工具。
3.  **输入**: 将 `call_api` 返回的**完整的、未经修改的**JSON响应，包装后作为 `update_state` 的参数。格式必须是: `{{"last_api_response": <完整的API响应>}}`。
4.  **行动**: 调用 `update_state`。

**绝对禁止**:
- 在 `api_request_payload` 为 `null` 时尝试调用 `call_api`。
- 在同一个思考步骤中同时调用 `call_api` 和 `update_state`。
"""
    elif i == 3: # 步骤四
        step_specific_instructions = """
### 当前任务：校验与断言
- **你的唯一目标**: 对比API响应和预期结果。
- **输入**: **必须**依赖上下文中的 `last_api_response` 和场景定义中的 `expected_response`。
- **断言规则**:
    1.  **HTTP状态码**: 验证API响应的HTTP状态码为 200。
    2.  **`return_code`**: 断言 `last_api_response.return_code` 为 '0'。
    3.  **可用余额变化**:
        - 获取交易前的 `usable_amount` (从 `test_data` 中获取)。
        - 查询交易后的 `usable_amount` (通过 `run_sql_query` 查询 `credit_card_account` 表，使用 `card_no` 作为条件)。
        - 计算预期扣款总额：`transfer_amount` (从 `request_payload.json_body` 获取) + `max(5, transfer_amount * 0.01)`。
        - 对比交易前后 `usable_amount` 的差值是否等于预期扣款总额。
- **最终输出**: **必须**调用 `update_state` 工具，以 `{{"assertion_result": {{"result": "成功/失败", "details": "..."}}}}` 的格式报告你的断言结论。
    - **示例调用**: `update_state` 工具的 `state_object` 参数应类似 `{{"assertion_result": {{"result": "成功", "details": "所有断言均通过，交易成功且扣款金额符合预期。"}}}}`
"""

    # --- 构建一个极简且聚焦的上下文和提示 ---
    input_prompt = f"""
**当前场景**: `{full_scene_context.get("name")}`
**当前步骤描述**: `{step}`

---
**上下文数据**:
- **场景定义 (Relevant parts)**: ```json
{json.dumps(scene_data, indent=2, ensure_ascii=False)}
```
- **已获取的测试数据 (Test Data)**: ```json
{json.dumps(state.get("test_data"), indent=2, ensure_ascii=False)}
```
- **已构造的请求体 (API Request Payload)**: ```json
{json.dumps(state.get("api_request_payload"), indent=2, ensure_ascii=False)}
```
- **上一步API响应 (Last API Response)**: ```json
{json.dumps(state.get("last_api_response"), indent=2, ensure_ascii=False)}
```
---
{step_specific_instructions}
"""

    contextual_input = { "input": input_prompt }

    try:
        response = await agent_executor.ainvoke(contextual_input)
        
        # 复制响应，以便修改 intermediate_steps
        processed_response = response.copy()
        
        # 处理 intermediate_steps，使其可序列化
        if "intermediate_steps" in processed_response and processed_response["intermediate_steps"]:
            serializable_intermediate_steps = []
            for action, result in processed_response["intermediate_steps"]:
                # 将 ToolAgentAction 转换为字典
                serializable_action = {
                    "tool": action.tool,
                    "tool_input": action.tool_input,
                    "log": action.log # 包含 log 字段
                }
                serializable_intermediate_steps.append([serializable_action, result])
            processed_response["intermediate_steps"] = serializable_intermediate_steps

        logger.info(f"DEBUG: Full AgentExecutor response: {json.dumps(processed_response, indent=2, ensure_ascii=False)}")

        # --- 透明化输出 ---
        summary_lines = []
        intermediate_steps = processed_response.get("intermediate_steps", [])
        if intermediate_steps:
            summary_lines.append("  - Agent 执行过程:")
            for action_dict, result in intermediate_steps:
                tool_name = action_dict["tool"]
                tool_input = action_dict["tool_input"]
                summary_lines.append(f"    - 调用工具: `{tool_name}`")
                # 尝试将 tool_input 转换为 JSON 字符串，如果不是字典或列表
                if isinstance(tool_input, (dict, list)):
                    summary_lines.append(f"    - 工具输入: {json.dumps(tool_input, ensure_ascii=False)}")
                else:
                    summary_lines.append(f"    - 工具输入: {repr(tool_input)}") # 使用 repr() 处理非 JSON 可序列化对象
                try:
                    # 确保 result 是字符串，然后尝试解析
                    if isinstance(result, str):
                        pretty_result = json.dumps(json.loads(result), ensure_ascii=False, indent=2)
                        summary_lines.append(f"    - 工具返回: \n{pretty_result}")
                    else:
                        summary_lines.append(f"    - 工具返回: {repr(result)}") # 使用 repr() 处理非字符串结果
                except (json.JSONDecodeError, TypeError):
                    summary_lines.append(f"    - 工具返回: {repr(result)}") # 捕获异常时也使用 repr()
        
        final_output = processed_response.get("output", "无最终输出。")
        summary_lines.append(f"  - Agent 最终结论: {final_output}")
        summary = "\n".join(summary_lines)
        print(summary)

        # --- 状态更新 ---
        new_state_updates = {}
        if intermediate_steps:
            logger.info("开始解析 intermediate_steps 以捕获状态更新...")
            for action_dict, result in intermediate_steps:
                logger.info(f"  - 正在检查工具: {action_dict['tool']}")
                if action_dict['tool'] == "update_state":
                    tool_input = action_dict['tool_input']
                    logger.info(f"    - 发现 'update_state' 调用，原始输入: {tool_input}")
                    
                    # 健壮性处理：tool_input 可能是字符串或字典
                    parsed_input = None
                    if isinstance(tool_input, str):
                        try:
                            parsed_input = json.loads(tool_input)
                        except json.JSONDecodeError:
                            logger.warning(f"      - 警告: 'update_state' 的字符串输入不是有效的JSON: {tool_input}")
                            continue
                    elif isinstance(tool_input, dict):
                        parsed_input = tool_input
                    else:
                        logger.warning(f"      - 警告: 'update_state' 的输入既不是字典也不是字符串: {type(tool_input)}")
                        continue

                    if isinstance(parsed_input, dict) and "state_object" in parsed_input:
                        state_update_data = parsed_input["state_object"]
                        if isinstance(state_update_data, dict):
                            logger.info(f"      - 成功提取状态更新: {state_update_data}")
                            new_state_updates.update(state_update_data)
                        else:
                            logger.warning(f"      - 警告: 'state_object' 的值不是一个字典: {state_update_data}")
                    else:
                        logger.warning(f"      - 警告: 'update_state' 的输入格式不正确，缺少 'state_object' 键: {parsed_input}")

        # 创建一个新状态字典，先复制旧状态，再应用捕获到的更新
        next_state = state.copy()
        next_state.update(new_state_updates)
        
        # 更新其他流程控制字段
        next_state.update({
            "current_step": state["current_step"] + 1,
            "output": final_output,
            "pending_action": None,
            "retry_payload": None,
            "step_outputs": state["step_outputs"] + [summary],
            "step_results": state.get("step_results", []) + [processed_response], # 保存处理后的响应
            "history": state["history"] + [f"Agent:\n{summary}\n\nAssistant:\n{final_output}"]
        })
        
        # 新增的最终状态诊断日志
        logger.info(f"步骤 {i + 1} 执行完毕，应用了 {len(new_state_updates)} 个状态更新。")
        logger.info(f"execute_step: new_state_updates: {new_state_updates}")
        logger.info(f"execute_step: next_state test_data: {next_state.get('test_data')}")
        logger.info(f"execute_step: next_state api_request_payload: {next_state.get('api_request_payload')}")
        logger.info(f"execute_step: next_state last_api_response: {next_state.get('last_api_response')}")
        logger.info(f"execute_step: next_state assertion_result: {next_state.get('assertion_result')}")
        
        return next_state

    except Exception as e:
        logger.error(f"步骤{i + 1} 执行时发生严重异常", exc_info=True)
        output = f"步骤{i + 1}：{step} 执行时发生异常：{repr(e)}。\n请输入“继续”或“停止”，或使用 参数=xxx 格式重试。"
        return {
            **state,
            "error_message": repr(e),
            "pending_action": f"step_{i}_error",
            "user_confirmed": None,
            "output": output,
            "history": state["history"] + [f"助手：{output}"]
        }


# 2.6 错误处理节点 
def handle_error(state: AgentState) -> AgentState:
    text = state["user_input"].strip()

    if "停止" in text:
        return {**state, "user_confirmed": False, "output": "已终止流程。", "pending_action": None}

    if "继续" in text or text.startswith("参数="):
        # 如果用户提供了新参数，它将被用作下一次重试的输入
        retry_payload = text.replace("参数=", "").strip() if "参数=" in text else None
        output_msg = "收到修复指令，准备重新执行失败步骤。"
        if retry_payload:
            output_msg = f"收到修复指令，准备使用新参数重试：{retry_payload}"
        
        return {
            **state,
            "user_confirmed": True, # 标记用户已确认，可以继续
            "retry_payload": retry_payload,
            "pending_action": None, # 清除pending_action，让router决定下一步
            "output": output_msg
        }
        
    return {
        **state,
        "user_confirmed": None, # 保持None，等待有效输入
        "output": "未识别的输入，请输入“继续”或“停止”，或使用 参数=xxx 重试。"
    }


# 2.7 结束节点
def finish(state: AgentState) -> AgentState:
    logger.info("结束")
    # 如果是从错误处理中选择“停止”而来的，则直接返回当前状态
    # （输出信息已在 handle_error 中设置）
    if state.get("user_confirmed") is False:
        return state

    # 否则，是正常流程结束
    output = "✅ 所有步骤执行完毕！\n\n"
    print(output)
    return {
        **state,
        "output": output
    }


# 2.8 路由节点 (简化版)
def router(state: AgentState) -> str:
    # 1. 如果有挂起的动作（如步骤失败），并且用户还未输入指令，则进入错误处理节点等待用户输入。
    if state.get("pending_action") and state.get("user_confirmed") is None:
        return "handle_error"

    # 2. 如果用户在错误处理节点输入了“停止”，则直接结束流程。
    if state.get("user_confirmed") is False:
        return "finish"

    # 3. 如果用户在错误处理节点输入了“继续”或带参数的指令，user_confirmed会变为True。
    #    此时应该清除pending_action，然后重新路由回execute_step进行重试。
    if state.get("user_confirmed") is True:
        # 重置确认状态，以防进入无限循环
        state["user_confirmed"] = None
        state["pending_action"] = None
        return "execute_step"

    # 4. 根据当前所处的阶段进行标准流程路由。
    current_stage = state.get("current_stage")
    if current_stage == "confirm_scene":
        return "confirm_scene"
    if current_stage == "retrieve_steps":
        return "retrieve_steps"
    if current_stage == "confirm_steps":
        return "confirm_steps"
    if current_stage == "execute_step":
        # 检查是否所有步骤都已执行完毕
        if state.get("current_step", 0) < len(state.get("step_list", [])):
            return "execute_step"
        else:
            return "finish" # 所有步骤完成，结束流程

    # 默认入口
    return "query_scene"


# 3. 构建图
def build_graph():
    logger.info("============构建状态图============")
    builder = StateGraph(AgentState)
    
    # 添加节点
    builder.add_node("query_scene", query_scene)
    builder.add_node("confirm_scene", confirm_scene)
    builder.add_node("retrieve_steps", retrieve_steps) # 获取预定义步骤节点
    builder.add_node("confirm_steps", confirm_steps)
    builder.add_node("execute_step", execute_step)
    builder.add_node("handle_error", handle_error)
    builder.add_node("finish", finish)
    
    # 设置条件入口点，使用 router 来决定从哪个节点开始
    builder.set_conditional_entry_point(router)
    
    # 所有节点执行完后都通过 router 来决定下一步
    builder.add_conditional_edges("query_scene", router)
    builder.add_conditional_edges("confirm_scene", router)
    builder.add_conditional_edges("retrieve_steps", router)
    builder.add_conditional_edges("confirm_steps", router)
    builder.add_conditional_edges("execute_step", router)
    builder.add_conditional_edges("handle_error", router)
    
    # 只有 finish 节点直接连接到 END
    builder.add_edge("finish", END)

    return builder.compile()


# --- 主程序运行逻辑 ---
async def main():

    state = {
        "user_input": "",
        "current_stage": "query_scene",
        "pending_action": None,
        "user_confirmed": None,
        "api_list": [],
        "selected_scene": None,
        "origin_step_list": [],
        "step_list": [],
        "current_step": 0,
        "step_outputs": [],
        "step_results": [],
        "error_message": None,
        "retry_payload": None,
        "output": "",
        "history": [],
        "api_request_payload": None,
        "test_data": None,
        "last_api_response": None,
        "assertion_result": None
    }
    
    # 步骤1：获取场景列表
    state = query_scene(state)
    print(f"🤖 {state['output']}")
    
    # 步骤2：用户选择场景
    while state.get("current_stage") == "confirm_scene":
        user_input = input("你：").strip()
        if user_input.lower() in ["退出", "exit", "quit", "q"]:
            print("再见！")
            return
        state["user_input"] = user_input
        state = confirm_scene(state)
        if state.get("output"):
            print(f"🤖 {state['output']}")
    
    # 步骤3：获取预定义步骤
    if state.get("current_stage") == "retrieve_steps":
        state = retrieve_steps(state)
        print(f"🤖 {state['output']}")
    
    # 步骤4：用户确认步骤
    while state.get("current_stage") == "confirm_steps":
        user_input = input("你：").strip()
        if user_input.lower() in ["退出", "exit", "quit", "q"]:
            print("再见！")
            return
        state["user_input"] = user_input
        state = confirm_steps(state)
        if state.get("output"):
            print(f"🤖 {state['output']}")
    
    # 步骤5：执行测试步骤
    while state.get("current_stage") == "execute_step" and state.get("current_step", 0) < len(state.get("step_list", [])):
        try:
            state = await execute_step(state)
            if state.get("output"):
                print(f"🤖 {state['output']}")
            
            # 处理错误情况
            while state.get("pending_action"):
                user_input = input("你：").strip()
                if user_input.lower() in ["退出", "exit", "quit", "q"]:
                    print("再见！")
                    return
                state["user_input"] = user_input
                state = handle_error(state)
                if state.get("output"):
                    print(f"🤖 {state['output']}")
                
                # 如果用户选择停止
                if state.get("user_confirmed") is False:
                    state = finish(state)
                    print(f"🤖 {state['output']}")
                    return
                
                # 如果用户选择继续，重新执行当前步骤
                if state.get("user_confirmed") is True:
                    state["user_confirmed"] = None
                    state["pending_action"] = None
                    break
        except Exception as e:
            print(f"执行步骤时发生异常：{e}")
            break
    
    # 步骤6：完成
    if state.get("current_step", 0) >= len(state.get("step_list", [])):
        state = finish(state)
        print(f"🤖 {state['output']}")


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n程序已由用户手动中断。再见！")
