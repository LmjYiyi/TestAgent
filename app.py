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
    message: str

@app.post("/api/v1/chat/stream/{thread_id}")
async def chat_stream(thread_id: str, request_body: ChatRequest = Body(...)):
    user_id = "default-user"  # TODO: 从token中获取真实用户ID

    try:
        if thread_id == 'new':
            logger.info(f"Creating a new conversation for user: {user_id}")
            new_conv = await db_manager.create_conversation_entry(user_id=user_id)
            thread_id = new_conv['thread_id']
            logger.info(f"New conversation created with thread_id: {thread_id}")

        async def event_stream():
            # 将输入消息封装为LangChain的HumanMessage格式
            input_message = HumanMessage(content=request_body.message)
            # 配置，指定可中断的线程ID
            config = {"configurable": {"thread_id": thread_id}}

            # 使用 astream_events 流式获取事件
            async for event in agent_app.astream_events({"messages": [input_message]}, config, version="v1"):
                # 根据事件类型筛选或格式化
                event_name = event['event']
                if event_name in ["on_chat_model_stream"]:
                    chunk = event["data"].get("chunk")
                    if chunk and hasattr(chunk, 'content'):
                        yield f"data: {json.dumps({'type': 'chunk', 'content': chunk.content})}\n\n"
                elif event_name == 'on_tool_end':
                     yield f"data: {json.dumps({'type': 'tool_result', 'tool_name': event['name'], 'output': event['data'].get('output')})}\n\n"
            # 发送一个特殊的结束信号
            yield f"data: {json.dumps({'type': 'end'})}\n\n"
            # 在流结束后，检查是否需要生成标题
            asyncio.create_task(check_and_generate_title(thread_id))

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    except Exception as e:
        logger.error(f"Error in chat stream for thread {thread_id}: {e}", exc_info=True)
        # 根据thread_id是否已创建来决定返回的消息
        error_message = f"Failed to process message in conversation {thread_id}."
        if thread_id == 'new':
             error_message = "Failed to create a new conversation."
        return JSONResponse(status_code=500, content={"detail": error_message})


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
