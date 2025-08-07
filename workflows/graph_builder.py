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
from tools.payload_utils import _replace_datetime_placeholders, _remove_empty_fields
from tools.logic_validator import validate_step_logic
import asyncio 
import json
import re
from datetime import datetime


class AgentState(TypedDict):
    user_input: str
    auto_continue: bool # 新增字段，用于控制是否自动继续
    current_stage: Literal["query_scene","confirm_scene", "retrieve_steps", "confirm_steps", "execute_step"] 
    pending_action: Optional[str]  # 挂起的动作
    user_confirmed: Optional[bool]  # 用户是否确认
    api_list: List[str]  # 接口场景列表
    selected_scene: dict  # 所选择的接口场景
    origin_step_list: List[str]  # 原始步骤列表
    step_list: List[str]  # 最终步骤列表
    current_step: int  # 当前步骤
    step_outputs: List[str]  # 步骤输出
    step_results: List[dict]  # 步骤结果
    error_message: Optional[str]  # 错误信息
    retry_payload: Optional[str]  # 重试的参数
    output: str  # 输出结果，用来标记本次的结束
    api_request_payload: Optional[dict] # API请求参数
    test_data: Optional[List[dict]]  # 测试数据
    last_api_response: Optional[dict] # API返回的参数
    assertion_result: Optional[dict] # 断言结果
    messages: Annotated[Sequence[BaseMessage], add_messages] # 消息

def create_initial_state(user_input: str) -> AgentState:
    """
    为新对话创建一个完整且符合AgentState规范的初始状态。
    这是确保图能够正确启动的关键。
    """
    # 这个函数返回一个字典，其中包含了AgentState所需的所有键，并赋予它们初始的“零值”。
    return AgentState(
        # 核心输入
        user_input=user_input,
        auto_continue=False,
        current_stage="query_scene",  
        pending_action=None,
        user_confirmed=None,
        api_list=[],
        selected_scene=None,
        origin_step_list=[],
        step_list=[],
        current_step=0,
        step_outputs=[],
        step_results=[],
        error_message=None,
        retry_payload=None,
        output="",
        api_request_payload=None,
        test_data=None,
        last_api_response=None,
        assertion_result=None,
        messages=[HumanMessage(content=user_input)]
    )

async def query_scene(state: AgentState) -> AgentState:
    """
    根据用户输入（state里获取），调用RAG工具检索知识库，获取对应的接口-场景列表
    """
    logger.info("开始获取场景列表.....")
    api_list = await query_scene_list(state["user_input"])
    # api_list = ["接口名:统一认证查询接口, 场景: 测试用户登陆", "接口名：信用卡消费，场景：准贷记卡消费"]
    logger.info(f"找到以下场景：{api_list}")

    if api_list == None or len(api_list) == 0:
        output = "没有找到您描述的接口场景，请重新调整查询描述再试"
        return {
            **state,
            "output": output,
            "messages": [AIMessage(content=output)]
        }
    else:
        state["api_list"] = api_list
        output = "我找到以下场景，请输入编号确认：\n" + \
             "\n".join([f"{i + 1}. {s}" for i, s in enumerate(api_list)]) + \
             "\n\n若没有您需要的场景，请重新输入描述，建议您输入更详细的描述。"
    
        return {
            **state,
            "output": output,
            "current_stage": "confirm_scene",
            "messages": [AIMessage(content=output)]
        }

