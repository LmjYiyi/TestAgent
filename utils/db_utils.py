# 文件路径: utils/db_utils.py

import os
import asyncio
import json
import uuid
import uuid
from typing import Any, Dict, List, Optional

import aiomysql

import aiomysql
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.mysql.aio import AIOMySQLSaver


from utils.logger import logger

class DatabaseManager:

# 移除重复实例化：db_manager = DatabaseManager()
    """
    一个单例风格的类，用于封装和管理所有与数据库相关的操作，符合持久化需求文档。
    """
    """
    一个单例风格的类，用于封装和管理所有与数据库相关的操作。
    """
    _pool: aiomysql.Pool = None
    _checkpointer: AIOMySQLSaver = None

    async def initialize(self, drop_existing_tables=False):
        """
        初始化数据库连接池和LangGraph检查点，并根据需要创建核心表。

        Args:
            drop_existing_tables (bool): 如果为True，则在创建前会先删除已存在的表，用于测试环境重置。
        """
        if self._pool is not None:
            logger.warning("数据库管理器已初始化，跳过重复操作。")
            return
        logger.info("正在初始化数据库管理器...")
        try:
            db_config = {
                "host": os.getenv("MYSQL_HOST", "localhost"),
                "port": int(os.getenv("MYSQL_PORT", 3308)),
                "user": os.getenv("MYSQL_USER", "root"),
                "password": os.getenv("MYSQL_PASSWORD", "1234"),
                "db": os.getenv("MYSQL_DATABASE", "langgraph_db"),
                "autocommit": True
            }
            self._pool = await aiomysql.create_pool(**db_config)
            self._checkpointer = AIOMySQLSaver(self._pool)

            # 1. 设置LangGraph的checkpoints表
            await self._checkpointer.setup() 

            # 2. 创建自定义的元数据和反馈表
            await self._create_custom_tables(drop_existing=drop_existing_tables)

            logger.info("数据库管理器初始化并成功设置所有必需的表。")
        except Exception as e:
            logger.error(f"无法初始化数据库管理器: {e}", exc_info=True)
            raise

    def get_checkpointer(self) -> BaseCheckpointSaver:
        if self._checkpointer is None:
            raise RuntimeError("数据库管理器尚未初始化。")
        return self._checkpointer

    async def close(self):
        if self._pool:
            logger.info("正在关闭数据库连接池...")
            self._pool.close()
            await self._pool.wait_closed()
            logger.info("数据库连接池已关闭。")
            self._pool = None
            self._checkpointer = None

    async def _create_custom_tables(self, drop_existing: bool = False):
        """检查并创建 conversations 和 message_feedback 表。"""
        if self._pool is None: raise RuntimeError("数据库管理器尚未初始化。")

        async with self._pool.acquire() as conn:
            async with conn.cursor() as cursor:
                if drop_existing:
                    await cursor.execute("DROP TABLE IF EXISTS message_feedback, conversations;")
                    logger.warning("已删除 'conversations' 和 'message_feedback' 表。")

                # 创建 conversations 表
                sql_create_conversations = """
                CREATE TABLE IF NOT EXISTS conversations (
                    thread_id VARCHAR(255) NOT NULL PRIMARY KEY,
                    user_id VARCHAR(255) NOT NULL,
                    title VARCHAR(255) NOT NULL,
                    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
                    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
                    is_deleted BOOLEAN DEFAULT FALSE,
                    share_id VARCHAR(36) UNIQUE DEFAULT NULL,
                    KEY user_id_idx (user_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """
                await cursor.execute(sql_create_conversations)
                logger.info("已确保 'conversations' 表存在。")

                # 创建 message_feedback 表
                sql_create_feedback = """
                CREATE TABLE IF NOT EXISTS message_feedback (
                    feedback_id VARCHAR(36) NOT NULL PRIMARY KEY,
                    thread_id VARCHAR(255) NOT NULL,
                    message_id VARCHAR(36) NOT NULL, 
                    user_id VARCHAR(255) NOT NULL,
                    rating INT NOT NULL,
                    comment TEXT,
                    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
                    KEY thread_message_idx (thread_id, message_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """
                await cursor.execute(sql_create_feedback)
                logger.info("已确保 'message_feedback' 表存在。")

    # --- 功能 1: 创建新会话 ---
    async def create_conversation_entry(self, user_id: str) -> Dict[str, Any]:
        if self._pool is None: raise RuntimeError("数据库管理器尚未初始化。")
        
        thread_id = f"{user_id}@@{uuid.uuid4().hex}"
        initial_title = "新对话"
        
        sql = """INSERT INTO conversations (thread_id, user_id, title) 
                 VALUES (%s, %s, %s)"""
        
        try:
            async with self._pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(sql, (thread_id, user_id, initial_title))
            
            # 获取刚刚插入的数据以返回给前端
            conversation_data = await self.get_conversation_meta(thread_id)
            logger.info(f"为用户 {user_id} 成功创建新的对话记录: {thread_id}")
            return conversation_data
        except Exception as e:
            logger.error(f"为用户 {user_id} 创建对话条目时失败: {e}", exc_info=True)
            raise

    # --- 功能 2: 获取历史会话列表 ---
    async def list_conversations(self, user_id: str) -> List[Dict[str, Any]]:
        if self._pool is None: raise RuntimeError("数据库管理器尚未初始化。")
        logger.info(f"正在为用户 {user_id} 从 'conversations' 表查询历史列表...")
        
        sql = """SELECT thread_id, title, updated_at 
                 FROM conversations 
                 WHERE user_id = %s AND is_deleted = FALSE 
                 ORDER BY updated_at DESC;"""
        
        try:
            async with self._pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(sql, (user_id,))
                    conversations = await cursor.fetchall()
                    logger.info(f"为用户 {user_id} 找到 {len(conversations)} 条对话记录。")
                    # 将 datetime 对象转换为 ISO 格式字符串以便 JSON 序列化
                    for conv in conversations:
                        conv['updated_at'] = conv['updated_at'].isoformat()
                    return conversations
        except Exception as e:
            logger.error(f"从 'conversations' 表查询用户 {user_id} 的列表时出错: {e}", exc_info=True)
            return []

    # --- 辅助方法: 获取单条对话元数据 ---
    async def get_conversation_checkpoint(self, thread_id: str) -> Optional[Dict[str, Any]]:
        if self._checkpointer is None: raise RuntimeError("数据库管理器尚未初始化。")
        config = {"configurable": {"thread_id": thread_id}}
        logger.info(f"查询检查点的配置: {config}")  # 添加配置日志
        try:
            checkpoint = await self._checkpointer.get(config)
            logger.info(f"检查点原始数据: {checkpoint}")  # 添加返回数据日志
            logger.info(f"成功获取 thread_id {thread_id} 的检查点。")
            return checkpoint
        except Exception as e:
            logger.error(f"获取 thread_id {thread_id} 的检查点时出错: {e}", exc_info=True)
            return None

    async def get_conversation_meta(self, thread_id: str) -> Optional[Dict[str, Any]]:
        if self._pool is None: raise RuntimeError("数据库管理器尚未初始化。")
        sql = "SELECT * FROM conversations WHERE thread_id = %s;"
        try:
            async with self._pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(sql, (thread_id,))
                    return await cursor.fetchone()
        except Exception as e:
            logger.error(f"获取 thread_id {thread_id} 的元数据时出错: {e}", exc_info=True)
            return None

    # --- 功能 4: 更新对话标题 ---
    async def update_conversation_title(self, thread_id: str, new_title: str) -> bool:
        if self._pool is None: raise RuntimeError("数据库管理器尚未初始化。")
        
        sql = "UPDATE conversations SET title = %s WHERE thread_id = %s"
        
        try:
            async with self._pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    result = await cursor.execute(sql, (new_title, thread_id))
                    # result 是受影响的行数
                    if result > 0:
                        logger.info(f"thread_id {thread_id} 的标题已成功更新为: {new_title}")
                        return True
                    else:
                        logger.warning(f"尝试更新 thread_id {thread_id} 的标题，但未找到匹配的记录。")
                        return False
        except Exception as e:
            logger.error(f"更新 thread_id {thread_id} 的标题时出错: {e}", exc_info=True)
            return False

    # --- 功能 5: 逻辑删除对话 ---
    async def delete_conversation_logically(self, thread_id: str) -> bool:
        if self._pool is None: raise RuntimeError("数据库管理器尚未初始化。")
        
        sql = "UPDATE conversations SET is_deleted = TRUE WHERE thread_id = %s"
        
        try:
            async with self._pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    result = await cursor.execute(sql, (thread_id,))
                    if result > 0:
                        logger.info(f"已逻辑删除对话: {thread_id}")
                        return True
                    else:
                        logger.warning(f"尝试逻辑删除 thread_id {thread_id}，但未找到匹配的记录。")
                        return False
        except Exception as e:
            logger.error(f"逻辑删除 thread_id {thread_id} 时出错: {e}", exc_info=True)
            return False

    # --- 功能 6: 创建消息反馈 ---
    async def create_message_feedback(self, feedback_data: Dict[str, Any]) -> str:
        if self._pool is None: raise RuntimeError("数据库管理器尚未初始化。")
        
        feedback_id = str(uuid.uuid4())
        sql = """INSERT INTO message_feedback (feedback_id, thread_id, message_id, user_id, rating, comment)
                 VALUES (%s, %s, %s, %s, %s, %s)"""
        
        try:
            async with self._pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(sql, (
                        feedback_id,
                        feedback_data['thread_id'],
                        feedback_data['message_id'],
                        feedback_data['user_id'],
                        feedback_data['rating'],
                        feedback_data.get('comment')
                    ))
            logger.info(f"成功为消息 {feedback_data['message_id']} 创建反馈记录，ID: {feedback_id}")
            return feedback_id
        except Exception as e:
            logger.error(f"为消息 {feedback_data['message_id']} 创建反馈时出错: {e}", exc_info=True)
            raise


    async def get_conversation_checkpoint(self, thread_id: str) -> Optional[Dict[str, Any]]:
        if self._checkpointer is None:
            raise RuntimeError("数据库管理器尚未初始化。")
        try:
            config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
            return await self._checkpointer.aget(config)
        except Exception as e:
            logger.error(f"为 thread_id {thread_id} 获取历史记录时出错: {e}")
            return None




