from langgraph.graph import StateGraph, END
from langchain_core.prompts import ChatPromptTemplate
from agents.mcp_agent import get_mcp_agent
from models.dquestion import get_llm
# from tools.rag_tools import query_interface_tool,query_execute_steps_tool
from utils import logger
import json
from typing import TypedDict, List, Optional,Literal

# 1. 定义状态结构
# ----------------------------------
class AgentState(TypedDict):
    user_input: str
    current_stage: Literal["confirm_scene", "retrieve_steps", "confirm_steps", "execute_step"] # 当前阶段，langgraph不支持从任一节点开始，必须从入口节点开始，所以要标记状态
    pending_action: Optional[str] # 挂起的动作
    user_confirmed: Optional[bool] # 用户是否确认
    api_list: List[str] # 接口场景列表
    selected_scene: dict # 所选择的接口场景
    origin_step_list: List[str] # 原始步骤列表
    step_list: List[str] # 最终步骤列表
    current_step: int # 当前步骤
    step_outputs: List[str] # 步骤输出
    step_results: List[dict] # 步骤结果
    # input_params: List[str] # 接口输入参数
    # output_params: List[str] # 接口输出参数
    error_message: Optional[str] # 错误信息
    retry_payload: Optional[str] # 重试的参数
    output: str # 输出结果，用来标记本次的结束
    # 两者的区别？
    history: List[str] # 历史记录
    # messages: Annotated[Sequence[BaseMessage], add_messages] # 消息

# memory = MemorySaver()

# 2. 定义节点、边函数
# ------------------------------
# 2.1 获取场景列表节点
# 根据用户输入构建提示词，去调用RAG查找接口+场景列表相关文档，送入大模型并将返回到结果结构化后存入state里面
llm = get_llm()
def query_scene(state: AgentState) -> AgentState:
    logger.info("开始获取场景列表.....")
    template = """Question: {question}根据用户的输入转换成 接口名：场景 这样的键值对，并以列表的形式返回。请用简体中文回复。
    例如，用户输入：我想查询我想要用统一认证查询接口，测试用户登陆的场景，那么应该返回："接口名:统一认证查询接口, 场景: 测试用户登陆"。
    要求：以列表的形式返回，只需要输出结果，不需要额外内容。
    """
    # prompt = ChatPromptTemplate.from_template(template)
    # info_chain = prompt | llm
    # response = info_chain.invoke({"question": state['user_input']})
    # # 解析返回
    # content = response.content.strip().replace('\n', '')
    # print(content)
    # parsed = json.loads(content)
    # if isinstance(parsed, list):
    #     api_list = parsed  # 直接使用解析后的列表
    # else:
    #     api_list = [str(parsed)]
    
    api_list = ["接口名:统一认证查询接口, 场景: 测试用户登陆","接口名：信用卡消费，场景：准贷记卡消费"]

    state["api_list"] = api_list
    # print(state["api_list"])
    # TODO: 没有考虑查询不到的情况，以及没有用户想要的场景
    output = "我找到以下场景，请输入编号确认：\n" + \
             "\n".join([f"{i+1}. {s}" for i, s in enumerate(api_list)])
    return {
        **state,
        "output": output,
        "current_stage": "confirm_scene",
        "history": state["history"] + [f"助手：{output}"] 
    }

# 2.2 用户确认场景节点---交互节点
def confirm_scene(state: AgentState) -> AgentState:
    logger.info("用户进行场景选择.....")
    text = state["user_input"].strip()
    try:
        idx = int(text) - 1
        scene = state["api_list"][idx]
        output = f"已选择场景：{scene}，开始查询执行步骤..."
        print(output)
        return {
            **state,
            "selected_scene": scene,
            "origin_step_list": None,
            "step_list": None,
            "current_step": 0,
            "step_outputs": [],
            "step_results": [],
            "current_stage": "retrieve_steps",
            "output": None,
            "history": state["history"] + [f"助手：{output}"]  # 追加历史
        }
    except:
        output = "输入无效，请重新输入编号确认场景。"
        return {
            **state,
            "output": output,
            "history": state["history"] + [f"助手：{output}"]  # 追加历史
        }

# 2.3 获取执行步骤节点
# 这一步应该直接获取原文档内容
def retrieve_steps(state: AgentState) -> AgentState:
    # doc = retrieve_docs(state["selected_scene"])
    logger.info("开始进行场景步骤检索....")
    doc = "步骤一、获取数据\n步骤二、处理数据\n步骤三、输出结果"
    step_list = [step for step in doc.split('\n')]
    logger.info(step_list)
    output = f"已获取到步骤：\n{doc}\n请确认是否需要修改，若无需修改，请输入“继续”；若需要修改，请按当前格式进行修改和追加...\n"
    return {
        **state,
        "output": output,
        "origin_step_list": step_list,
        "step_list": None,
        "current_stage": "confirm_steps",
        "history": state["history"] + [f"助手：{output}"]  # 追加历史
    }
    # 如果没查到的处理逻辑 todo

