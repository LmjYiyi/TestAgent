from langchain_core.runnables.utils import Output
from langgraph.graph import StateGraph, END
from langchain_core.prompts import ChatPromptTemplate
from agents.mcp_agent import get_mcp_agent
from models.dquestion import get_llm
from utils import logger
from utils.db_utils import DatabaseManager
from tools.rag_tools import query_scene_list,query_scene_steps
from typing import TypedDict, List, Optional, Literal, Annotated, Sequence
from langchain_core.messages import SystemMessage,BaseMessage, HumanMessage, AIMessage
from langgraph.graph.message import add_messages
from langgraph.checkpoint.base import BaseCheckpointSaver
from workflows.api_scene import get_scenario_steps
import asyncio 
import json


class AgentState(TypedDict):
    user_input: str
    current_stage: Literal["confirm_scene", "retrieve_steps", "confirm_steps", "execute_step"] 
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
    db_schema: Optional[str]
    db_sample_data: Optional[str]
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
             "\n".join([f"{i + 1}. {s}" for i, s in enumerate(api_list)])
    
        return {
            **state,
            "output": output,
            "current_stage": "confirm_scene",
            "messages": [AIMessage(content=output)]
        }

def confirm_scene(state: AgentState) -> AgentState:
    """
    用于与用户交互，用户选择并确认接口-场景
    TODO: 没有用户想要的场景
    """
    logger.info("用户进行场景选择.....")
    text = state["user_input"].strip()
    try:
        idx = int(text) - 1
        scene = state["api_list"][idx]
        result_dict = dict(pair.split(": ") for pair in scene.split(", "))
        print("转换后的字典:", result_dict)
        output = f"已选择场景：{scene}，开始查询执行步骤..."
        print(output)
        return {
            **state,
            "selected_scene": result_dict,
            "origin_step_list": None,
            "step_list": None,
            "current_step": 0,
            "step_outputs": [],
            "step_results": [],
            "current_stage": "retrieve_steps",
            "output": None,
            "messages": [AIMessage(content=output)]
        }
    except:
        output = "输入无效，请重新输入编号确认场景。"
        return {
            **state,
            "output": output,
            "messages": [AIMessage(content=output)]
        }

async def retrieve_steps(state: AgentState) -> AgentState:
    """
    获取执行步骤节点
    """
    # doc = retrieve_docs(state["selected_scene"])
    logger.info("开始进行场景步骤检索....")
    # selected_scene = state["selected_scene"]
    # step_list = await query_scene_steps(selected_scene['接口中文名'],selected_scene['场景名'])
    step_list = get_scenario_steps("统一认证用户信息查询 - 场景分支1：验证统一认证号分支")
    logger.info(step_list)
    output = f"已获取到步骤：\n{step_list}\n请确认是否需要修改，若无需修改，请输入“继续”；若需要修改，请按当前格式进行修改和追加...\n"
    return {
        **state,
        "output": output,
        "origin_step_list": step_list,
        "step_list": None,
        "current_stage": "confirm_steps",
        "messages": [AIMessage(content=output)]
    }
    # TODO: 如果没查到的处理逻辑


def confirm_steps(state: AgentState) -> AgentState:
    """
    步骤确认节点，---用户交互节点
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
        # step_list = ['步骤一、(3+5)*4等于几?', '步骤二、广州今天的天气怎么样']
    # print(step_list)
    output = f"根据用户要求，最终步骤为：\n{step_list}，共 {len(step_list)} 步。\n开始执行步骤..."
    print(output)
    return {
        **state,
        "step_list": step_list,
        "current_step": 0,
        "step_outputs": [],
        "step_results": [],
        "current_stage": "execute_step",
        "output": None,
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
    # try:
        # response = await agent_executor.ainvoke({"input": step})
        # print(response)
        # if response['output'] != "":
        #     summary = f"步骤{i + 1}：{step} 执行成功，结果：{response['output']}"
        #     print(summary)
        #     return {
        #         **state,
        #         "current_step": i + 1,
        #         "step_outputs": state["step_outputs"] + [summary],
        #         "step_results": state.get("step_results", []) + [response],
        #         "output": None,
        #         "pending_action": None,
        #         "retry_payload": None,  # 清空
        #         "messages": [AIMessage(content=summary)]
        #     }
        # else:
        #     output = f"步骤{i + 1}：{step} 执行失败：{str(response)}\n请输入“继续”或“停止”，或使用 参数=xxx 格式重试。"
        #     # TODO: 添加诊断意见
        #     return {
        #         **state,
        #         # "error_message": str(response),
        #         "pending_action": f"step_{i}_error",
        #         "user_confirmed": None,
        #         "output": output,
        #         "messages": [AIMessage(content=output)]
        #     }
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
    - **要求**：如果没有找到这个表或者其他失败的情况，请返回一个错误消息，不要再继续执行了。
2.  **执行数据查询**:
    - **你的唯一指令**: 在上一步成功获取表结构后，你 **必须** 调用 `run_sql_query` 工具，根据 `场景定义` 中的 `ssic_type` 和 `ssic_id` 查询 `teller_info` 表中的数据。
    - **工具输入示例**: `{"query": "SELECT * FROM teller_info WHERE ssic_type = '3' AND ssic_id = 'B234567(8)' LIMIT 1;"}` (请根据实际场景定义中的值替换 `ssic_type` 和 `ssic_id`)
    - **要求**：如果这一步失败，请返回一个错误消息，不要再继续执行了。
3.  **保存测试数据**:
    - **你的唯一指令**: 在上一步成功查询到数据后，你 **必须** 调用 `update_state` 工具，将查询到的数据保存到状态中。
    - **工具输入示例**: `{"state_object": {"test_data": [<你从数据库查询到的数据>]}}`
    - **要求**：如果这一步失败，请返回一个错误消息和目前执行得到的结果，不要再继续执行了。
- **禁止**: 在没有先执行 `DESCRIBE` 的情况下，直接执行 `SELECT` 查询。
- **禁止**: 禁止随意发挥、自由发挥，必须按照上述步骤进行，若无法执行，请如实将错误结果返回。
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
            "messages": [AIMessage(content=f"Agent:\n{summary}\n\nAssistant:\n{final_output}")]
            # "history": state["history"] + [f"Agent:\n{summary}\n\nAssistant:\n{final_output}"]
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
    if "停止" in text:
        output = "已终止流程。"
        return {**state, "user_confirmed": False, "messages": [AIMessage(content=output)]}

    if "继续" in text or text.startswith("参数="):
        retry_payload = text.replace("参数=", "") if "参数=" in text else None
        output = "收到修复指令，准备重新执行失败步骤，请确认是否继续执行。"
        return {
            **state,
            "user_confirmed": True,
            "output": output,
            "retry_payload": retry_payload,
            "messages": [AIMessage(content=output)]
        }
    output = "未识别的输入，请输入“继续”或“停止”，或使用 参数=xxx 重试。"
    return {
        **state,
        "user_confirmed": None,
        "messages": [AIMessage(content=output)]
    }


# 2.7 结束节点--对外输出
def finish(state: AgentState) -> AgentState:
    logger.info("结束")
    summary = "\n".join(state["step_outputs"])
    # output = "✅ 所有步骤执行完毕，执行摘要：\n\n" + summary
    output = "✅ 所有步骤执行完毕！\n\n"
    print(output)
    return {
        **state,
        "output": output,
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