###起后台服务，直接和前端对接
### uvicorn run:app --reload --port 8000


import os
import json
import asyncio
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from workflows.graph_builder import build_graph

app = FastAPI()

# 允许前端跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8080"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- 状态持久化相关 ----------
def save_state(session_id: str, state: dict):
    with open(f"state_{session_id}.json", "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)

def load_state(session_id: str) -> dict:
    path = f"state_{session_id}.json"
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None

# ---------- SSE 聊天流 ----------
@app.get("/chat/stream")
async def chat_stream(request: Request, session_id: str):
    graph = build_graph()

    # 加载已有状态，如果没有就初始化
    state = load_state(session_id)
    if not state:
        state = {
            "session_id": session_id,
            "user_input": "",
            "history": [],
            "current_stage": "query_scene",  # 初始阶段
            "selected_scene": None,
            "origin_step_list": [],
            "step_list": [],
            "current_step": 0,
            "step_outputs": [],
            "step_results": [],
            "pending_action": None,
            "user_confirmed": None,
            "error_message": None,
            "retry_payload": None,
            "output": ""
        }

    #每秒检查一次是否有新输入
    async def event_generator():
        nonlocal state
        while state["current_stage"] != "finish":  # 循环限制：当节点当前节点为finish时，则跳出循环
            if await request.is_disconnected():
                print("客户端断开连接")
                return
            # 如果需要用户交互，就等待用户输入文件
            if state["output"] is not None:
                print(f"\n助手：{state['output']}")
                user_input = await wait_for_user_input_file(session_id)
                state["user_input"] = user_input
                print("收到用户输入:", user_input)
            else:
                print("请稍等...")

            # 执行图计算
            state = graph.invoke(state)

            # 持久化状态
            save_state(session_id, state)

            # 推送给前端
            yield f"data: {json.dumps(state, ensure_ascii=False)}\n\n"

            # 如果流程结束
            if state.get("output") and "执行完毕" in state["output"]:
                return

        yield f"data: {json.dumps({'output': '执行完毕'})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

# ---------- 接收用户输入 ----------
class ChatRequest(BaseModel):
    message: str
    session_id: str

@app.post("/chat")
async def chat(req: ChatRequest):
    # 将用户输入写入 session 文件，供后台读取
    with open(f"session_{req.session_id}.txt", "w", encoding="utf-8") as f:
        f.write(req.message)
    return {"output": "消息已发送，开始处理..."}

# ---------- 轮询用户输入,每隔一秒轮询一次 ----------
async def wait_for_user_input_file(session_id: str, timeout: int = 300):
    path = f"session_{session_id}.txt"
    waited = 0
    while waited < timeout:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                user_input = f.read().strip()
            os.remove(path)
            if user_input:
                return user_input
        await asyncio.sleep(1)
        waited += 1
    return ""
