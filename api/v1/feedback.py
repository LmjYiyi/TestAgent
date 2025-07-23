# 文件路径: api/v1/feedback.py

from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel, Field
from typing import Dict, Optional

from utils.db_utils import DatabaseManager, db_manager
from utils.logger import setup_logger

logger = setup_logger()
router = APIRouter()

class FeedbackPayload(BaseModel):
    thread_id: str = Field(..., description="对话的唯一线程ID")
    message_id: str = Field(..., description="消息的唯一ID")
    user_id: str = Field(..., description="用户的唯一标识符")
    rating: int = Field(..., ge=1, le=5, description="评分，范围从1到5")
    comment: Optional[str] = Field(None, description="用户的文字反馈")

def get_db_manager():
    return db_manager

@router.post("/", 
             summary="接收并存储用户对某条消息的反馈",
             response_model=Dict[str, str])
async def submit_feedback(
    payload: FeedbackPayload = Body(...),
    db: DatabaseManager = Depends(get_db_manager)
):
    """
    接收用户对特定消息的反馈（评分和评论）并将其存储到数据库中。
    """
    try:
        feedback_id = await db.create_message_feedback(payload.dict())
        logger.info(f"成功存储了对消息 {payload.message_id} 的反馈，ID为: {feedback_id}")
        return {"message": "反馈已成功提交。", "feedback_id": feedback_id}
    except Exception as e:
        logger.error(f"存储对消息 {payload.message_id} 的反馈时出错: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误，无法提交反馈。")