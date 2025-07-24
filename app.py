###起后台服务，直接和前端对接
### uvicorn app:app --reload --port 8000
###使用的是agent文件夹中的graph作为测试，因为workflows中的build_graph有多个版本，等合并后再用

import asyncio
from contextlib import asynccontextmanager


import json
from fastapi import FastAPI, Request, HTTPException, Body
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
from api.v1 import conversation as conversation_v1, feedback as feedback_v1
from utils.db_utils import db_manager
from utils.logger import setup_logger
from agent.graph import build_graph
from fastapi.responses import JSONResponse

logger = setup_logger('INFO')

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Application startup...")
    await db_manager.initialize()
    logger.info("Database initialized.")

    # 构建带有检查点的LangGraph
    global agent_app
    agent_app = build_graph(checkpointer=db_manager.get_checkpointer())
    logger.info("LangGraph Agent built with database checkpointer.")

    yield
    # Shutdown
    logger.info("Application shutdown...")
    await db_manager.close()
    logger.info("Database connections closed.")

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有来源，生产环境请替换为你的前端地址
    allow_credentials=True,
    allow_methods=["*"], # 允许所有方法
    allow_headers=["*"], # 允许所有头部
)

app.include_router(conversation_v1.router, prefix="/api/v1/conversation", tags=["Conversation"])
app.include_router(feedback_v1.router, prefix="/api/v1/feedback", tags=["Feedback"])


class ChatRequest(BaseModel):
    # 前端直接传递 user_id
    user_id: str 
    # thread_id 是可选的。前端不传或传 null，代表是新对话。
    thread_id: Optional[str] = None
    message: str

# class ChatResponse(BaseModel):
#     # 无论新旧对话，都必须返回 thread_id，以便前端在下一次请求时可以带上
#     thread_id: str
#     # 本次 AI 回复的完整内容
#     response_message: str

# @app.post("/api/v1/chat/invoke", response_model=ChatResponse)
# async def unified_chat_invoke(request: ChatRequest = Body(...)):
#     """
#     统一的【非流式】聊天接口。
#     - 如果请求中不包含 thread_id，则创建新对话。
#     - 如果包含 thread_id，则继续现有对话。
#     - 返回一次完整的响应。
#     """
#     try:
#         current_thread_id = request.thread_id
#         is_new_conversation = (current_thread_id is None)

#         # --- 后端核心判断与操作 (与流式接口完全相同) ---
#         if is_new_conversation:
#             logger.info(f"thread_id is null, creating new conversation for user: {request.user_id}")
#             new_conv = await db_manager.create_conversation_entry(request.user_id)
#             current_thread_id = new_conv['thread_id']
#             logger.info(f"New conversation created with thread_id: {current_thread_id}")
#         else:
#             logger.info(f"Continuing conversation for thread_id: {current_thread_id}")
#             conv_meta = await db_manager.get_conversation_meta(current_thread_id)
#             if not conv_meta or conv_meta.get('user_id') != request.user_id:
#                  raise HTTPException(status_code=404, detail="对话未找到或无权访问。")

#         # --- 调用 LangGraph 的非流式方法 ---
#         config = {"configurable": {"thread_id": current_thread_id}}
#         input_message = HumanMessage(content=request.message)
        
#         # 使用 .ainvoke() 等待完整的最终状态返回
#         final_state = await agent_app.ainvoke(
#             {"messages": [input_message]},
#             config
#         )

#         # 异步执行标题生成等收尾工作
#         asyncio.create_task(check_and_generate_title(current_thread_id))

#         # --- 构造并返回统一的响应体 ---
#         # 从最终状态中提取最后一条AI消息
#         response_message_content = ""
#         if final_state and final_state.get("messages"):
#             # 找到最后一条 AIMessage
#             for msg in reversed(final_state["messages"]):
#                 if msg.type == 'ai':
#                     response_message_content = msg.content
#                     break
        
#         return UnifiedChatResponse(
#             thread_id=current_thread_id,
#             response_message=response_message_content
#         )

#     except Exception as e:
#         logger.error(f"Error in unified invoke for request: {request.dict()}: {e}", exc_info=True)
#         return JSONResponse(status_code=500, content={"detail": "处理消息时发生内部错误。"})

