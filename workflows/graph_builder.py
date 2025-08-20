from langgraph.graph import StateGraph, END
from langchain_core.prompts import ChatPromptTemplate
from agents.mcp_agent import get_mcp_agent
from models.dquestion import get_llm
from utils import logger
from utils.db_utils import DatabaseManager
from tools.rag_tools import query_scene_list, query_interface_details
from typing import TypedDict, List, Optional, Literal, Annotated, Sequence
from langchain_core.messages import SystemMessage, BaseMessage, HumanMessage, AIMessage
from langgraph.graph.message import add_messages
from langgraph.checkpoint.base import BaseCheckpointSaver
from prompts.workflow_prompts import STEP_1_PROMPT, STEP_2_PROMPT, STEP_3_PROMPT, STEP_4_PROMPT

from tools.logic_validator import validate_step_logic
import asyncio 
import json
import re
from datetime import datetime


class AgentState(TypedDict):
    user_input: str
    auto_continue: bool
    current_stage: Literal["query_scene","confirm_scene", "retrieve_steps", "confirm_steps", "execute_step", "finish"] 
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
    api_request_payload: Optional[dict]
    test_data: Optional[List[dict]]
    last_api_response: Optional[dict]
    assertion_result: Optional[dict]
    agent_process: Optional[str]
    messages: Annotated[Sequence[BaseMessage], add_messages]

def create_initial_state(user_input: str) -> AgentState:
    return AgentState(
        user_input=user_input, auto_continue=False, current_stage="query_scene",  
        pending_action=None, user_confirmed=None, api_list=[], selected_scene=None,
        origin_step_list=[], step_list=[], current_step=0, step_outputs=[],
        step_results=[], error_message=None, retry_payload=None, output="",
        api_request_payload=None, test_data=None, last_api_response=None,
        assertion_result=None, agent_process=None, messages=[HumanMessage(content=user_input)]
    )

async def query_scene(state: AgentState) -> AgentState:
    logger.info("开始获取场景列表.....")
    api_list = await query_scene_list(state["user_input"])
    logger.info(f"找到以下场景：{api_list}")

    if not api_list:
        output_json = {"type": "text", "content": "没有找到您描述的接口场景，请重新调整查询描述再试"}
    else:
        options = [{"key": str(i + 1), "description": s} for i, s in enumerate(api_list)]
        output_json = {
            "type": "scenario_selection", "content": "我找到了以下场景，请选择一个：",
            "options": options, "fallback_text": "若没有您需要的场景，请重新输入描述，建议您输入更详细的描述。"
        }
    
    output_str = json.dumps(output_json, ensure_ascii=False)
    return { **state, "api_list": api_list, "output": output_str, "current_stage": "confirm_scene", "messages": state["messages"] + [AIMessage(content=output_str)] }

