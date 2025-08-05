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

# 通用的数据清洗函数
def _clean_for_json(data: Any) -> Any:
    """
    递归地清洗数据，将 LangChain/LangGraph 的特定对象转换为可序列化的字典或字符串。
    """
    if isinstance(data, dict):
        return {key: _clean_for_json(value) for key, value in data.items()}
    elif isinstance(data, list):
        return [_clean_for_json(item) for item in data]
    elif isinstance(data, BaseMessage):
        return {"role": data.type, "content": data.content}
    return data

@router.post("/aitest/stream")
async def chat_stream(fastapi_req: Request, request: ChatRequest = Body(...)):
    
    try:
        work_graph_app = fastapi_req.app.state.work_graph_app
        if not work_graph_app:
            raise HTTPException(status_code=503, detail="服务正在初始化，请稍后再试。")

        # 预先处理 thread_id 和 is_new_conversation
        thread_id = request.thread_id
        is_new_conversation = (thread_id is None or thread_id == "")

        if not is_new_conversation:
            # 仅为继续对话的情况做预先验证
            logger.info(f"Continuing test run for thread_id: {thread_id}")
            conv_meta = await db_manager.get_conversation_meta(thread_id)
            if not conv_meta or conv_meta.get('user_id') != request.user_id:
                 raise HTTPException(status_code=404, detail="对话未找到或无权访问。")

        async def event_stream():
            # 使用 nonlocal 来在内部函数中修改外部函数的变量
            nonlocal thread_id, is_new_conversation
            
            # 【核心修正】在 event_stream 内部处理输入和新对话的创建
            if is_new_conversation:
                logger.info(f"Starting new test run for user: {request.user_id}")
                new_conv = await db_manager.create_conversation_entry(request.user_id)
                thread_id = new_conv['thread_id']
                # 对于新对话，我们使用 create_initial_state 作为输入
                final_input = create_initial_state(request.message)
                
                # 在流的最开始，立即返回新创建的 thread_id
                yield f"data: {json.dumps({'type': 'init', 'thread_id': thread_id})}\n\n"
            else:
                # 对于继续的对话，我们只传递增量更新
                final_input = {
                    "user_input": request.message,
                    "messages": [HumanMessage(content=request.message)]
                }
                
            config = {"configurable": {"thread_id": thread_id}}

            # 【多事件处理逻辑 - 已包含】
            async for event in work_graph_app.astream_events(final_input, config, version="v2"):
                # print(f"\n[EVENT RECEIVED] ==> {event}\n") 

                kind = event["event"]
                name = event["name"]
                event_data = event.get("data", {})
                
                payload = {"node_or_tool_name": name}

                if kind == "on_chain_start":
                    if name not in ["LangGraph", "__start__", "router"]:
                        payload["type"] = "node_start"
                        logger.info(f"Node '{name}' started.")
                        yield f"data: {json.dumps(payload)}\n\n"

                elif kind == "on_chain_stream":
                    if name not in ["LangGraph", "__start__", "router"]:
                        chunk = event_data.get("chunk")
                        content_to_stream = ""
                        cleaned_chunk = _clean_for_json(chunk)
                        if isinstance(cleaned_chunk, dict):
                            messages = cleaned_chunk.get("messages", [])
                            if messages and isinstance(messages[-1], dict):
                                content_to_stream = messages[-1].get("content", "")
                        
                        if content_to_stream:
                            payload["type"] = "chunk"
                            payload["content"] = content_to_stream
                            logger.info(f"Streaming chunk from '{name}': {content_to_stream}")
                            yield f"data: {json.dumps(payload)}\n\n"

                elif kind == "on_chain_end":
                    if name not in ["LangGraph", "__start__", "router"]:
                        payload["type"] = "state"
                        payload["payload"] = _clean_for_json(event_data)
                        logger.info(f"Streaming state update from node '{name}'")
                        yield f"data: {json.dumps(payload)}\n\n"

                elif kind == "on_tool_start":
                    payload["type"] = "tool_start"
                    payload["input"] = _clean_for_json(event_data.get("input"))
                    logger.info(f"Tool '{name}' started.")
                    yield f"data: {json.dumps(payload)}\n\n"

                elif kind == "on_tool_end":
                    payload["type"] = "tool_end"
                    payload["output"] = _clean_for_json(event_data.get("output"))
                    logger.info(f"Tool '{name}' ended.")
                    yield f"data: {json.dumps(payload)}\n\n"

            # 【最终状态判断逻辑 - 保持不变】
            final_state = await work_graph_app.aget_state(config)
            logger.info(f"Stream loop finished. Final state is: {final_state}")

            if final_state.next:
                logger.info(f"Graph is interrupted, waiting to execute: {final_state.next}")
                yield f"data: {json.dumps({'type': 'wait_for_input'})}\n\n"
            else:
                logger.info("Graph has finished, reached END.")
                yield f"data: {json.dumps({'type': 'end'})}\n\n"
                asyncio.create_task(check_and_generate_title(thread_id))

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
            from models.dquestion import get_llm
            prompt = PromptTemplate.from_template(
                "根据以下对话内容，为其生成一个简洁的、不超过10个字的标题。\n\n对话内容:\n{history}\n\n标题:"
            )
            model = get_llm()
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