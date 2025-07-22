import sys
import os
import json
import asyncio
import re
from typing import TypedDict, List, Optional, Literal

from langgraph.graph import StateGraph, END
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import SystemMessage, HumanMessage

from agents.mcp_agent import get_mcp_agent
from models.dquestion import get_llm
from utils import logger


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
    current_request_params: Optional[dict] #请求参数
    last_api_response: Optional[dict]
    api_request_payload: Optional[dict]


# --- 全局配置信息 --- 
# 接口信息 目前硬编码。。
API_INFO = {
    "name": "UniformTeller.qryTellerInfo",
    "chinese_name": "统一认证用户信息查询",
    "url": "http://localhost:8080/api/aam/uniformteller/qrytellerInfo/V1",
    "method": "POST",
    "headers": {
        "X-Request-App": "F-CCPS",
        "X-Request-Id": "2010434"
    }
}

# 测试场景 
TEST_SCENARIOS = {
    "统一认证用户信息查询 - 场景分支1：验证统一认证号分支": {
        "description": "测试 `ssicType` 为 \"1\" (统一认证号) 的认证结果。",
        "given": "数据库和API服务已就绪。",
        "request_body": {
            "ssicType": "1",
            "ssicId": "123456789",
            "username": "张三",
            "email": "zhangsan@example.com",
            "phone": "13800138001",
            "biz_content": {
                "serviceName": "AAM",
                "randomKey": "smxxxxxxxxsm4",
                "timestamp": "2019-07-01 09:01:01"
            }
        },
        "expected_response": {
            "data": {
                "field1": "统一认证用户-123456789",
                "field2": {"sub_field1": 0, "sub_field2": False},
                "field3": "服务站点: 总行"
            },
            "return_code": "0",
            "return_msg": "请求处理成功"
        },
        "steps": [
            "步骤一、获取接口所需的前置数据",
            "步骤二、准备统一认证号分支请求参数",
            "步骤三、调用UniformTeller.qryTellerInfo接口",
            "步骤四、验证响应状态码为200",
            "步骤五、验证响应体符合统一认证号分支预期"
        ]
    },
    "统一认证用户信息查询 - 场景分支2：验证身份证信息分支": {
        "description": "测试 `ssicType` 为 \"2\" (身份证) 的认证结果。",
        "given": "数据库和API服务已就绪。",
        "request_body": {
            "ssicType": "2",
            "ssicId": "110101199001011234",
            "username": "王五",
            "email": "wangwu@example.com",
            "phone": "13800138003",
            "biz_content": {
                "serviceName": "AAM",
                "randomKey": "smxxxxxxxxsm4",
                "timestamp": "2019-07-01 09:01:01"
            }
        },
        "expected_response": {
            "data": {
                "field1": "身份证用户-110101199001011234",
                "field2": {"sub_field1": 0, "sub_field2": False},
                "field3": "服务站点: 支行"
            },
            "return_code": "0",
            "return_msg": "请求处理成功"
        },
        "steps": [
            "步骤一、获取接口所需的前置数据",
            "步骤二、准备身份证信息分支请求参数",
            "步骤三、调用UniformTeller.qryTellerInfo接口",
            "步骤四、验证响应状态码为200",
            "步骤五、验证响应体符合身份证信息分支预期"
        ]
    },
    "统一认证用户信息查询 - 场景分支3：验证香港身份证分支": {
        "description": "测试 `ssicType` 为 \"3\" (香港身份证) 的认证结果。",
        "given": "数据库和API服务已就绪。",
        "request_body": {
            "ssicType": "3",
            "ssicId": "B234567(8)",
            "username": "刘八",
            "email": "liuba@example.com",
            "phone": "+8613812345678",
            "biz_content": {
                "serviceName": "AAM",
                "randomKey": "smxxxxxxxxsm4",
                "timestamp": "2025-07-15 11:03:46"
            }
        },
        "expected_response": {
            "data": {
                "field1": "香港身份证用户-B234567(8)",
                "field2": {"sub_field1": 0, "sub_field2": False},
                "field3": "服务站点: 香港支行"
            },
            "return_code": "0",
            "return_msg": "请求处理成功"
        },
        "steps": [
            "步骤一、获取接口所需的前置数据",
            "步骤二、准备香港身份证分支请求参数",
            "步骤三、调用UniformTeller.qryTellerInfo接口",
            "步骤四、验证响应状态码为200",
            "步骤五、验证响应体符合香港身份证分支预期"
        ]
    }
}


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


