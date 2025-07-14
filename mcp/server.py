from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Optional
import uuid
from workflows.graph import build_graph

app = FastAPI()
graph = build_graph()

# 会话状态缓存
SESSION_CACHE = {}

class MCPRequest(BaseModel):
    user_input: str
    session_id: Optional[str] = None
    history: Optional[List[str]] = []

class MCPResponse(BaseModel):
    output: str
    session_id: str
    history: List[str]

@app.post("/mcp", response_model=MCPResponse)
def mcp_endpoint(req: MCPRequest):
    session_id = req.session_id or str(uuid.uuid4())
    print("session_id:", session_id)

    # 获取旧状态或初始化新状态
    if session_id not in SESSION_CACHE:
        SESSION_CACHE[session_id] = {
            "session_id": session_id,
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

    # 替换本轮用户输入
    SESSION_CACHE[session_id]["user_input"] = req.user_input
    # 取旧状态
    history = SESSION_CACHE[session_id]["history"] if session_id in SESSION_CACHE else []

    # 追加本次用户输入
    history = history + [f"用户：{req.user_input}"]

    # 更新状态中的 history
    SESSION_CACHE[session_id]["history"] = history
    SESSION_CACHE[session_id]["user_input"] = req.user_input

    # 调用 LangGraph
    result = graph.invoke(SESSION_CACHE[session_id], config={"configurable": {"thread_id": session_id}})

    # 更新缓存
    SESSION_CACHE[session_id] = result

    return MCPResponse(
        output=result["output"],
        session_id=session_id,
        history=result["history"]
    )