# 2.4 步骤确认---用户交互节点
def confirm_steps(state: AgentState) -> AgentState:
    logger.info("开始进行场景步骤修改与合并....")
    text = state["user_input"].strip()
    # 判断用户的输入
    if "继续" in text: 
        step_list = state["origin_step_list"]
    else :
        # 调用大模型组织结果
        template2 = """用户输入：{question}，原始内容{origin}。请仔细看用户输入内容，如果是对原始内容的追加，则结合用户输入和原始文本内容，将内容进行重新组织成步骤列表；如果是完整的步骤内容，则将完整的步骤整理后返回。
        例如，用户输入：步骤四、校验数据，原始内容：步骤一、获取数据\n步骤二、处理数据\n步骤三、输出结果，则最后应该返回：步骤一、获取数据\n步骤二、处理数据\n步骤三、输出结果\n步骤四、校验数据。
        要求：
        第一、按以上示例格式返回；
        第二、禁止追加不存在的内容，严格按照用户输入和原始内容进行整合。
        第三，只需要输出结果，不需要额外的描述。
        """
        # prompt2 = ChatPromptTemplate.from_template(template2)
        # steps_update_chain = prompt2 | llm
        # response = steps_update_chain.invoke({"question": text, "origin": state['origin_step_list']})
        # print(response.content)
        # content = response.content.strip()
        # # 假设传来的是字符串，需要转成list
        # step_list = [step  for step in content.split('\n')]
        step_list = ['步骤一、确认接口', '步骤二、获取数据', '步骤三、处理数据', '步骤四、输出结果']
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
            "history": state["history"] + [f"助手：{output}"]  # 追加历史
        }

# 2.5 执行步骤-agent节点（agent里面实现执行步骤，根据状态控制是继续循环执行agent还是调用错误诊断）
# agent里根据输入自主判断调用工具
agent_executor = get_mcp_agent()

def execute_step(state: AgentState) -> AgentState:
    i = state["current_step"]
    step = state["step_list"][i]
    retry_input = state.get("retry_payload")
    # 如果retry_input不为空，则用retry_input替代step,成功后清空
    logger.info(f"开始执行步骤{i+1}: {step}")
    print(f"开始执行步骤{i+1}: {step}")
    try: 
        # response = agent_executor.invoke({"input": step})
        # 根据response结构获取result，假设response就是结果

        # summary = f"步骤{i+1}：{step} 执行成功，结果：{response}"
        response = "201"
        summary = f"步骤{i+1}：{step} 执行成功"
        print(summary)
        if response == 200:
            return {
                **state,
                "current_step": i + 1,
                "step_outputs": state["step_outputs"] + [summary],
                "step_results": state.get("step_results", []) + [response],
                "output": None,
                "pending_action": None,
                "retry_payload": None,
                "history": state["history"] + [f"助手：{summary}"]  # 追加历史
            }
        else:
            output = f"步骤{i+1}：{step} 执行失败：{str(response)}。请输入“继续”或“停止”，或使用 参数=xxx 格式重试。"
            # TODO: 添加诊断意见
            return {
                **state,
                # "error_message": str(response),
                "pending_action": f"step_{i}_error",
                "user_confirmed": None,
                "output": output,
                "history": state["history"] + [f"助手：{output}"]  # 追加历史
            }
    except Exception as e:
        # 是不是要在这里加诊断意见？
        output = f"步骤{i+1}：{step} 执行失败：{str(e)}。请输入“继续”或“停止”，或使用 参数=xxx 格式重试。"
        return {
            **state,
            "error_message": str(e),
            "pending_action": f"step_{i}_error",
            "user_confirmed": None,
            "output": output,
            "history": state["history"] + [f"助手：{output}"]  # 追加历史
        }

# 2.6 错误诊断建议节点（是否要查数据库）
# template2 = """你的工作是根据输入的错误信息，对这个错误进行分析和诊断，并给出一个建议，让用户按照这个建议进行修复。
# 不要试图疯狂猜测，在你能够辨别所有信息后，调用相关工具。
# """

def handle_error(state: AgentState) -> AgentState:
    text = state["user_input"].strip()
    # 目前还需要手动退出流程
    if "停止" in text:
        return {**state, "user_confirmed": False, "output": "已终止流程。"}

    if "继续" in text or text.startswith("参数="):
        retry_payload = text.replace("参数=", "") if "参数=" in text else None
        return {
            **state,
            "user_confirmed": True,
            "retry_payload": retry_payload,
            "output": "收到修复指令，准备重新执行失败步骤。"
        }
    return {
        **state,
        "user_confirmed": None,
        "output": "未识别的输入，请输入“继续”或“停止”，或使用 参数=xxx 重试。"
    }

# 2.7 结束节点--对外输出
def finish(state: AgentState) -> AgentState:
    logger.info("结束")
    summary = "\n".join(state["step_outputs"])
    # output = "✅ 所有步骤执行完毕，执行摘要：\n\n" + summary
    output= "✅ 所有步骤执行完毕！\n\n"
    print(output)
    return {
        **state,
        "output": output
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
def build_graph():
    logger.info("============构建状态图============")

    # 构建状态图
    builder = StateGraph(AgentState)
    # 设置节点
    builder.add_node("query_scene", query_scene) # 获取接口列表
    builder.add_node("confirm_scene", confirm_scene) # 选择接口节点
    builder.add_node("retrieve_steps", retrieve_steps) # 检索步骤节点
    builder.add_node("confirm_steps", confirm_steps) # 用户确认步骤节点
    builder.add_node("execute_step", execute_step) # 执行步骤节点
    builder.add_node("handle_error", handle_error) # 错误处理节点
    builder.add_node("finish", finish) # 完成节点
    # 设置条件入口-路由
    builder.set_conditional_entry_point(router)
    # 设置边
    # builder.add_edge("confirm_scene", "retrieve_steps")
    # builder.add_edge("confirm_steps", "excute_step")
    builder.add_edge("finish", END)

    # 编译图
    compiler = builder.compile()
    #compiler.get_graph().draw_mermaid_png(output_file_path="main_graph.png")
    return compiler

if __name__ == '__main__':
    compiler = build_graph()
    state = {"user_input": "我想测试查询接口", "history": [], "output": ""}
    while True:
        if state["output"]:
            print(f"\n🤖 {state['output']}")

        if "执行完毕" in state.get("output", ""):
            break

        user_input = input("你：").strip()
        state["user_input"] = user_input
        state = compiler.invoke(state)