# =======================================================
# ==              独立的测试模块                       ==
# =======================================================

db_manager = DatabaseManager()
if __name__ == "__main__":
    import sys
    from pathlib import Path
    from langchain_core.messages import HumanMessage, AIMessage

    # ... (sys.path 设置) ...
    from workflows.graph_builder import build_graph

    async def perform_integration_tests():
        print("\n[步骤 1/3] 构建测试用的LangGraph工作流...")
        checkpointer = db_manager.get_checkpointer()
        work_graph = await build_graph(checkpointer=checkpointer)
        print("✅ 测试工作流构建成功。")

        print("\n[步骤 2/3] 模拟用户与工作流的真实交互...")
        TEST_USER_ID = f"test-user-{uuid.uuid4().hex[:6]}"
        print(f"  -> 使用临时测试用户ID: {TEST_USER_ID}")

        # --- 这是核心修改：定义一个符合新 AgentState 的初始状态 ---
        def get_initial_state(user_input: str) -> dict:
            # 初始状态现在包含一个 HumanMessage
            return {
                "messages": [HumanMessage(content=user_input)],
                "user_input": user_input,
                # 其他字段也需要初始化
                "current_stage": "choose_scene",
                "pending_action": None,
                "user_confirmed": None,
                "api_list": [],
                "selected_scene": None,
                "origin_step_list": [],
                "step_list": [],
                "current_step": 0,
                "step_outputs": [],
                "step_results": [],
                "error_message": None,
                "retry_payload": None,
                "output": ""
            }

        # --- 对话A ---
        thread_a_id = f"{TEST_USER_ID}@@conv-a"
        config_a = {"configurable": {"thread_id": thread_a_id}}
        
        print(f"  -> 正在为对话A (thread_id: {thread_a_id}) 发送第一条消息...")
        initial_state_a = get_initial_state("你好，这是对话A")
        final_state_a1 = await work_graph.ainvoke(initial_state_a, config_a)
        print(f"  -> 对话A第一轮交互完成。")
        
        # 模拟第二轮交互
        await asyncio.sleep(0.1)
        print(f"  -> 正在为对话A发送第二条消息...")
        # 后续调用，我们传入新的用户输入，并将其包装成 HumanMessage
        # LangGraph 会自动将其追加到历史记录中
        final_state_a2 = await work_graph.ainvoke(
            {"messages": [HumanMessage(content="这是对话A的第二轮交互")], "user_input": "这是对话A的第二轮交互"},
            config_a
        )
        print(f"  -> 对话A第二轮交互完成。")

        # ... (对话B的逻辑类似) ...

        print(f"\n[步骤 3/3] 验证数据库中的持久化数据...")
        
        print(f"  -> 测试 get_conversation_checkpoint(thread_id='{thread_a_id}')...")
        checkpoint_data = await db_manager.get_conversation_checkpoint(thread_a_id)
        assert checkpoint_data is not None, "未能获取到对话A的检查点"
        print(f"  -> 获取到的checkpoint: {checkpoint_data}")
        # 验证恢复的 messages 是否包含了所有交互
        retrieved_messages = checkpoint_data['channel_values']['messages']
        print(f"  -> 获取到的历史消息数量: {len(retrieved_messages)}")
        print(f"  -> 获取到的历史消息: {retrieved_messages}")
        # 期望的消息顺序：Human, AI, Human, AI...
        # 具体的数量和内容取决于你的图的完整流程
        # 让我们做一个简单的检查：历史记录不为空，且最后一条是AIMessage
        assert len(retrieved_messages) > 1, "历史记录不完整"
        assert isinstance(retrieved_messages[0], HumanMessage), "第一条消息不是HumanMessage"
        assert isinstance(retrieved_messages[-1], AIMessage), "最后一条消息不是AIMessage"
        print(f"  -> 最后一条AI回复: {retrieved_messages[-1].content}")
        print("✅ 单个对话内容查询与最终状态一致。")


    async def main_test_runner():
        print("\n--- [DB UTILS] 开始模块集成测试 ---")
        try:
            await db_manager.initialize()
            print("✅ 初始化成功。")
            await perform_integration_tests()
            print("\n--- [DB UTILS] 所有测试已成功完成！ ---")
        except Exception as e:
            print(f"\n❌ 测试过程中发生未处理的异常: {e}")
            import traceback
            traceback.print_exc()
        finally:
            await db_manager.close()
            print("✅ 资源已关闭。")

    asyncio.run(main_test_runner())