def confirm_scene(state: AgentState) -> AgentState:
    logger.info("用户进行场景选择.....")
    text = state["user_input"].strip()
    
    # ✨ FIX: 使用更智能的解析逻辑，而不是简单的 isdigit()
    
    # 1. 尝试从 "我选择场景 X: ..." 格式中提取数字
    match = re.search(r"我选择场景\s+(\d+):", text)
    
    selected_index = -1
    if match:
        # 如果匹配成功，提取数字
        selected_index = int(match.group(1)) - 1
    elif text.isdigit():
        # 2. 如果不匹配，检查整个输入是否为纯数字
        selected_index = int(text) - 1

    # 如果 selected_index 保持为 -1，说明既不是格式化选择，也不是纯数字
    if selected_index == -1:
        # 3. 只有在以上两种情况都失败时，才认为是新的场景描述
        logger.info(f"输入 '{text}' 不被识别为场景选择，将作为新描述重新查询。")
        output_json = {"type": "text", "content": f"收到新的场景描述: {text}，正在重新查询相关场景..."}
        output_str = json.dumps(output_json, ensure_ascii=False)
        return { 
            **state, 
            "user_input": text, 
            "current_stage": "query_scene", 
            "selected_scene": None, 
            "api_list": [], 
            "output": output_str, 
            "auto_continue": True, 
            "messages": state["messages"] + [AIMessage(content=output_str)] 
        }

    # --- 如果成功解析出编号，执行选择逻辑 ---
    try:
        if not (0 <= selected_index < len(state["api_list"])):
            raise IndexError("用户选择的编号超出范围")
            
        selected_api_string = state["api_list"][selected_index]
        match = re.search(r"接口中文名:\s*(.+?),\s*场景名:\s*(.+)", selected_api_string.strip())
        
        if not match:
            raise ValueError(f"无法从 '{selected_api_string}' 解析场景")
        
        result_dict = {"接口中文名": match.group(1).strip(), "场景名": match.group(2).strip()}
        output_text = f"已选择场景：`{selected_api_string}`，开始查询场景相关信息..."
        output_json = {"type": "text", "content": output_text}
        output_str = json.dumps(output_json, ensure_ascii=False)
        
        return { 
            **state, 
            "selected_scene": result_dict, 
            "current_stage": "retrieve_steps", 
            "output": output_str, 
            "auto_continue": True, 
            "messages": state["messages"] + [AIMessage(content=output_str)] 
        }
        
    except (ValueError, IndexError) as e:
        logger.error(f"场景选择失败: {e}")
        output_json = {"type": "text", "content": "输入无效或编号超出范围，请重新输入有效编号。"}
        output_str = json.dumps(output_json, ensure_ascii=False)
        return { 
            **state, 
            "output": output_str, 
            "current_stage": "confirm_scene", 
            "auto_continue": False, 
            "messages": state["messages"] + [AIMessage(content=output_str)] 
        }
async def retrieve_steps(state: AgentState) -> AgentState:
    logger.info("开始进行场景步骤检索....")
    selected_scene = state["selected_scene"]
    selected_scene_data = await query_interface_details(selected_scene["接口中文名"], selected_scene["场景名"])
    selected_scene.update(selected_scene_data)
    step_list = selected_scene_data.get("steps", [])
    
    if not step_list:
        # 如果真的没有步骤，返回一个明确的文本消息
        output_json = {
            "type": "text", 
            "content": f"错误：场景 `{selected_scene.get('场景名', '未知')}` 没有找到任何预定义的步骤。"
        }
    else:
        # ✨ FIX: 构造一个完整的、前端友好的 step_confirmation 对象
        output_json = {
            "type": "step_confirmation",
            # 使用 "message" 键来传递标题，更加语义化
            "message": "请确认步骤：", 
            # (最关键的修复) 将原始的步骤列表数组传递给前端
            "steps": step_list,
            # 提供更结构化的按钮信息
            "actions": [
                {"key": "continue", "label": "继续", "type": "primary"}
            ],
            # (可选优化) 添加一条指导语
            "instruction": "您可以直接点击“继续”以执行以上步骤，或在输入框中修改/增加步骤后发送。"
        }

    output_str = json.dumps(output_json, ensure_ascii=False)
    return {
        **state, 
        "selected_scene": selected_scene, 
        "output": output_str, 
        "origin_step_list": step_list, 
        "current_stage": "confirm_steps", 
        "auto_continue": False, 
        "messages": state["messages"] + [AIMessage(content=output_str)]
    }
def confirm_steps(state: AgentState) -> AgentState:
    logger.info("开始进行场景步骤修改与合并....")
    text = state["user_input"].strip()
    
    if "继续" in text:
        step_list = state["origin_step_list"]
    else:
        template2 = """用户输入：{question}，原始内容{origin}。请仔细看用户输入内容，如果是对原始内容的追加，则结合用户输入和原始文本内容，将内容进行重新组织成步骤列表；如果是完整的步骤内容，则将完整的步骤整理后返回。
        例如，用户输入：步骤四、校验数据，原始内容：步骤一、获取数据\n步骤二、处理数据\n步骤三、输出结果，则最后应该返回：步骤一、获取数据\n步骤二、处理数据\n步骤三、输出结果\n步骤四、校验数据。
        要求：
        第一、按以上格式返回；
        第二、禁止追加不存在的内容，严格按照用户输入和原始内容进行整合。
        第三，只需要输出结果，不需要额外的描述。
        """
        prompt2 = ChatPromptTemplate.from_template(template2)
        steps_update_chain = prompt2 | get_llm()
        response = steps_update_chain.invoke({"question": text, "origin": state['origin_step_list']})
        step_list = [s.strip() for s in response.content.strip().split('\n') if s.strip()]
    
    result_text = "根据您的要求，最终步骤为：\n\n" + "\n".join(step_list) + f"\n\n共 {len(step_list)} 步。开始执行..."
    output_json = {"type": "text", "content": result_text}
    output_str = json.dumps(output_json, ensure_ascii=False)

    return { **state, "user_input": "", "step_list": step_list, "current_step": 0, "current_stage": "execute_step", "output": output_str, "auto_continue": True, "messages": state["messages"] + [AIMessage(content=output_str)] }


