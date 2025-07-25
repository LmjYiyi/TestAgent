from fastapi import APIRouter, HTTPException, Depends, Path, Body
from typing import List, Dict, Any

from utils.db_utils import DatabaseManager
from agent.graph import build_graph
from langchain_core.messages import HumanMessage
from utils.logger import setup_logger

logger = setup_logger()
router = APIRouter()

from utils.db_utils import db_manager

@router.post("/aitest/create", 
              summary="创建一个新的空对话",
              response_model=Dict[str, Any])
async def create_new_conversation(user_id: str):
    """
    为指定用户创建一个新的对话，并返回新对话的元数据。
    """
    try:
        logger.info(f"收到为用户 {user_id} 创建新对话的请求。")
        new_conversation = await db_manager.create_conversation_entry(user_id)
        return new_conversation
    except Exception as e:
        logger.error(f"创建新对话时发生意外错误: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误，无法创建新对话。")

@router.get("/aitest/getList/{user_id}", 
             summary="获取指定用户的历史对话列表",
             response_model=List[Dict[str, Any]])
async def get_user_conversations(
    user_id: str = Path(..., description="用户的唯一标识符")
):
    """
    获取指定用户的所有未删除对话，按更新时间降序排列。
    """
    try:
        logger.info(f"正在为用户 {user_id} 获取历史对话列表。")
        conversations = await db_manager.list_conversations(user_id)
        return conversations
    except Exception as e:
        logger.error(f"为用户 {user_id} 获取对话列表时出错: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误，无法获取对话列表。")

# @router.get("/aitest/selectSession/{thread_id}",
#             summary="加载完整的state",
#             response_model=Dict[str, Any])
# async def get_state(
#     thread_id: str = Path(..., description="对话的唯一线程ID")
# ):
#     """
#     根据thread_id从checkpoints表中获取并返回一个对话的完整消息历史记录。
#     """
#     try:
#         logger.info(f"正在为 thread_id {thread_id} 加载state。")
#         checkpoint = await db_manager.get_conversation_checkpoint(thread_id)
#         if not checkpoint:
#             raise HTTPException(status_code=404, detail="state未找到。")

#         # LangChain的消息对象需要被序列化为字典
#         state = checkpoint.get("channel_values", {})

        
#         return state
#     except HTTPException as he:
#         # Re-raise HTTPException to preserve status code and detail
#         raise he
#     except Exception as e:
#         logger.error(f"为 thread_id {thread_id} 加载state时出错: {e}", exc_info=True)
#         raise HTTPException(status_code=500, detail="内部服务器错误，加载state失败。")

@router.get("/aitest/getState/{thread_id}",
            summary="获取完整state",
            response_model=Dict[str, Any])
async def get_full_state(
    thread_id: str = Path(..., description="对话的唯一线程ID")
):
    """
    根据thread_id从checkpoints表中获取并返回包含自定义数据的完整对话状态。
    """
    try:
        logger.info(f"正在为 thread_id {thread_id} 获取完整state。")
        checkpoint = await db_manager.get_conversation_checkpoint(thread_id)
        if not checkpoint:
            raise HTTPException(status_code=404, detail="state未找到。")

        # 提取包含自定义数据的channel_values
        state = checkpoint.get("channel_values", {})

        # 序列化LangChain消息对象和其他可能的非序列化数据
        if "messages" in state:
            state["messages"] = [message.dict() for message in state["messages"]]

        return state
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"获取 thread_id {thread_id} 的完整state时出错: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误，获取state失败。")


@router.get("/aitest/selectSession/{thread_id}",
            summary="获取单个对话的历史记录",
            response_model=List[Dict[str, Any]])
async def get_single_conversation_history(
    thread_id: str = Path(..., description="对话的唯一线程ID")
):
    """
    根据thread_id从checkpoints表中获取并返回一个对话的完整消息历史记录。
    """
    try:
        logger.info(f"正在为 thread_id {thread_id} 加载对话内容。")
        checkpoint = await db_manager.get_conversation_checkpoint(thread_id)
        if not checkpoint:
            raise HTTPException(status_code=404, detail="对话内容未找到。")

        # LangChain的消息对象需要被序列化为字典
        messages = checkpoint.get("channel_values", {}).get("messages", [])
        history = []
        for msg in messages:
            history.append({
                "id": getattr(msg, 'id', None),
                "role": getattr(msg, 'type', 'unknown'),
                "content": getattr(msg, 'content', ''),
            })
        
        return history
    except HTTPException as he:
        # Re-raise HTTPException to preserve status code and detail
        raise he
    except Exception as e:
        logger.error(f"为 thread_id {thread_id} 加载对话内容时出错: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误，加载对话内容失败。")

@router.put("/aitest/updateTitle/{thread_id}", 
             summary="更新对话标题",
             response_model=Dict[str, str])
async def update_conversation_title(
    thread_id: str = Path(..., description="对话的唯一线程ID"),
    new_title: str = Body(..., embed=True)
):
    """
    更新指定对话的标题。
    """
    try:
        logger.info(f"正在为 thread_id {thread_id} 更新标题为: {new_title}。")
        success = await db_manager.update_conversation_title(thread_id, new_title)
        if not success:
            raise HTTPException(status_code=404, detail="对话未找到或标题更新失败。")
        return {"message": "标题更新成功。"}
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"为 thread_id {thread_id} 更新标题时出错: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误，更新标题失败。")

# @router.post("/aitest/chat", 
#              summary="发送非流式聊天消息",
#              response_model=Dict[str, Any])
# async def send_non_stream_message(
#     thread_id: str = Path(..., description="对话的唯一线程ID"),
#     message: str = Body(..., embed=True)
# ):
#     """
#     发送非流式聊天消息并获取完整响应。
#     """
#     try:
#         logger.info(f"为 thread_id {thread_id} 处理非流式消息: {message}")
        
#         # 获取检查点
#         checkpointer = db_manager.get_checkpointer()
        
#         # 构建图
#         app = build_graph(checkpointer=checkpointer)
        
#         # 准备配置
#         config = {"configurable": {"thread_id": thread_id}}
        
#         # 发送消息
#         final_state = await app.ainvoke(
#             {"messages": [HumanMessage(content=message)]},
#             config
#         )
        
#         # 返回完整响应
#         return {
#             "thread_id": thread_id,
#             "message": final_state["messages"][-1].content,
#             "status": "completed"
#         }
#     except Exception as e:
#         logger.error(f"处理非流式消息时出错: {e}", exc_info=True)
#         raise HTTPException(status_code=500, detail="处理消息失败")


@router.delete("/aitest/deleteSession/{thread_id}", 
               summary="逻辑删除一个对话",
               response_model=Dict[str, str])
async def delete_conversation(
    thread_id: str = Path(..., description="要删除的对话的唯一线程ID")
):
    """
    将指定对话标记为已删除，但保留数据以备将来恢复。
    """
    try:
        logger.info(f"正在逻辑删除对话: {thread_id}")
        success = await db_manager.delete_conversation_logically(thread_id)
        if not success:
            raise HTTPException(status_code=404, detail="对话未找到或删除失败。")
        return {"message": "对话已成功删除。"}
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"删除对话 {thread_id} 时出错: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误，删除对话失败。")