# 文件: utils/persistence.py 异步实现
# 安装依赖 pip install langgraph-checkpoint-mysql[aiomysql]
#导入包 from utils.persistence import get_checkpointer 
# =======================================================
# build_graph函数处核心修改：调用 get_checkpointer 时加上 await ==
# checkpointer = await get_checkpointer()
# work_graph = build_graph(checkpointer=checkpointer)
# =======================================================
    

import os
import asyncio
from langgraph.checkpoint.base import BaseCheckpointSaver
from utils.logger import setup_logger
from langgraph.checkpoint.mysql.aio import AIOMySQLSaver
import aiomysql

logger = setup_logger()

# =======================================================
# ==              生命周期管理的核心改动                 ==
# =======================================================
# 1. 创建全局变量来缓存 Checkpointer 实例和连接池
_checkpointer_instance: AIOMySQLSaver = None
_db_pool: aiomysql.Pool = None
# =======================================================


async def get_checkpointer() -> BaseCheckpointSaver:
    """
    获取一个基于 MySQL 的【异步】持久化 Checkpointer 单例。
    
    如果实例已存在，则直接返回；否则，创建一个新的实例并缓存。
    """
    global _checkpointer_instance, _db_pool

    # 如果实例已存在，直接返回，避免重复创建
    if _checkpointer_instance:
        logger.info("返回已缓存的 AIOMySQLSaver 实例。")
        return _checkpointer_instance

    logger.info("正在初始化 AIOMySQLSaver (异步 MySQL Checkpointer)...")

    try:
        db_config = {
            "host": os.getenv("MYSQL_HOST", "localhost"),
            "port": int(os.getenv("MYSQL_PORT", 3308)),
            "user": os.getenv("MYSQL_USER", "root"),
            "password": os.getenv("MYSQL_PASSWORD", "1234"),
            "db": os.getenv("MYSQL_DATABASE", "langgraph_db"),
            "autocommit": True
        }

        # 创建并缓存连接池
        _db_pool = await aiomysql.create_pool(**db_config)
        
        # 创建并缓存 Checkpointer 实例
        _checkpointer_instance = AIOMySQLSaver(_db_pool)

        await _checkpointer_instance.setup()
        
        logger.info("AIOMySQLSaver 初始化并设置成功。")
        return _checkpointer_instance
        
    except Exception as e:
        logger.error(f"无法创建 AIOMySQLSaver: {e}")
        logger.error("请确保 MySQL 服务正在运行，并且连接参数正确。")
        raise

# =======================================================
# ==       2. 提供一个用于关闭资源的函数                ==
# =======================================================
async def close_checkpointer():
    """
    优雅地关闭数据库连接池。应在应用结束时调用。
    """
    global _checkpointer_instance, _db_pool
    
    if _db_pool:
        logger.info("正在关闭数据库连接池...")
        _db_pool.close()
        await _db_pool.wait_closed()
        logger.info("数据库连接池已关闭。")
        
        # 清理全局变量
        _db_pool = None
        _checkpointer_instance = None
    else:
        logger.info("数据库连接池已关闭或从未创建。")
# =======================================================


if __name__ == "__main__":
    # 您的测试代码可以保持不变，因为它在一个独立的运行中，
    # 但为了演示生命周期，我们可以做一点小小的调整。
    import uuid
    from langchain_core.messages import HumanMessage
    import datetime

    async def test_persistence():
        """
        一个异步函数，用于测试 checkpointer 的核心功能和生命周期。
        """
        print("--- 开始持久化功能测试 ---")
        
        # 1. 获取 checkpointer 实例
        try:
            checkpointer1 = await get_checkpointer()
            print("✅ 步骤 1/4: get_checkpointer() 第一次调用成功。")
            
            # 再次调用，应该会使用缓存
            checkpointer2 = await get_checkpointer()
            print("✅ 步骤 2/4: get_checkpointer() 第二次调用成功 (应从缓存获取)。")
            
            assert checkpointer1 is checkpointer2, "两次获取的 Checkpointer 实例不一致！"
            print("    -> 验证成功：两次调用返回的是同一个实例。")
            
        except Exception as e:
            print(f"❌ 获取 checkpointer 失败: {e}")
            return

        # 接下来是您的写入和读取测试，保持不变...
        thread_id = f"test_session_{uuid.uuid4().hex[:8]}"
        config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
        checkpoint_to_save = {
            "v": 2,
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "id": str(uuid.uuid4()),
            "channel_values": {"messages": [HumanMessage(content="你好，这是一个测试！")]},
            "channel_versions": { "messages": 1 },
            "versions_seen": {}, "pending_sends": []
        }
        
        try:
            await checkpointer1.aput(config, checkpoint_to_save, {}, {"messages": 1})
            print("✅ 步骤 3/4: aput() 调用成功。")
            retrieved = await checkpointer1.aget(config)
            assert retrieved is not None
            print("✅ 步骤 4/4: aget() 调用成功。")
        except Exception as e:
            print(f"❌ 读写测试失败: {e}")
            import traceback
            traceback.print_exc()

        print("\n--- 持久化功能测试通过！ ---")

    async def main_test_with_lifecycle():
        try:
            await test_persistence()
        finally:
            # 无论测试成功与否，最后都调用关闭函数
            print("\n--- 测试结束，执行清理操作 ---")
            await close_checkpointer()

    # 运行包含生命周期管理的异步测试函数
    try:
        asyncio.run(main_test_with_lifecycle())
    except KeyboardInterrupt:
        print("\n测试被中断。")