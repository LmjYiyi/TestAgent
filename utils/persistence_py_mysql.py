# 文件: utils/persistence_py_mysql.py 
#langgraph使用checkpoint进行持久化，需要在编译图的时候传入checkpoint
#然后在图执行的时候（invoke或者put等操作）会调用checkpoint的save方法自动保存到数据库（最开始连接时会自动建表，只需建库）

import os
import atexit # 导入 atexit 模块，用于注册程序退出时要执行的函数
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.mysql.pymysql import PyMySQLSaver
import pymysql
from utils.logger import setup_logger

logger = setup_logger()

# --- 全局变量，用于持有关键对象，管理其生命周期 ---
_connection = None
_checkpointer_instance = None

def _cleanup_connection():
    """在程序退出时被调用，用于关闭数据库连接。"""
    global _connection
    if _connection:
        logger.info("程序退出，正在关闭 MySQL 连接...")
        _connection.close()
        _connection = None
        logger.info("MySQL 连接已关闭。")

# 使用 atexit 注册清理函数，确保程序无论如何退出，都会尝试关闭连接
atexit.register(_cleanup_connection)


def get_checkpointer() -> BaseCheckpointSaver:
    """
    配置并返回一个基于 MySQL 的【同步】持久化 Checkpointer 实例。
    这个函数是幂等的，会复用已创建的数据库连接和 Checkpointer 实例。
    """
    global _connection, _checkpointer_instance

    # 如果实例已创建，直接返回，避免重复工作
    if _checkpointer_instance:
        return _checkpointer_instance

    logger.info("正在初始化 PyMySQLSaver (同步 MySQL Checkpointer)...")

    try:
        # 1. 如果全局连接不存在，则创建它
        if not _connection:
            logger.info("尚未建立数据库连接，正在创建新连接...")
            _connection = pymysql.connect(
                host=os.getenv("MYSQL_HOST", "localhost"),
                port=int(os.getenv("MYSQL_PORT", 3306)),
                user=os.getenv("MYSQL_USER", "root"),
                password=os.getenv("MYSQL_PASSWORD", "123456"),
                db=os.getenv("MYSQL_DATABASE", "test"),
                autocommit=True,
                cursorclass=pymysql.cursors.DictCursor # 使用字典游标方便调试
            )
            logger.info("数据库连接已成功建立。")

        # 2. 使用这个全局连接来创建 Checkpointer 实例
        checkpointer = PyMySQLSaver(conn=_connection)

        # 3. 设置数据库表
        logger.info("正在检查并设置数据库表...")
        checkpointer.setup()
        logger.info("数据库表设置完成。")

        # 4. 将创建好的实例存入全局变量并返回
        _checkpointer_instance = checkpointer
        return _checkpointer_instance
        
    except Exception as e:
        logger.error(f"无法创建 PyMySQLSaver: {e}")
        import traceback
        traceback.print_exc()
        logger.error("请确保 MySQL 服务正在运行，并且连接参数正确。")
        raise

# =========================================================================
#  测试部分：在 main.py 中的交互式循环
# =========================================================================
if __name__ == '__main__':
    try:
        from workflows.graph_builder_py_mysql import build_graph
        import uuid

        def test_interactive_run():
            """
            使用 main.py 中的交互式循环来测试 get_checkpointer 的功能。
            """
            logger.info("============[测试模式] 案例智能生成助手启动============")
            
            # 1. 获取 Checkpointer 实例
            checkpointer = get_checkpointer()
            
            # 2. 构建带有持久化功能的图
            work_graph = build_graph(checkpointer=checkpointer)
            state = {
                "user_input": "",
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
                "output": "",
                "history": []
            }
            # 3. 开始交互式测试循环
            thread_id = str(uuid.uuid4())
            logger.info(f"创建新测试会话，会话ID: {thread_id}")
            config = {"configurable": {"thread_id": thread_id}}

            print("\n🤖 你好！我是测试案例智能生成助手。请输入你想要做什么？")

            # 循环问用户
            while True:
                # 跳出循环的判断
                if state.get("output") and "执行完毕" in state["output"]:
                    break
                # 需用户交互
                if state["output"] is not None:
                    print(f"\n {state['output']}")
                    user_input = input("\n你：").strip()
                    # 主动退出判断
                    if user_input.lower() in ["退出", "exit", "quit","q"]:
                        print("再见！")
                        break
                    state["user_input"] = user_input
                else:
                    print("请稍等...")
                # 同步阻塞
                state = work_graph.invoke(state,config=config)


        test_interactive_run()

    except ImportError:
        logger.error("无法导入 'workflows.graph_builder'。")
        logger.error("请确保您在项目的根目录下运行此脚本，或者项目结构已正确添加到 PYTHONPATH。")
    except KeyboardInterrupt:
        print("\n测试被中断。")