import requests

from workflows.graph import State

url = "http://localhost:8001/mcp"
session_id = None
history = []
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
    resp = requests.post(url, json={
        "user_input": user_input,
        "session_id": session_id,
        "history": history
    })
    data = resp.json()
    print("助手：", data["output"])
    session_id = data["session_id"]
    history = data["history"]
