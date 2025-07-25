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
from api.v1 import conversation as conversation_v1, feedback as feedback_v1,chat as chat_v1
from utils.db_utils import db_manager
from utils.logger import setup_logger
from agent.graph import build_graph, workflow
from fastapi.responses import JSONResponse
from workflows.graph_builder import build_graph
logger = setup_logger('INFO')

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Application startup...")
    await db_manager.initialize()
    logger.info("Database initialized.")
    checkpointer = db_manager.get_checkpointer()
    work_graph = await build_graph(checkpointer=checkpointer)
    # 构建带有检查点的LangGraph
    # 将 work_graph 实例存入 app.state 
    app.state.work_graph_app = work_graph
    logger.info("LangGraph Workflow built and stored in app.state.")
    
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
app.include_router(chat_v1.router, prefix="/api/v1/chat", tags=["Chat"])