# 2.5 执行步骤-agent节点
async def execute_step(state: AgentState) -> AgentState:
    """
    执行测试计划中的单个步骤，使用MCP Agent，处理结果，并为前端返回标准化的JSON输出。
    """
    agent_executor = await get_mcp_agent()

    # 处理Agent服务不可用的情况
    if agent_executor is None:
        output_json = {
            "type": "text",
            "content": "无法连接到MCP服务，请确保所有MCP服务正在运行。\n请输入“继续”重试，或输入“停止”终止流程。",
            "error": True
        }
        output_str = json.dumps(output_json, ensure_ascii=False)
        i = state["current_step"]
        return {
            **state,
            "error_message": "MCP agent could not be initialized.",
            "pending_action": f"step_{i}_error",
            "output": output_str,
            "messages": state["messages"] + [AIMessage(content=output_str)]
        }
    
    i = state["current_step"]
    step = state["step_list"][i]
    retry_input = state.get("retry_payload")
    if retry_input is not None:
        step = retry_input
        
    logger.info(f"开始执行步骤 {i + 1}: {step}")
    
    scene_data = state.get("selected_scene", {})
    step_specific_instructions = ""
    if i == 0: step_specific_instructions = STEP_1_PROMPT
    elif i == 1: step_specific_instructions = STEP_2_PROMPT
    elif i == 2: step_specific_instructions = STEP_3_PROMPT
    elif i == 3: step_specific_instructions = STEP_4_PROMPT

    input_prompt = f"""
**当前场景**: `{scene_data.get("场景名")}`
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

        #logger.info(f"DEBUG: Full AgentExecutor response: {json.dumps(processed_response, indent=2, ensure_ascii=False)}")

        # --- 透明化输出 ---
        summary_lines = []
        intermediate_steps = processed_response.get("intermediate_steps", [])
        if intermediate_steps:
            summary_lines.append("- Agent 执行过程:")
            for action_dict, result in intermediate_steps:
                tool_name = action_dict["tool"]
                tool_input = action_dict["tool_input"]
                summary_lines.append(f"  - 调用工具: `{tool_name}`")
                # 尝试将 tool_input 转换为 JSON 字符串，如果不是字典或列表
                if isinstance(tool_input, (dict, list)):
                    summary_lines.append(f"  - 工具输入: {json.dumps(tool_input, ensure_ascii=False)}")
                else:
                    summary_lines.append(f"  - 工具输入: {repr(tool_input)}") # 使用 repr() 处理非 JSON 可序列化对象
                try:
                    # 确保 result 是字符串，然后尝试解析
                    if isinstance(result, str):
                        pretty_result = json.dumps(json.loads(result), ensure_ascii=False, indent=2)
                        summary_lines.append(f"  - 工具返回: \n{pretty_result}")
                    else:
                        summary_lines.append(f"  - 工具返回: {repr(result)}") # 使用 repr() 处理非字符串结果
                except (json.JSONDecodeError, TypeError):
                    summary_lines.append(f"  - 工具返回: {repr(result)}") # 捕获异常时也使用 repr()
        
        final_output = processed_response.get("output", "无最终输出。")
        summary_lines.append(f"- Agent 最终结论: {final_output}")
        summary = "\n".join(summary_lines)
        print(summary)
        output_json = { "type": "agent_result", "content": final_output, "agent_process": summary }
        output_str = json.dumps(output_json, ensure_ascii=False)
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
        
        # 日志修复：确保步骤2的日志显示最终报文
        # 在这里重新赋值 final_output，确保它包含完整的报文
        if i == 1 and "api_request_payload" in next_state:
            final_output = f"已成功构造API请求报文，最终报文如下：\n```json\n{json.dumps(next_state['api_request_payload'], indent=2, ensure_ascii=False)}\n```"
            print(final_output)
        

        # 创建分离的Agent执行过程信息和最终结论
        agent_process_content = f"Agent:\n{summary}"
        
        next_state.update({
            "current_step": state["current_step"] + 1,
            "output": output_str,  # 使用JSON格式的输出
            "pending_action": None,
            "retry_payload": None,
            "auto_continue": True,  # 关键：设置自动继续，确保下一个步骤能自动执行
            "step_outputs": state["step_outputs"] + [final_output],
            "step_results": state.get("step_results", []) + [processed_response],
            "agent_process": agent_process_content,  # 单独存储Agent执行过程
            "messages": [AIMessage(content=output_str)]  # 使用JSON格式的消息
        })

        # 逻辑验证：检查执行结果是否符合预期
        is_valid, validation_msg = await validate_step_logic(
            step_description=step,
            agent_final_output=final_output # 直接传递最终结论
        )
        
        if not is_valid:
            logger.warning(f"步骤 {i + 1} 逻辑验证失败: {validation_msg}")
            output = f"步骤 {i + 1}：{step} 执行结果不符合预期。\n诊断信息：{validation_msg}\n请输入“继续”重试，或输入“停止”终止流程。"
            output_json = {"type": "text", "content": output, "error": True}
            output_str = json.dumps(output_json, ensure_ascii=False)
            # 返回错误状态，等待用户决策
            return {
            **state, # 返回原始 state，不保存此次失败的执行结果
            "error_message": f"逻辑验证失败: {validation_msg}",
            "pending_action": f"step_{i}_logic_error",
            "user_confirmed": None,
            "auto_continue": False,  # 发生错误时停止自动继续
            "output": output_str,
            "messages": [AIMessage(content=output_str)]
        }
        
        
        
        print(f'step_outputs : {next_state["step_outputs"]}')
        return next_state

    except Exception as e:
        # 是不是要在这里加诊断意见？
        logger.error(f"步骤{i + 1} 执行时发生严重异常", exc_info=True)
        output = f"步骤{i + 1}：{step} 执行失败：{str(e)}。请输入“继续”或“停止”，或使用 参数=xxx 格式重试。"
        output_json = {"type": "text", "content": output, "error": True}
        output_str = json.dumps(output_json, ensure_ascii=False)
        return {
            **state,
            "error_message": str(e),
            "pending_action": f"step_{i}_error",
            "user_confirmed": None,
            "output": output_str,
            "messages": [AIMessage(content=output_str)],
            "auto_continue": False, # 发生异常时，必须停止等待用户输入
        }


# 2.6 错误诊断建议节点（是否要查数据库）
# template2 = """你的工作是根据输入的错误信息，对这个错误进行分析和诊断，并给出一个建议，让用户按照这个建议进行修复。
# 不要试图疯狂猜测，在你能够辨别所有信息后，调用相关工具。
# """