# 2.3 获取执行步骤节点
def retrieve_steps(state: AgentState) -> AgentState:
    logger.info("开始进行场景步骤检索....")
    # 返回通用步骤，这与 execute_step 中的逻辑分支对应
    step_list = ["步骤一、获取数据", "步骤二、处理数据", "步骤三、输出结果"]
    doc = "\n".join(step_list)
    logger.info(step_list)
    output = f"已获取到步骤：\n{doc}\n请确认是否需要修改，若无需修改，请请输入“继续”；若需要修改，请按当前格式进行修改和追加...\n"
    return {
        **state,
        "output": output,
        "origin_step_list": step_list,
        "step_list": None,
        "current_stage": "confirm_steps",
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
    agent_executor = await get_mcp_agent()

    i = state["current_step"]
    step = state["step_list"][i]
    retry_input = state.get("retry_payload")
    if retry_input is not None:
        step = retry_input
    
    logger.info(f"开始执行步骤{i + 1}: {step}")
    print(f"开始执行步骤{i + 1}: {step}")
    try:
        # --- 步骤一：获取数据 ---
        if step == "步骤一、获取数据":
            # 直接查询teller_info表的结构和示例数据
            query_schema = "DESCRIBE teller_info;"
            tool_input_schema = {
                "server_name": "mysql",
                "tool_name": "run_sql_query",
                "arguments": {"query": query_schema}
            }
            response_schema = await agent_executor.ainvoke({"input": f"查询表结构: {json.dumps(tool_input_schema)}"})
            result_schema = response_schema["output"]
            
            schema_text = ""
            if isinstance(result_schema, list) and result_schema and hasattr(result_schema[0], 'text'):
                schema_text = result_schema[0].text
            else:
                schema_text = str(result_schema)

            query_data = "SELECT * FROM teller_info LIMIT 3;"
            tool_input_data = {
                "server_name": "mysql",
                "tool_name": "run_sql_query",
                "arguments": {"query": query_data}
            }
            response_data = await agent_executor.ainvoke({"input": f"查询示例数据: {json.dumps(tool_input_data)}"})
            result_data = response_data["output"]

            data_text = ""
            if isinstance(result_data, list) and result_data and hasattr(result_data[0], 'text'):
                data_text = result_data[0].text
            else:
                data_text = str(result_data)

            # 存储查询到的数据
            state["db_schema"] = schema_text
            state["db_sample_data"] = data_text

            summary = f"步骤{i + 1}：{step} 执行成功。\n表结构：{schema_text}\n示例数据：{data_text}"
            print(summary)
            return {
                **state,
                "current_step": i + 1,
                "step_outputs": state["step_outputs"] + [summary],
                "step_results": state.get("step_results", []) + [response_schema, response_data],
                "output": summary,
                "pending_action": None,
                "retry_payload": None,
                "history": state["history"] + [f"助手：{summary}"]
            }

        # --- 步骤二：处理数据 (生成请求报文并等待确认 / 调用API) ---
        elif step == "步骤二、处理数据":
            # 如果是第一次进入此步骤，生成请求报文并等待用户确认
            if state.get("pending_action") != "await_api_call_confirmation":
                selected_scene_data = state["selected_scene"]["data"]
                request_body = selected_scene_data.get("request_body")
                api_headers = API_INFO["headers"].copy()
                if "headers" in selected_scene_data:
                    api_headers.update(selected_scene_data["headers"])

                current_request_params = {
                    "url": API_INFO["url"],
                    "method": API_INFO["method"],
                    "headers": api_headers,
                    "json_body": request_body
                }
                state["current_request_params"] = current_request_params
                state["api_request_payload"] = current_request_params # 存储待确认的请求报文

                output = f"步骤{i + 1}：{step} 已生成API请求报文：\n{json.dumps(current_request_params, indent=2, ensure_ascii=False)}\n请确认是否调用API，若无需修改，请请输入“继续”；若需要修改，请按 参数=xxx 格式进行修改和重试..."
                print(output)
                return {
                    **state,
                    "pending_action": "await_api_call_confirmation", # 设置等待用户确认的标志
                    "user_confirmed": None, # 重置用户确认状态
                    "output": output,
                    "history": state["history"] + [f"助手：{output}"]
                }
            # 如果用户已确认，则实际调用API
            else:
                tool_input_api = {
                    "server_name": "test_project",
                    "tool_name": "call_api",
                    "arguments": state["current_request_params"] # 使用之前生成的请求参数
                }
                
                response_api = await agent_executor.ainvoke({"input": f"调用API: {json.dumps(tool_input_api)}"})
                
                # 提取原始的API响应内容
                raw_api_output = ""
                if isinstance(response_api, dict) and "output" in response_api:
                    if isinstance(response_api["output"], list) and response_api["output"] and hasattr(response_api["output"][0], 'text'):
                        raw_api_output = response_api["output"][0].text
                    elif isinstance(response_api["output"], str):
                        raw_api_output = response_api["output"]
                elif isinstance(response_api, str): # 兼容直接返回字符串的情况
                    raw_api_output = response_api

                api_response_content = None
                error_occurred = False
                error_message = ""

                # 尝试从原始输出中提取JSON
                # 改进的JSON提取逻辑，寻找最外层的JSON对象
                json_match = re.search(r'(\{.*?\})', raw_api_output, re.DOTALL)
                if json_match:
                    try:
                        api_response_content = json.loads(json_match.group(1))
                        if "error" in api_response_content: # 如果解析出的JSON包含"error"键，说明是错误响应
                            error_occurred = True
                            error_message = f"API调用工具返回错误：{json.dumps(api_response_content, indent=2, ensure_ascii=False)}"
                    except json.JSONDecodeError:
                        error_occurred = True
                        error_message = f"API调用工具返回非JSON格式响应或解析失败。原始输出：{raw_api_output}"
                else:
                    error_occurred = True
                    error_message = f"API调用工具返回非JSON格式响应或解析失败。原始输出：{raw_api_output}"

                if error_occurred:
                    output = f"步骤{i + 1}：{step} 执行失败：{error_message}\n请输入“继续”或“停止”，或使用 参数=xxx 格式重试。"
                    return {
                        **state,
                        "pending_action": f"step_{i}_error",
                        "user_confirmed": None, # 保持为None，等待用户输入
                        "output": output,
                        "history": state["history"] + [f"助手：{output}"]
                    }
                else:
                    state["last_api_response"] = api_response_content
                    summary = f"步骤{i + 1}：{step} 执行成功，API响应：{json.dumps(api_response_content, indent=2, ensure_ascii=False)}"
                    print(summary)
                    return {
                        **state,
                        "current_step": i + 1, # 成功时才推进步骤
                        "step_outputs": state["step_outputs"] + [summary],
                        "step_results": state.get("step_results", []) + [response_api],
                        "output": summary,
                        "pending_action": None, # 清除pending_action
                        "retry_payload": None,
                        "history": state["history"] + [f"助手：{summary}"]
                    }

        # --- 步骤三：输出结果 (验证响应) ---
        elif step == "步骤三、输出结果":
            last_api_response = state.get("last_api_response")
            expected_response = state["selected_scene"]["data"].get("expected_response")
            
            if not last_api_response or not expected_response:
                output = f"步骤{i + 1}：{step} 执行失败：未找到API响应或预期响应。请确保前置步骤已成功执行。"
                return {
                    **state,
                    "pending_action": f"step_{i}_error",
                    "user_confirmed": None,
                    "output": output,
                    "history": state["history"] + [f"助手：{output}"]
                }
            
            # 直接输出API响应结果，并进行解读
            output_data = {
                "data": last_api_response.get("data", {}),
                "return_code": last_api_response.get("return_code", ""),
                "return_msg": last_api_response.get("return_msg", "")
            }
            
            interpretation = "根据API调用返回的结果，查询操作已成功处理。以下是详细响应信息：\n\n"
            interpretation += f"### 返回状态\n- **返回码**: `{output_data['return_code']}` (表示请求成功)\n- **返回消息**: `{output_data['return_msg']}`\n\n"
            
            if "field1" in output_data["data"]:
                interpretation += f"### 查询数据详情\n1. **用户身份信息**  \n   `{output_data['data']['field1']}`\n\n"
            if "field3" in output_data["data"]:
                interpretation += f"2. **服务站点信息**  \n   `{output_data['data']['field3']}`\n\n"
            if "field2" in output_data["data"]:
                interpretation += f"3. **其他字段信息**  \n   ```json\n{json.dumps(output_data['data']['field2'], indent=2, ensure_ascii=False)}\n   ```\n\n"
            
            summary = f"步骤{i + 1}：{step} 执行成功。\n{interpretation}"
            print(summary)
            return {
                **state,
                "current_step": i + 1,
                "step_outputs": state["step_outputs"] + [summary],
                "output": summary,
                "history": state["history"] + [f"助手：{summary}"]
            }
        else:
            output = f"步骤{i + 1}：{step} 未识别的步骤，请检查步骤定义。\n请输入“继续”或“停止”，或使用 参数=xxx 格式重试。"
            return {
                **state,
                "pending_action": f"step_{i}_error",
                "user_confirmed": None,
                "output": output,
                "history": state["history"] + [f"助手：{output}"]
            }
    except Exception as e:
        output = f"步骤{i + 1}：{step} 执行失败：{str(e)}。请输入“继续”或“停止”，或使用 参数=xxx 格式重试。"
        return {
            **state,
            "error_message": str(e),
            "pending_action": f"step_{i}_error",
            "user_confirmed": None,
            "output": output,
            "history": state["history"] + [f"助手：{output}"]
        }


# 2.6 错误处理节点
def handle_error(state: AgentState) -> AgentState:
    text = state["user_input"].strip()
    pending_action = state.get("pending_action")

    if "停止" in text:
        return {**state, "user_confirmed": False, "output": "已终止流程。", "pending_action": None}

    if "继续" in text:
        # 如果是等待API调用确认，则用户确认继续调用API
        if pending_action == "await_api_call_confirmation":
            return {
                **state,
                "user_confirmed": True,
                "pending_action": "await_api_call_confirmation", # 保持此状态，以便router路由回execute_step
                "retry_payload": None,
                "output": "收到确认指令，准备调用API。"
            }
        # 如果是步骤执行失败后的重试
        elif pending_action and "step_" in pending_action:
            return {
                **state,
                "user_confirmed": True,
                "pending_action": None, # 清除pending_action，以便router重新评估
                "retry_payload": None,
                "output": "收到修复指令，准备重新执行失败步骤。"
            }
    
    if text.startswith("参数="):
        new_payload_str = text.replace("参数=", "").strip()
        try:
            # 尝试解析为JSON，如果失败则作为普通字符串处理
            new_payload = json.loads(new_payload_str)
        except json.JSONDecodeError:
            new_payload = new_payload_str # 如果不是JSON，就当作字符串

        if pending_action == "await_api_call_confirmation":
            # 如果是修改API请求参数
            state["current_request_params"] = new_payload
            return {
                **state,
                "user_confirmed": True,
                "pending_action": "await_api_call_confirmation", # 保持此状态，以便router路由回execute_step
                "retry_payload": None,
                "output": f"已更新API请求参数，准备重新调用API：\n{json.dumps(new_payload, indent=2, ensure_ascii=False)}"
            }
        elif pending_action and "step_" in pending_action:
            # 如果是修改步骤重试的payload
            return {
                **state,
                "user_confirmed": True,
                "pending_action": None,
                "retry_payload": new_payload_str, # retry_payload仍然是字符串
                "output": f"收到修复指令，准备使用新参数重试失败步骤：{new_payload_str}"
            }

    return {
        **state,
        "user_confirmed": None,
        "output": "未识别的输入，请输入“继续”或“停止”，或使用 参数=xxx 重试。"
    }


# 2.7 结束节点
def finish(state: AgentState) -> AgentState:
    logger.info("结束")
    output = "✅ 所有步骤执行完毕！\n\n"
    print(output)
    return {
        **state,
        "output": output
    }


# 2.8 路由节点
def router(state: AgentState) -> str:
    # 如果有pending_action且用户未确认，则路由到错误处理
    if state["pending_action"] and state["user_confirmed"] is None:
        return "handle_error"
    # 如果用户已确认继续，且当前处于错误处理或API调用确认后的状态，则路由回execute_step
    if state["user_confirmed"] is True and (state["pending_action"] == "await_api_call_confirmation" or "step_" in state["pending_action"]):
        return "execute_step"

    if state["current_stage"] == "confirm_scene":
        return "confirm_scene"
    if state["current_stage"] == "retrieve_steps":
        return "retrieve_steps" # retrieve_steps会自己转到confirm_steps
    if state["current_stage"] == "confirm_steps":
        return "confirm_steps" # confirm_steps会自己转到execute_step
    if state["current_stage"] == "execute_step":
        if state["current_step"] < len(state["step_list"]):
            return "execute_step"
        else:
            return "finish"
    return "query_scene"


# 3. 构建图
def build_graph():
    logger.info("============构建状态图============")
    builder = StateGraph(AgentState)
    
    # 添加节点
    builder.add_node("query_scene", query_scene)
    builder.add_node("confirm_scene", confirm_scene)
    builder.add_node("retrieve_steps", retrieve_steps)
    builder.add_node("confirm_steps", confirm_steps)
    builder.add_node("execute_step", execute_step)
    builder.add_node("handle_error", handle_error)
    builder.add_node("finish", finish)
    
    # 设置入口路由和边
    builder.set_conditional_entry_point(router)
    # 明确定义从错误处理返回的路径
    builder.add_edge("handle_error", "execute_step") # 假设错误处理后总是重试
    builder.add_edge("finish", END)

    return builder.compile()


# --- 主程序运行逻辑 ---
async def main():
    work_graph = build_graph()
    initial_state = {
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
        "api_request_payload": None # 初始化新字段
    }
    
    # 初始调用，获取第一个输出
    state = await work_graph.ainvoke(initial_state)

    while True:
        if state.get("output"):
            print(f"🤖 {state['output']}")
        
        # 检查是否结束
        if state.get("current_stage") == "execute_step" and state.get("current_step", 0) >= len(state.get("step_list", [])):
             final_state = await work_graph.ainvoke(state)
             if final_state.get("output"):
                 print(f"🤖 {final_state['output']}")
             break

        # 判断是否需要用户输入
        # 需要用户输入的场景：确认场景、确认步骤、有pending_action（错误处理或API调用确认）
        if state.get("current_stage") in ["confirm_scene", "confirm_steps"] or state.get("pending_action"):
            user_input = input("你：").strip()
            state["user_input"] = user_input
            if user_input.lower() in ["退出", "exit", "quit", "q"]:
                print("再见！")
                break
        else:
            state["user_input"] = ""  # 自动流程不需要用户输入

        # 再次调用图
        state = await work_graph.ainvoke(state)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n程序已由用户手动中断。再见！")
