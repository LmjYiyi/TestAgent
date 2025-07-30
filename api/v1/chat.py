# 文件路径: api/v1/chat.py

from sched import Event
from fastapi import APIRouter, HTTPException, Body, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from typing import Optional, Any, Dict, List
import json
import asyncio

from langchain_core.messages import HumanMessage, AIMessage,BaseMessage
from langchain_core.prompts import PromptTemplate

from utils.logger import setup_logger
from utils.db_utils import db_manager
from models.dquestion import get_llm

from workflows.graph_builder import AgentState, create_initial_state

# 只初始化一次 logger
logger = setup_logger('INFO')
router = APIRouter()

class ChatRequest(BaseModel):
    user_id: str 
    thread_id: Optional[str] = None
    message: str

@router.post("/aitest/stream")
async def chat_stream(fastapi_req: Request, request: ChatRequest = Body(...)):
    
    try:
        work_graph_app = fastapi_req.app.state.work_graph_app
        if not work_graph_app:
            raise HTTPException(status_code=503, detail="服务正在初始化，请稍后再试。")

        current_thread_id = request.thread_id
        is_new_conversation = (current_thread_id is None)

        if is_new_conversation:
            logger.info(f"Starting new test run for user: {request.user_id}")
            new_conv = await db_manager.create_conversation_entry(request.user_id)
            current_thread_id = new_conv['thread_id']
            # 为新对话创建完整的初始状态
            initial_input = create_initial_state(request.message)
        else:
            logger.info(f"Continuing test run for thread_id: {current_thread_id}")
            conv_meta = await db_manager.get_conversation_meta(current_thread_id)
            if not conv_meta or conv_meta.get('user_id') != request.user_id:
                 raise HTTPException(status_code=404, detail="对话未找到或无权访问。")
            # 对于已有对话，只需提供增量输入
            initial_input = {
                "messages": [HumanMessage(content=request.message)],
                "user_input": request.message
            }

        async def event_stream():
            if is_new_conversation:
                yield f"data: {json.dumps({'type': 'init', 'thread_id': current_thread_id})}\n\n"

            config = {"configurable": {"thread_id": current_thread_id}}

            async for event in work_graph_app.astream_events(initial_input, config, version="v2"):
                # print(f"\n[EVENT RECEIVED] ==> {event}\n") 
                #event结构
                kind = event["event"]
                
                if kind == "on_chain_end":
                    node_name = event["name"]
                    if node_name not in ["LangGraph", "__start__", "router"]:
                        event_data = event.get("data", {})
                
                        if isinstance(event_data, dict):
                            # 创建一个列表，包含所有可能含有 messages 的部分
                            parts_to_clean = []
                            if "input" in event_data and isinstance(event_data["input"], dict):
                                parts_to_clean.append(event_data["input"])
                            if "output" in event_data and isinstance(event_data["output"], dict):
                                parts_to_clean.append(event_data["output"])

                            # 遍历这些部分，对它们各自的 messages 列表进行清洗
                            for part in parts_to_clean:
                                if "messages" in part and isinstance(part["messages"], list):
                                        part["messages"] = [
                                            {"role": msg.type, "content": msg.content} 
                                            for msg in part["messages"] 
                                            if isinstance(msg, BaseMessage)
                                        ]
                            
                            logger.info(f"Streaming state update from node '{node_name}:{event_data}'") 
                            
                            # 4. 现在，整个 event_data 对象都已经是可序列化的了
                            yield f"data: {json.dumps({'type': 'state', 'node': node_name, 'payload': event_data},ensure_ascli=False)}\n\n"
            
            # 循环结束后，检查图的最终状态 
            final_state = await work_graph_app.aget_state(config)
            logger.info(f"Stream loop finished. Final state is: {final_state}")

            if final_state.next:
                logger.info(f"Graph is interrupted, waiting to execute: {final_state.next}")
                yield f"data: {json.dumps({'type': 'wait_for_input'})}\n\n"
            else:
                logger.info("Graph has finished, reached END.")
                yield f"data: {json.dumps({'type': 'end'})}\n\n"
                #生成标题
                # asyncio.create_task(check_and_generate_title(current_thread_id))

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    except Exception as e:
        logger.error(f"Critical error in stream for request: {request.dict()}: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"detail": f"处理消息时发生内部错误: {str(e)}"})



async def check_and_generate_title(thread_id: str):
    try:
        conv_meta = await db_manager.get_conversation_meta(thread_id)
        if conv_meta and conv_meta.get('title') and conv_meta['title'] != '新对话':
            logger.info(f"Conversation {thread_id} already has a title: {conv_meta['title']}")
            return

        checkpoint = await db_manager.get_conversation_checkpoint(thread_id)
        if not checkpoint or not checkpoint.get('channel_values', {}).get('messages'):
            logger.info(f"No messages in conversation {thread_id} to generate a title.")
            return

        messages = checkpoint['channel_values']['messages']
        if len(messages) >= 2:
            logger.info(f"Generating title for conversation {thread_id}...")
            
            from langchain_core.prompts import PromptTemplate
            from models.dquestion import get_title_generation_llm
            prompt = PromptTemplate.from_template(
                "根据以下对话内容，为其生成一个简洁的、不超过10个字的标题。\n\n对话内容:\n{history}\n\n标题:"
            )
            model = get_title_generation_llm()
            history_str = "\n".join([f"{type(msg).__name__}: {msg.content}" for msg in messages])
            chain = prompt | model
            title_response = await chain.ainvoke({"history": history_str})
            new_title = title_response.content.strip()

            if new_title:
                logger.info(f"Generated title for {thread_id}: '{new_title}'. Updating database.")
                await db_manager.update_conversation_title(thread_id, new_title)
            else:
                logger.warning(f"Failed to generate a valid title for conversation {thread_id}.")

    except Exception as e:
        logger.error(f"Error generating title for conversation {thread_id}: {e}", exc_info=True)