@app.post("/aitest/chat/stream")
async def chat_stream(request: ChatRequest = Body(...)):
    """
    统一的流式聊天接口。
    - 如果请求中不包含 thread_id，则创建新对话。
    - 如果包含 thread_id，则继续现有对话。
    """
    try:
        current_thread_id = request.thread_id
        is_new_conversation = (current_thread_id is None)

        # --- 后端核心判断与操作 ---
        if is_new_conversation:
            # 1. 创建新对话
            logger.info(f"thread_id is null, creating new conversation for user: {request.user_id}")
            # 输入前端传的user_id,调用 db_utils.py 的创建会话函数,返回thread_id
            new_conv = await db_manager.create_conversation_entry(request.user_id)
            current_thread_id = new_conv['thread_id']
            logger.info(f"New conversation created with thread_id: {current_thread_id}")
        else:
            # 2. (安全加固) 继续现有对话，验证所有权
            logger.info(f"Continuing conversation for thread_id: {current_thread_id}")
            # 调用 db_utils.py 中的获取会话元数据函数判断对话是否属于当前用户
            conv_meta = await db_manager.get_conversation_meta(current_thread_id)
            if not conv_meta or conv_meta.get('user_id') != request.user_id:
                 raise HTTPException(status_code=404, detail="对话未找到或无权访问。")

        # --- 统一的流式处理生成器 ---
        async def event_stream():
            # 1. 握手事件：如果是新对话，必须先告诉前端新的thread_id
            if is_new_conversation:
                init_event = {"type": "init", "thread_id": current_thread_id}
                yield f"data: {json.dumps(init_event)}\n\n"

            # 2. 调用真正的异步流式 agent
            config = {"configurable": {"thread_id": current_thread_id}}
            input_message = HumanMessage(content=request.message)
            
            # 使用在 lifespan 中创建的全局 agent_app
            async for event in agent_app.astream_events({"messages": [input_message]}, config, version="v1"):
                event_name = event['event']
                if event_name == "on_chat_model_stream":
                    chunk = event["data"].get("chunk")
                    if chunk and hasattr(chunk, 'content'):
                        yield f"data: {json.dumps({'type': 'chunk', 'content': chunk.content})}\n\n"
                elif event_name == 'on_tool_end':
                     yield f"data: {json.dumps({'type': 'tool_result', 'tool_name': event['name'], 'output': event['data'].get('output')})}\n\n"
            
            # 3. 发送结束信号
            yield f"data: {json.dumps({'type': 'end'})}\n\n"
            
            # 异步执行标题生成等收尾工作
            asyncio.create_task(check_and_generate_title(current_thread_id))

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    except Exception as e:
        logger.error(f"Error in unified stream for request: {request.dict()}: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"detail": "处理消息时发生内部错误。"})


async def check_and_generate_title(thread_id: str):
    try:
        # 1. 获取对话元数据，检查标题是否已存在
        conv_meta = await db_manager.get_conversation_meta(thread_id)
        if conv_meta and conv_meta.get('title') and conv_meta['title'] != 'New Chat':
            logger.info(f"Conversation {thread_id} already has a title: {conv_meta['title']}")
            return

        # 2. 获取对话历史
        checkpoint = await db_manager.get_conversation_checkpoint(thread_id)
        if not checkpoint or not checkpoint.get('channel_values', {}).get('messages'):
            logger.info(f"No messages in conversation {thread_id} to generate a title.")
            return

        messages = checkpoint['channel_values']['messages']
        # 检查消息数量，例如，在第一轮交互后（1个人类消息，1个AI消息）
        if len(messages) >= 2:
            logger.info(f"Generating title for conversation {thread_id}...")
            # 3. 调用LLM生成标题
            from langchain_core.prompts import PromptTemplate
            from models.dquestion import get_title_generation_llm

            prompt = PromptTemplate.from_template(
                "根据以下对话内容，为其生成一个简洁的、不超过10个字的标题。\n\n对话内容:\n{history}\n\n标题:"
            )
            # 使用一个独立的、非流式的模型实例
            model = get_title_generation_llm()
            
            history_str = "\n".join([f"{type(msg).__name__}: {msg.content}" for msg in messages])
            
            chain = prompt | model
            title_response = await chain.ainvoke({"history": history_str})
            new_title = title_response.content.strip()

            # 4. 更新数据库中的标题
            if new_title:
                logger.info(f"Generated title for {thread_id}: '{new_title}'. Updating database.")
                await db_manager.update_conversation_title(thread_id, new_title)
            else:
                logger.warning(f"Failed to generate a valid title for conversation {thread_id}.")

    except Exception as e:
        logger.error(f"Error generating title for conversation {thread_id}: {e}", exc_info=True)