def handle_error(state: AgentState) -> AgentState:
    text = state["user_input"].strip()
    logger.info(f"进入错误处理handle_error: {text}")
    
    # 用户选择停止
    if "停止" in text:
        output_text = "当前测试流程已由用户终止。请选择下一个场景或输入新的查询描述。"
        output_json = {"type": "text", "content": output_text}
        output_str = json.dumps(output_json, ensure_ascii=False)
        # 更新状态以准备选择新场景
        return {
            **state, 
            "user_confirmed": False, 
            "pending_action": None, 
            "output": output_str, 
            "auto_continue": False,
            "current_stage": "query_scene", # 重置为查询场景阶段
            "selected_scene": None, # 清除已选择的场景
            "origin_step_list": [], # 清除原始步骤列表
            "step_list": [], # 清除最终步骤列表
            "current_step": 0, # 重置当前步骤
            "step_outputs": [], # 清除步骤输出
            "step_results": [], # 清除步骤结果
            "error_message": None, # 清除错误信息
            "retry_payload": None, # 清除重试参数
            "messages": state["messages"] + [AIMessage(content=output_str)]
        }
    
    # 用户选择继续或使用新参数重试
    if "继续" in text or text.startswith("参数="):
        retry_payload = text.replace("参数=", "").strip() if "参数=" in text else None
        output_json = {"type": "text", "content": "收到修复指令，正在重试..."}
        output_str = json.dumps(output_json, ensure_ascii=False)
        # 准备重试，清除错误状态并设置自动继续
        return {
            **state,
            "user_confirmed": None,      # 重置确认状态
            "pending_action": None,      # 清除挂起动作，以便路由可以继续
            "error_message": None,       # 清除错误信息
            "output": output_str,        # 向用户显示我们正在重试
            "auto_continue": True,       # 设置自动继续信号
            "retry_payload": retry_payload,
            "messages": state["messages"] + [AIMessage(content=output_str)]
        }
    
    # 如果输入无法识别，保持在错误处理状态，并提示用户
    output_text = "请输入\"继续\"或\"停止\"，或使用 `参数=xxx` 格式提供新的指令重试。"
    output_json = {"type": "text", "content": output_text}
    output_str = json.dumps(output_json, ensure_ascii=False)
    return {
        **state,
        "user_confirmed": None,
        "output": output_str,
        "auto_continue": False, # 保持暂停，等待有效输入
        "messages": state["messages"] + [AIMessage(content=output_str)]
    }

