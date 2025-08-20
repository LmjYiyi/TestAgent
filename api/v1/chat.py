# 文件路径: api/v1/chat.py

from sched import Event
from fastapi import APIRouter, HTTPException, Body, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from typing import Optional, Any, Dict, List
import json
import asyncio

# --- 第一处修改：额外导入 AgentAction AgentFinish ---
from langchain_core.agents import AgentAction, AgentFinish 
# ---------------------------------------

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

# --- 第二处修改：更新这个函数 ---
def _clean_for_json(data: Any) -> Any:
    """
    递归地清洗数据，将 LangChain/LangGraph 的特定对象转换为可序列化的字典或字符串。
    """
    if isinstance(data, dict):
        return {key: _clean_for_json(value) for key, value in data.items()}
    elif isinstance(data, list):
        return [_clean_for_json(item) for item in data]
    elif isinstance(data, tuple):
        return tuple(_clean_for_json(item) for item in data)
    elif isinstance(data, BaseMessage):
        return {"role": data.type, "content": data.content}
    elif isinstance(data, AgentAction):
        return {
            "tool": data.tool,
            "tool_input": _clean_for_json(data.tool_input),
            "log": data.log
        }
    # --- 新增的逻辑：处理 AgentFinish ---
    elif isinstance(data, AgentFinish):
        return {
            "return_values": _clean_for_json(data.return_values),
            "log": data.log
        }
    # ------------------------------------
    return data
