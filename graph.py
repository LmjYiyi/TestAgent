from langgraph.graph import StateGraph, END
from typing import TypedDict, List, Literal, Optional
import random

# 1. 定义状态结构
class State(TypedDict):
    session_id: str
    user_input: str
    history: List[str]
    current_stage: Literal["choose_scene", "confirm_scene", "execute_steps"]
    selected_scene: Optional[str]
    step_list: List[str]
    current_step_index: int
    step_outputs: List[str]
    step_results: List[dict]
    pending_action: Optional[str]
    user_confirmed: Optional[bool]
    error_message: Optional[str]
    retry_payload: Optional[str]
    output: str

# 2. 场景数据
SCENARIOS = ["导出日报", "删除测试数据", "重启服务"]
SCENE_STEPS = {
    "导出日报": ["连接数据库", "查询数据", "写入 Excel", "发送邮件"],
    "删除测试数据": ["连接数据库", "执行 DELETE", "记录日志"],
    "重启服务": ["停止服务", "清理缓存", "启动服务"]
}

def rag_scene_match(state: State) -> State:
    output = "我找到以下场景，请输入编号确认：\n" + \
             "\n".join([f"{i+1}. {s}" for i, s in enumerate(SCENARIOS)])
    return {
        **state,
        "output": output,
        "current_stage": "confirm_scene",
        "history": state["history"] + [f"助手：{output}"]  # 追加历史
    }


def confirm_scene(state: State) -> State:
    text = state["user_input"].strip()
    try:
        idx = int(text) - 1
        scene = SCENARIOS[idx]

        output = f"已选择场景：{scene}，共 {len(SCENE_STEPS[scene])} 步。开始执行..."
        return {
            **state,
            "selected_scene": scene,
            "step_list": SCENE_STEPS[scene],
            "current_step_index": 0,
            "step_outputs": [],
            "step_results": [],
            "current_stage": "execute_steps",
            "output": output,
            "history": state["history"] + [f"助手：{output}"]  # 追加历史
        }
    except:
        output = "输入无效，请重新输入编号确认场景。"
        return {
            **state,
            "output": output,
            "history": state["history"] + [f"助手：{output}"]  # 追加历史
        }

def execute_step(state: State) -> State:
    i = state["current_step_index"]
    step = state["step_list"][i]
    retry_input = state.get("retry_payload")

    try:
        # 模拟步骤返回结果
        if "连接数据库" in step:
            result = {"status": "ok", "db": "main"}
        elif "查询数据" in step:
            result = {"status": "ok", "rows": 100}
        elif "Excel" in step:
            result = {"status": "ok", "file": "/tmp/report.xlsx"}
        elif "邮件" in step:
            result = {"status": "ok", "to": "user@example.com"}
        elif "DELETE" in step:
            if random.random() < 0.5:
                raise Exception("")
            result = {"status": "ok", "deleted": 42}
        else:
            result = {"status": "ok", "info": f"{step} "}

        summary = f"步骤1：{step} 执行成功，结果：{result}"

        return {
            **state,
            "current_step_index": i + 1,
            "step_outputs": state["step_outputs"] + [summary],
            "step_results": state.get("step_results", []) + [result],
            "output": summary,
            "pending_action": None,
            "retry_payload": None,
            "history": state["history"] + [f"助手：{summary}"]  # 追加历史

        }

    except Exception as e:
        output = f"""步骤{i+1}：{step} 执行失败：{str(e)}。请输入“继续”或“停止”，或使用 参数=xxx 格式重试。"""
        return {
            **state,
            "error_message": str(e),
            "pending_action": f"step_{i}_error",
            "user_confirmed": None,
            "output": f"步骤{i+1}：{step} 执行失败：{str(e)}。请输入“继续”或“停止”，或使用 参数=xxx 格式重试。",
            "history": state["history"] + [f"助手：{output}"]  # 追加历史

        }

def handle_error(state: State) -> State:
    text = state["user_input"].strip()

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

def finish(state: State) -> State:
    summary = "\n".join(state["step_outputs"])
    return {
        **state,
        "output": "✅ 所有步骤执行完毕，执行摘要：\n\n" + summary
    }

# 3. 构建 LangGraph 流程
def build_graph():
    builder = StateGraph(State)

    builder.add_node("rag_scene_match", rag_scene_match)
    builder.add_node("confirm_scene", confirm_scene)
    builder.add_node("execute_step", execute_step)
    builder.add_node("handle_error", handle_error)
    builder.add_node("finish", finish)

    def router(state: State) -> str:
        if state["pending_action"] and state["user_confirmed"] is None:
            return "handle_error"
        if state["current_stage"] == "confirm_scene":
            if state["selected_scene"] is not None:
                return "execute_step"
            return "confirm_scene"
        if state["current_stage"] == "execute_steps":
            if state["current_step_index"] < len(state["step_list"]):
                return "execute_step"
            else:
                return "finish"
        return "rag_scene_match"



    builder.set_conditional_entry_point(router)
    builder.add_edge("finish", END)
    compiler = builder.compile()

    return compiler

# 4. 命令行与用户交互
if __name__ == "__main__":
    graph = build_graph()

    state: State = {
        "session_id": "abc",
        "user_input": "",
        "history": [],
        "current_stage": "choose_scene",
        "selected_scene": None,
        "step_list": [],
        "current_step_index": 0,
        "step_outputs": [],
        "step_results": [],
        "pending_action": None,
        "user_confirmed": None,
        "error_message": None,
        "retry_payload": None,
        "output": ""
    }

    while True:
        if state["output"]:
            print(f"\n🤖 {state['output']}")

        if "执行完毕" in state.get("output", ""):
            break

        user_input = input("你：").strip()
        state["user_input"] = user_input
        state = graph.invoke(state)
