from fastapi import APIRouter, HTTPException, Depends, Path, Body, Request
from typing import List, Dict, Any
import json
from utils.db_utils import DatabaseManager
from workflows.graph_builder import create_initial_state
from langchain_core.messages import HumanMessage
from utils.logger import setup_logger
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
from typing import Optional
from utils.db_utils import db_manager
from fastapi.responses import JSONResponse, StreamingResponse
import asyncio
logger = setup_logger('INFO')

logger = setup_logger()
router = APIRouter()






class ChatRequest(BaseModel):
    # 前端直接传递 user_id
    user_id: str 
    # thread_id 是可选的。前端不传或传 null，代表是新对话。
    thread_id: Optional[str] = None
    message: str

@router.post("/aitest/stream")
async def chat_stream(fastapi_req: Request, request: ChatRequest = Body(...)):
    """
    统一的流式聊天接口。
    - 如果请求中不包含 thread_id，则创建新对话。
    - 如果包含 thread_id，则继续现有对话。
    """
    try:
        work_graph_app = fastapi_req.app.state.work_graph_app
        if not work_graph_app:
            raise HTTPException(status_code=503, detail="服务正在初始化，请稍后再试。")

        current_thread_id = request.thread_id
        is_new_conversation = (current_thread_id is None)

        if is_new_conversation:
            # 这一部分逻辑现在只负责创建元数据，因为状态是由聊天驱动的
            logger.info(f"thread_id is null, creating new conversation for user: {request.user_id}")
            new_conv = await db_manager.create_conversation_entry(request.user_id)
            current_thread_id = new_conv['thread_id']
            logger.info(f"New conversation created with thread_id: {current_thread_id}")
        else:
            logger.info(f"Continuing conversation for thread_id: {current_thread_id}")
            conv_meta = await db_manager.get_conversation_meta(current_thread_id)
            if not conv_meta or conv_meta.get('user_id') != request.user_id:
                 raise HTTPException(status_code=404, detail="对话未找到或无权访问。")

        async def event_stream():
            if is_new_conversation:
                init_event = {"type": "init", "thread_id": current_thread_id}
                yield f"data: {json.dumps(init_event)}\n\n"

            config = {"configurable": {"thread_id": current_thread_id}}

            if is_new_conversation:
                # 对于新对话，调用create_initial_state函数创建完整的初始状态
                # 对于新对话，调用crea函数创建完整的初始状态
                logger.info("This is a new conversation. Creating full initial state using blueprint.")
                input = create_initial_state(request.message)
            else:
                # 对于已有对话，checkpointer会从数据库加载历史状态，
                # 我们只需提供新的消息和输入即可。
                logger.info("This is an existing conversation. Providing only new messages and user_input.")
                input = {
                    "messages": [HumanMessage(content=request.message)],
                    "user_input": request.message
                }
            # -----------------------------------

            # 使用构建好的input 来调用图
            async for event in work_graph_app.astream_events(input, config, version="v1"):
                event_name = event['event']
                # 这里可以根据你的图的输出节点来决定返回什么内容
                # 为了简单起见，我们假设最终输出在 AIMessage 的 content 中
                if event_name == "on_chat_model_stream":
                    chunk = event["data"].get("chunk")
                    if chunk and hasattr(chunk, 'content'):
                        yield f"data: {json.dumps({'type': 'chunk', 'content': chunk.content})}\n\n"
                elif event_name == 'on_tool_end':
                     yield f"data: {json.dumps({'type': 'tool_result', 'tool_name': event['name'], 'output': event['data'].get('output')})}\n\n"
                elif event.get('name') == 'finish' and event['event'] == 'on_chain_end':
                     # 当你的 finish 节点结束时，可以从它的输出中获取最终摘要
                     final_output = event['data'].get('output', {}).get('output', '')
                     if final_output:
                         yield f"data: {json.dumps({'type': 'final_summary', 'content': final_output})}\n\n"


            yield f"data: {json.dumps({'type': 'end'})}\n\n"
            
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