def confirm_scene(state: AgentState) -> AgentState:
    """
    用于与用户交互，用户选择并确认接口-场景；
    若没有用户需要的场景，则重新输入描述。
    """
    logger.info("用户进行场景选择.....")
    text = state["user_input"].strip()
    try:
        idx = int(text) - 1
        
        if idx < 0 or idx >= len(state["api_list"]):
            raise IndexError("用户选择的编号超出范围")
            
        selected_api_string = state["api_list"][idx]
        
        # 从字符串中解析接口名和场景名
        match = re.search(r"接口中文名:\s*(.+?),\s*场景名:\s*(.+)", selected_api_string.strip())
        if not match:
            raise ValueError(f"无法从 '{selected_api_string}' 解析场景")
        
        interface_name = match.group(1).strip()
        scenario_name = match.group(2).strip()
        
        result_dict = {"接口中文名": interface_name, "场景名": scenario_name}
        print("转换后的字典:", result_dict)
        
        output = f"已选择场景：{result_dict}，开始查询场景相关信息，获取场景执行步骤..."
        print(output)
        
        output = f"已选择场景：{result_dict}，开始查询场景相关信息，获取场景执行步骤..."
        print(output) # Keep this print for immediate feedback
        return {
            **state,
            "selected_scene": result_dict,
            "origin_step_list": None,
            "step_list": None,
            "current_step": 0,
            "step_outputs": [],
            "step_results": [],
            "current_stage": "retrieve_steps",
            "output": output, # 确保 output 是一个字符串
            "auto_continue": True, # 设置自动继续信号
            "messages": [AIMessage(content=output)]
        }
    except (ValueError, IndexError) as e:
        logger.error(f"场景选择失败: {e}")
        output = "输入无效或编号超出范围，请重新输入有效编号。"
        return {
            **state,
            "output": output,
            "messages": [AIMessage(content=output)]
        }
    except:
        print(f"用户没有按正常方式输入，请重新输入描述。")
        output = f"用户没有按正常方式输入，请重新输入描述。您输入的是: {text}"
        return {
            **state,
            "user_input": text,
            "output": output,
            "current_stage": "query_scene",
            "messages": [AIMessage(content=output)]
        }

async def retrieve_steps(state: AgentState) -> AgentState:
    """
    获取特定场景相关信息，保存在state中，并返回步骤列表
    """
    logger.info("开始进行场景步骤检索....")
    selected_scene = state["selected_scene"]
    selected_scene_data = await query_interface_details(selected_scene["接口中文名"], selected_scene["场景名"])
    print(f"selected_scene_data: {selected_scene_data}")
    selected_scene.update(selected_scene_data)
    step_list = selected_scene_data["steps"]
    
    if not step_list:
        logger.error(f"场景 {selected_scene} 没有找到预定义的步骤")
        output = f"错误：场景 {selected_scene} 没有找到预定义的步骤。"
        return {
            **state,
            "output": output,
            "error_message": "No predefined steps found",
            "messages": [AIMessage(content=output)]
        }
        
    logger.info(f"获取到步骤: {step_list}")
    result = "\n".join([s for i,s in enumerate(step_list)])
    output = f"已获取到步骤：\n{result}\n\n请确认是否需要修改，若无需修改，请输入“继续”；若需要修改，请按当前格式进行修改和追加...\n"
    return {
        **state,
        "selected_scene": selected_scene,
        "output": output,
        "origin_step_list": step_list, # TODO：可以不需要了
        "step_list": None,
        "current_stage": "confirm_steps",
        "auto_continue": False, # 确保在确认步骤前暂停，等待用户输入
        "messages": [AIMessage(content=output)]
    }
    # TODO: 如果没查到的处理逻辑

def confirm_steps(state: AgentState) -> AgentState:
    """
    用于与用户交互，用户确认接口场景的步骤列表；若有需要修改的步骤，则进行修改和追加；若无修改，则返回原步骤列表。
    """
    logger.info("开始进行场景步骤修改与合并....")
    text = state["user_input"].strip()
    # 判断用户的输入
    if "继续" in text:
        step_list = state["origin_step_list"]
    else:
        # 调用大模型组织结果
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
        print(response.content)
        content = response.content.strip()
        # 假设传来的是字符串，需要转成list
        step_list = [step  for step in content.split('\n')]
        print(f"修改后的步骤列表为：{step_list}")
    
    result = "\n".join([s for i,s in enumerate(step_list)])
    output = f"根据用户要求，最终步骤为：\n{result}，共 {len(step_list)} 步。\n\n开始执行步骤..."
    print(output)
    return {
        **state,
        "step_list": step_list,
        "current_step": 0,
        "step_outputs": [],
        "step_results": [],
        "current_stage": "execute_step",
        "output": output, # 确保 output 是一个字符串
        "auto_continue": True, # 设置自动继续信号
        "messages": [AIMessage(content=output)]
    }