# ---------------------------------

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
            # 只转发我们定义的业务节点，避免 LangChain 内部 Runnable 节点造成重复
            allowed_nodes = {"LangGraph", "__start__", "router", "query_scene", "confirm_scene", "retrieve_steps", "confirm_steps", "execute_step", "handle_error", "finish"}

            async for event in work_graph_app.astream_events(final_input, config, version="v2"):
                #print(f"\n[EVENT RECEIVED] ==> {event}\n") 

                kind = event["event"]
                name = event["name"]
                event_data = event.get("data", {})
                
                # 清理整个 event_data，确保所有内容都是可序列化的
                cleaned_event_data = _clean_for_json(event_data)
                
                payload = {"node_or_tool_name": name}

                if kind == "on_chain_start":
                    if name in {"query_scene", "confirm_scene", "retrieve_steps", "confirm_steps", "execute_step", "handle_error", "finish"}:
                        payload["type"] = "node_start"
                        logger.info(f"Node '{name}' started.")
                        yield f"data: {json.dumps(payload)}\n\n"

                elif kind == "on_chain_stream":
                    if name in {"query_scene", "confirm_scene", "retrieve_steps", "confirm_steps", "execute_step", "handle_error", "finish"}:
                        # 为了保证先输出 Agent 过程，再输出步骤结果：
                        # 对 execute_step 节点不转发 chunk，只保留 on_chain_end 的 agent_process 与 state
                        if name == "execute_step":
                            continue
                        chunk = cleaned_event_data.get("chunk")
                        content_to_stream = ""
                        if isinstance(chunk, dict):
                            messages = chunk.get("messages", [])
                            if messages and isinstance(messages[-1], dict):
                                content_to_stream = messages[-1].get("content", "")
                        if content_to_stream:
                            payload["type"] = "chunk"
                            payload["content"] = content_to_stream
                            logger.info(f"Streaming chunk from '{name}': {content_to_stream}")
                            yield f"data: {json.dumps(payload)}\n\n"

                elif kind == "on_chain_end":
                    if name in {"query_scene", "confirm_scene", "retrieve_steps", "confirm_steps", "execute_step", "handle_error", "finish"}:
                        payload["type"] = "state"
                        payload["payload"] = cleaned_event_data
                        
                        # 只有execute_step节点才可能包含Agent执行过程信息
                        if name == "execute_step":
                            # 检查是否有完整的agent_result消息
                            messages = cleaned_event_data.get("messages", [])
                            if messages:
                                for msg in messages:
                                    if isinstance(msg, dict) and msg.get("content"):
                                        try:
                                            msg_content = json.loads(msg["content"])
                                            if msg_content.get("type") == "agent_result":
                                                # 立即发送agent_result消息，不等待所有步骤完成
                                                agent_result_payload = {
                                                    "node_or_tool_name": name, 
                                                    "type": "agent_result", 
                                                    "content": msg_content.get("content", ""),
                                                    "agent_process": msg_content.get("agent_process", "")
                                                }
                                                logger.info(f"Streaming agent result from '{name}'")
                                                yield f"data: {json.dumps(agent_result_payload)}\n\n"
                                                
                                                # 发送单独的agent_process消息
                                                if msg_content.get("agent_process"):
                                                    agent_process_payload = {
                                                        "node_or_tool_name": name, 
                                                        "type": "agent_process", 
                                                        "content": msg_content.get("agent_process", "")
                                                    }
                                                    logger.info(f"Streaming agent process from '{name}'")
                                                    yield f"data: {json.dumps(agent_process_payload)}\n\n"
                                                
                                                # 立即刷新，确保前端能实时显示
                                                yield f"data: {json.dumps({'type': 'flush'})}\n\n"
                                        except json.JSONDecodeError:
                                            continue
                        
                        # 处理finish节点的执行摘要
                        elif name == "finish":
                            # 检查是否有execution_summary消息
                            messages = cleaned_event_data.get("messages", [])
                            if messages:
                                for msg in messages:
                                    if isinstance(msg, dict) and msg.get("content"):
                                        try:
                                            msg_content = json.loads(msg["content"])
                                            if msg_content.get("type") == "execution_summary":
                                                # 发送execution_summary数据
                                                execution_summary_payload = {
                                                    "node_or_tool_name": name,
                                                    "type": "execution_summary",
                                                    "stepResults": msg_content.get("stepResults", []),
                                                    "finalSummary": msg_content.get("finalSummary", "")
                                                }
                                                logger.info(f"Streaming execution summary from '{name}'")
                                                yield f"data: {json.dumps(execution_summary_payload)}\n\n"
                                        except json.JSONDecodeError:
                                            continue
                        
                        logger.info(f"Streaming state update from node '{name}'")
                        yield f"data: {json.dumps(payload)}\n\n"

                elif kind == "on_tool_start":
                    payload["type"] = "tool_start"
                    payload["input"] = cleaned_event_data.get("input")
                    logger.info(f"Tool '{name}' started.")
                    yield f"data: {json.dumps(payload)}\n\n"

                elif kind == "on_tool_end":
                    payload["type"] = "tool_end"
                    payload["output"] = cleaned_event_data.get("output")
                    logger.info(f"Tool '{name}' ended.")
                    yield f"data: {json.dumps(payload)}\n\n"

            # 【最终状态判断逻辑 - 保持不变】
            final_state = await work_graph_app.aget_state(config)
            logger.info(f"Stream loop finished. Final state is: {final_state}")

            if final_state.next:
                logger.info(f"Graph is interrupted, waiting to execute: {final_state.next}")
            # 检查是否是execute_step的自动继续状态
                current_values = final_state.values
                if (current_values.get("current_stage") == "execute_step" and 
                    current_values.get("auto_continue") and
                    current_values.get("current_step", 0) < len(current_values.get("step_list", []))):
                    # 这是步骤执行中的自动继续，不需要用户输入
                    logger.info("Graph is in auto-continue mode for step execution")
                    yield f"data: {json.dumps({'type': 'auto_continue'})}\n\n"
                else:
                    # 真正需要用户输入的情况
                    yield f"data: {json.dumps({'type': 'wait_for_input'})}\n\n"
            else:
                logger.info("Graph has finished, reached END.")
                yield f"data: {json.dumps({'type': 'end'})}\n\n"
                asyncio.create_task(check_and_generate_title(thread_id))

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    except Exception as e:
        logger.error(f"Critical error in stream for request: {request.dict()}: {str(e)}", exc_info=True)
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
            try:
                title_response = await chain.ainvoke({"history": history_str})
                new_title = title_response.content.strip()

                if new_title:
                    logger.info(f"Generated title for {thread_id}: '{new_title}'. Updating database.")
                    await db_manager.update_conversation_title(thread_id, new_title)
                else:
                    logger.warning(f"Failed to generate a valid title for conversation {thread_id}.")
            except Exception as title_error:
                # 如果标题生成失败，使用默认标题
                logger.warning(f"Failed to generate title for conversation {thread_id}: {str(title_error)}")
                await db_manager.update_conversation_title(thread_id, "测试对话")

    except Exception as e:
        logger.error(f"Error generating title for conversation {thread_id}: {str(e)}", exc_info=True)