def finish(state: AgentState) -> AgentState:
    logger.info("结束")
    step_outputs = state.get("step_outputs", [])
    step_list = state.get("step_list", [])
    
    # 创建执行摘要
    summary = "\n".join(step_outputs)
    output_text = "✅ 所有步骤执行完毕，执行摘要：\n\n" + summary
    
    # 创建包含步骤结论和执行摘要的JSON输出
    output_json = {
        "type": "execution_summary", 
        "stepResults": step_outputs,
        "finalSummary": output_text
    }
    output_str = json.dumps(output_json, ensure_ascii=False)
    
    return { 
        **state, 
        "output": output_str, 
        "current_stage": "finish", 
        "messages": state["messages"] + [AIMessage(content=output_str)] 
    }

# ----------------------
# 2.8 构建条件入口-router
# 进入--查询场景
# 若挂起动作存在且用户确认为空，则进入错误处理节点
# 若当前阶段-确认场景，且已选择的场景存在，则进入检索步骤节点，否则执行确认场景节点-进行场景确认
# 若当前阶段-检索步骤，且原始检索结果存在，则进入确认步骤节点，否则进入检索步骤节点-进行步骤检索
# 若当前阶段-确认步骤，且场景步骤结果存在，则进入执行步骤节点，否则进入确认步骤节点-进行步骤确认
# 若当前阶段-执行步骤，且执行步骤全部完成，则进入结束节点，否则进入执行步骤节点-进行下一步步骤执行

def router(state: AgentState) -> str:
    # If there's a pending action and the user hasn't confirmed, handle the error
    if state.get("pending_action") and state.get("user_confirmed") is None:
        return "handle_error"
    
    # Route based on the current stage
    current_stage = state.get("current_stage")

    if current_stage == "confirm_scene":
        if state.get("selected_scene"):
            return "retrieve_steps"
        return "confirm_scene"
    
    if current_stage == "retrieve_steps":
        # After retrieving steps, the next logical step is to wait for user confirmation
        return "confirm_steps"

    if current_stage == "confirm_steps":
        # ✨ THE KEY FIX: Check if step_list is truthy (non-empty)
        # This correctly treats an empty list [] as False
        if state.get("step_list"):  
            return "execute_step"
        return "confirm_steps"
    
    if current_stage == "execute_step":
        step_list = state.get("step_list", [])
        current_step = state.get("current_step", 0)
        if current_step < len(step_list):
            return "execute_step"
        else:
            return "finish"
    
    # Default entry point
    return "query_scene"