# 2.5 执行步骤-agent节点
async def execute_step(state: AgentState) -> AgentState:
    # 异步获取执行agent执行器
    agent_executor = await get_mcp_agent()

    # 如果无法获取Agent（例如MCP服务未启动），则进入错误处理流程
    if agent_executor is None:
        output = "无法连接到MCP服务，请确保所有MCP服务正在运行。\n请输入“继续”重试，或输入“停止”终止流程。"
        i = state["current_step"]
        return {
            **state,
            "error_message": "MCP agent could not be initialized.",
            "pending_action": f"step_{i}_error", # 复用现有的错误处理流程
            "user_confirmed": None,
            "output": output,
            "messages": [AIMessage(content=output)]
        }
    
    i = state["current_step"]
    step = state["step_list"][i]
    retry_input = state.get("retry_payload")
    if retry_input is not None:
        step = retry_input
    # 如果retry_input不为空，则用retry_input替代step,成功后清空
    logger.info(f"开始执行步骤{i + 1}: {step}")
    print(f"开始执行步骤{i + 1}: {step}")
    
    # --- 全局业务上下文注入 ---
    # full_scene_context = state.get("selected_scene", {})
    # scene_data = full_scene_context.get("data", {})
    scene_data = state.get("selected_scene", {})
    print(f"scene_data: {scene_data}")
    # --- 动态构建针对当前步骤的指令 ---
    step_specific_instructions = ""
    # 步骤索引 i 来判断，比用文本匹配可靠
    if i == 0: # 步骤一
        step_specific_instructions = STEP_1_PROMPT
    elif i == 1: # 步骤二
        step_specific_instructions = STEP_2_PROMPT
    elif i == 2: # 步骤三
        step_specific_instructions = STEP_3_PROMPT
    elif i == 3: # 步骤四
        step_specific_instructions = STEP_4_PROMPT

    # --- 构建一个极简且聚焦的上下文和提示 ---
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

        # --- **关键修复：自动填充并清理报文** ---
        if "api_request_payload" in new_state_updates:
            now = datetime.now()
            # 1. 递归替换日期和时间占位符
            payload = _replace_datetime_placeholders(
                new_state_updates["api_request_payload"], now
            )

            # 2. 递归移除所有空值字段 (空字符串, 空列表, 空字典)
            payload = _remove_empty_fields(payload)
            logger.info("清理报文: 已移除所有空值字段。")
            
            new_state_updates["api_request_payload"] = payload

        # 创建一个新状态字典，先复制旧状态，再应用捕获到的更新
        next_state = state.copy()
        next_state.update(new_state_updates)
        
        # 日志修复：确保步骤2的日志显示最终报文
        # 在这里重新赋值 final_output，确保它包含完整的报文
        if i == 1 and "api_request_payload" in next_state:
            final_output = f"已成功构造API请求报文，最终报文如下：\n```json\n{json.dumps(next_state['api_request_payload'], indent=2, ensure_ascii=False)}\n```"
            print(final_output)
        

        next_state.update({
            "current_step": state["current_step"] + 1,
            "output": final_output, # 使用更新后的 final_output
            "pending_action": None,
            "retry_payload": None,
            "step_outputs": state["step_outputs"] + [final_output], # 使用更新后的 final_output
            "step_results": state.get("step_results", []) + [processed_response], # 保存处理后的响应
            "messages": [AIMessage(content=f"Agent:\n{summary}\n\nAssistant:\n{final_output}")] # 使用更新后的 final_output
            # "history": state["history"] + [f"Agent:\n{summary}\n\nAssistant:\n{final_output}"]
        })

        # 逻辑验证：检查执行结果是否符合预期
        is_valid, validation_msg = await validate_step_logic(
            step_description=step,
            agent_final_output=final_output # 直接传递最终结论
        )
        
        if not is_valid:
            logger.warning(f"步骤 {i + 1} 逻辑验证失败: {validation_msg}")
            output = f"步骤 {i + 1}：{step} 执行结果不符合预期。\n诊断信息：{validation_msg}\n请输入“继续”重试，或输入“停止”终止流程。"
            # 返回错误状态，等待用户决策
            return {
                **state, # 返回原始 state，不保存此次失败的执行结果
                "error_message": f"逻辑验证失败: {validation_msg}",
                "pending_action": f"step_{i}_logic_error", # 新的挂起动作类型
                "user_confirmed": None,
                "output": output,
                "messages": [AIMessage(content=output)]
            }
        
        # 新增的最终状态诊断日志
        # logger.info(f"步骤 {i + 1} 执行完毕，应用了 {len(new_state_updates)} 个状态更新。")
        # logger.info(f"execute_step: new_state_updates: {new_state_updates}")
        # logger.info(f"execute_step: next_state test_data: {next_state.get('test_data')}")
        # logger.info(f"execute_step: next_state api_request_payload: {next_state.get('api_request_payload')}")
        # logger.info(f"execute_step: next_state last_api_response: {next_state.get('last_api_response')}")
        # logger.info(f"execute_step: next_state assertion_result: {next_state.get('assertion_result')}")
        
        print(f'step_outputs : {next_state["step_outputs"]}')
        return next_state

    except Exception as e:
        # 是不是要在这里加诊断意见？
        logger.error(f"步骤{i + 1} 执行时发生严重异常", exc_info=True)
        output = f"步骤{i + 1}：{step} 执行失败：{str(e)}。请输入“继续”或“停止”，或使用 参数=xxx 格式重试。"
        return {
            **state,
            "error_message": str(e),
            "pending_action": f"step_{i}_error",
            "user_confirmed": None,
            "output": output,
            "messages": [AIMessage(content=output)]
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
        output = "当前测试流程已由用户终止。请选择下一个场景或输入新的查询描述。"
        # 更新状态以准备选择新场景
        return {
            **state, 
            "user_confirmed": False, 
            "pending_action": None, 
            "output": output, 
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
            "messages": [AIMessage(content=output)]
        }

    # 用户选择继续或使用新参数重试
    if "继续" in text or text.startswith("参数="):
        retry_payload = text.replace("参数=", "").strip() if "参数=" in text else None
        output = "收到修复指令，正在重试..."
        # 准备重试，清除错误状态并设置自动继续
        return {
            **state,
            "user_confirmed": None,      # 重置确认状态
            "pending_action": None,      # 清除挂起动作，以便路由可以继续
            "error_message": None,       # 清除错误信息
            "output": output,            # 向用户显示我们正在重试
            "auto_continue": True,       # 设置自动继续信号
            "retry_payload": retry_payload,
            "messages": [AIMessage(content=output)]
        }
    
    # 如果输入无法识别，保持在错误处理状态，并提示用户
    output = "请输入“继续”或“停止”，或使用 `参数=xxx` 格式提供新的指令重试。"
    return {
        **state,
        "user_confirmed": None,
        "output": output,
        "auto_continue": False, # 保持暂停，等待有效输入
        "messages": [AIMessage(content=output)]
    }


# 2.7 结束节点--对外输出
def finish(state: AgentState) -> AgentState:
    logger.info("结束")
    summary = "\n".join(state["step_outputs"])
    output = "✅ 所有步骤执行完毕，执行摘要：\n\n" + summary
    print(output)
    return {
        **state,
        "output": output,
        "current_stage": "finish",
        "messages": [AIMessage(content=output)]
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
    if state["pending_action"] and state["user_confirmed"] is None:
        return "handle_error"
    if state["current_stage"] == "confirm_scene":
        if state["selected_scene"] is not None:
            return "retrieve_steps"
        return "confirm_scene"
    if state["current_stage"] == "retrieve_steps":
        if state["origin_step_list"] is not None:
            return "confirm_steps"
        return "retrieve_steps"
    if state["current_stage"] == "confirm_steps":
        if state["step_list"] is not None:
            return "execute_step"
        return "confirm_steps"
    if state["current_stage"] == "execute_step":
        if state["current_step"] < len(state["step_list"]):
            return "execute_step"
        else:
            return "finish"
    return "query_scene"


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
    # 设置边
    # 当场景确认后，不要停止，立即去检索步骤
    builder.add_edge("confirm_scene", "retrieve_steps")
    # 当步骤确认后，不要停止，立即去执行第一步
    builder.add_edge("confirm_steps", "execute_step")
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
