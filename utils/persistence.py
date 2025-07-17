# 文件: utils/persistence.py 异步实现
# 安装依赖 pip install langgraph-checkpoint-mysql[aiomysql]
#导入包 from utils.persistence import get_checkpointer 
# =======================================================
# build_graph函数处核心修改：调用 get_checkpointer 时加上 await ==
# checkpointer = await get_checkpointer()
# work_graph = build_graph(checkpointer=checkpointer)
# =======================================================
    

    

import os
import asyncio # 需要导入 asyncio
from langgraph.checkpoint.base import BaseCheckpointSaver
from logger import setup_logger

# 从新库的 aio 模块导入 AIOMySQLSaver
from langgraph.checkpoint.mysql.aio import AIOMySQLSaver

import aiomysql # 需要导入 aiomysql 来创建连接池

logger = setup_logger()

async def get_checkpointer() -> BaseCheckpointSaver:
    """
    配置并返回一个基于 MySQL 的【异步】持久化 Checkpointer 实例。
    """
    logger.info("正在初始化 AIOMySQLSaver (异步 MySQL Checkpointer)...")

    # =======================================================
    # == 核心修改：我们不再使用 from_conn_string，而是手动创建连接池 ==
    # =======================================================
    try:
        # 1. 从环境变量获取连接参数
        db_config = {
            "host": os.getenv("MYSQL_HOST", "localhost"),
            "port": int(os.getenv("MYSQL_PORT", 3308)), # 您的端口是 3308
            "user": os.getenv("MYSQL_USER", "root"),
            "password": os.getenv("MYSQL_PASSWORD", "1234"),
            "db": os.getenv("MYSQL_DATABASE", "langgraph_db"),
            "autocommit": True # 根据库的文档，推荐设置
        }

        # 2. 使用 aiomysql 创建一个异步连接池
        pool = await aiomysql.create_pool(**db_config)
        
        # 3. 将【连接池】传递给 AIOMySQLSaver 的构造函数
        #    这是不使用 `async with` 时的标准实例化方式
        checkpointer = AIOMySQLSaver(pool)

        # 4. 显式、异步地调用 setup()
        #    现在 checkpointer 是正确的实例，它有 .setup() 方法
        await checkpointer.setup()
        
        logger.info("AIOMySQLSaver 初始化并设置成功。")
        return checkpointer
        
    except Exception as e:
        logger.error(f"无法创建 AIOMySQLSaver: {e}")
        logger.error("请确保 MySQL 服务正在运行，并且连接参数正确。")
        raise




if __name__ == "__main__":
    import uuid
    from langgraph.graph import MessagesState
    from langchain_core.messages import HumanMessage
    import datetime

    async def test_persistence():
        """
        一个异步函数，用于测试 get_checkpointer 和 checkpointer 的核心功能。
        """
        print("--- 开始持久化功能测试 ---")
        
        # 1. 获取 checkpointer 实例
        try:
            checkpointer = await get_checkpointer()
            print("✅ 步骤 1/4: get_checkpointer() 调用成功，Checkpointer 实例已创建。")
        except Exception as e:
            print(f"❌ 步骤 1/4: get_checkpointer() 调用失败: {e}")
            return

        # 2. 准备测试数据
        thread_id = f"test_session_{uuid.uuid4().hex[:8]}"
        
        # 对于大部分简单的用例，checkpoint_ns 可以是一个空字符串。
        config = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": ""  # <--- 添加这个缺失的键！
            }
        }
        
        # 构造 checkpoint 的部分保持不变
        ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
        checkpoint_to_save = {
            "v": 2,
            "ts": ts,
            "id": str(uuid.uuid4()),
            "channel_values": {
                "messages": [HumanMessage(content="你好，这是一个测试！", id=str(uuid.uuid4()))]
            },
            "channel_versions": { "messages": 1 },
            "versions_seen": {},
            "pending_sends": [],
        }
        
        print(f"准备写入测试数据，Config: {config}")

        # 3. 测试写入功能 (aput)
        try:
            # aput 调用本身保持不变，因为修改的是 config
            saved_checkpoint_info = await checkpointer.aput(
                config, 
                checkpoint_to_save, 
                metadata={},
                new_versions={"messages": 1}
            )
            assert saved_checkpoint_info is not None, "aput 方法没有返回任何信息"
            print("✅ 步骤 2/4: aput() 调用成功，数据已写入数据库。")
        except Exception as e:
            print(f"❌ 步骤 2/4: aput() 调用失败: {e}")
            import traceback
            traceback.print_exc()
            return

        # 4. 测试读取功能 (aget)
        #    读取时，config 也需要包含 checkpoint_ns
        try:
            retrieved_checkpoint = await checkpointer.aget(config)
            
            assert retrieved_checkpoint is not None, "aget()未能获取到 checkpoint"
            retrieved_messages = retrieved_checkpoint['channel_values']['messages']
            assert retrieved_messages[-1].content == "你好，这是一个测试！"
            
            print("✅ 步骤 3/4: aget() 调用成功，数据已从数据库中正确读回。")
            print(f"    -> 读取到的内容: {retrieved_messages[-1].content}")
        except Exception as e:
            print(f"❌ 步骤 3/4: aget() 调用失败: {e}")
            return
            
        # 5. 测试列出功能 (alist)
        try:
            checkpoints_list = []
            # alist 的 config 也需要 checkpoint_ns
            async for cp in checkpointer.alist(config):
                checkpoints_list.append(cp)
            
            assert len(checkpoints_list) > 0, "alist() 未能列出任何 checkpoint"
            print(f"✅ 步骤 4/4: alist() 调用成功，找到了 {len(checkpoints_list)} 个检查点。")
        except Exception as e:
            print(f"❌ 步骤 4/4: alist() 调用失败: {e}")

        print("\n--- 持久化功能测试通过！ ---")

    # 运行异步测试函数
    try:
        asyncio.run(test_persistence())
    except KeyboardInterrupt:
        print("\n测试被中断。")