async def route_after_confirm_scene(state: AgentState) -> str:
    """
    根据 confirm_scene 节点的结果进行路由。
    - 如果用户输入了新描述，则返回 'query_scene'。
    - 如果用户选择了有效的场景，则返回 'retrieve_steps'。
    """
    if state.get("current_stage") == "query_scene":
        logger.info("用户提供了新的场景描述，将路由到 'query_scene'。")
        return "query_scene"
    else:
        logger.info("用户已选择场景，将路由到 'retrieve_steps'。")
        return "retrieve_steps"
    
# 3. 构建图
async def build_graph(checkpointer: BaseCheckpointSaver):
    logger.info("============构建状态图============")
    # 构建状态图
    builder = StateGraph(AgentState)
    # 设置节点
    builder.add_node("query_scene", query_scene)  # 获取接口列表
    builder.add_node("confirm_scene", confirm_scene)  # 选择接口节点
    builder.add_node("retrieve_steps", retrieve_steps)  # 检索步骤节点
    builder.add_node("confirm_steps", confirm_steps)  # 用户确认步骤节点
    builder.add_node("execute_step", execute_step)  # 执行步骤节点
    builder.add_node("handle_error", handle_error)  # 错误处理节点
    builder.add_node("finish", finish)  # 完成节点
    # 设置条件入口-路由
    builder.set_conditional_entry_point(router)
    #builder.add_edge("confirm_scene", "retrieve_steps")
    
    builder.add_conditional_edges(
        "confirm_scene",
        route_after_confirm_scene,
        {
            "query_scene": "query_scene",
            "retrieve_steps": "retrieve_steps"
        }
    )
    
    builder.add_edge("confirm_steps", "execute_step")
    
    # 重要：添加execute_step到自己的边，通过router条件控制
    builder.add_conditional_edges(
        "execute_step",
        router,  # 使用router函数决定下一步
        {
            "execute_step": "execute_step",  # 继续执行下一步
            "finish": "finish",              # 完成所有步骤
            "handle_error": "handle_error"   # 处理错误
        }
    )
    
    # 其他边连接
    builder.add_conditional_edges(
        "handle_error",
        router,
        {
            "execute_step": "execute_step",
            "query_scene": "query_scene"
        }
    )
    
    builder.add_edge("finish", END)

    # 编译图
    compiler = builder.compile(checkpointer=checkpointer)
    logger.info("图创建成功并传入checkpointer")
    return compiler


async def main():
   #测试图是否能编译
    db_manager = DatabaseManager()
    await db_manager.initialize()
    checkpointer = db_manager.get_checkpointer()
    work_graph = await build_graph(checkpointer=checkpointer)
    # state = {
    #     "user_input": "",
    #     "current_stage": "choose_scene",
    #     "pending_action": None,
    #     "user_confirmed": None,
    #     "api_list": [],
    #     "selected_scene": None,
    #     "origin_step_list": [],
    #     "step_list": [],
    #     "current_step": 0,
    #     "step_outputs": [],
    #     "step_results": [],
    #     "error_message": None,
    #     "retry_payload": None,
    #     "output": "",
    #     "history": []
    # }
    # # 您的原始状态和循环逻辑现在都在这个异步函数内部
    # config = {"configurable": {"thread_id": "1234"}} # 别忘了 LangGraph 需要的 config
    
    # while True:
    #     if state.get("output"): # 使用 .get() 更安全
    #         print(f"\n🤖 {state['output']}")

    #     if "执行完毕" in state.get("output", ""):
    #         break

    #     user_input = input("你：").strip()
    #     if user_input.lower() in ["退出", "exit", "quit","q"]:
    #         print("再见！")
    #         break
            
    #     state["user_input"] = user_input
        
    #     # 现在 await 在 async def 函数内部，这是完全正确的
    #     state = await compiler.ainvoke(state, config)

# 3. 在 if __name__ == '__main__': 中，只做一件事：启动异步事件循环
if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n程序被用户中断。")