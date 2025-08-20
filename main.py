from utils.logger import setup_logger
from workflows.graph_builder import build_graph
import asyncio
import uuid

from utils.db_utils import DatabaseManager

logger = setup_logger(log_level="INFO")
db_manager = DatabaseManager()

async def run():
    logger.info("============测试案例智能生成助手启动============")
    thread_id = str(uuid.uuid4())
    logger.info(f"创建新测试会话，会话ID: {thread_id}")
    config = {"configurable": {"thread_id": thread_id}}
    # 构建工作流
    # db_manager = DatabaseManager()
    await db_manager.initialize()
    checkpointer = db_manager.get_checkpointer()
    work_graph = await build_graph(checkpointer=checkpointer)

    state = {
        "user_input": "",
        "auto_continue": False,
        "current_stage": "query_scene",
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
    # 循环问用户
    while True:
        # 检查是否到达结束状态 - 优先处理，避免不必要的用户输入
        if state.get("current_stage") == "finish":
            print(f"\n {state['output']}")
            await db_manager.close()
            break
        
        # 判断是否需要用户交互
        if not state.get("auto_continue", False):
            print(f"\n {state['output']}")
            user_input = input("\n你：").strip()
            # 主动退出判断
            if user_input.lower() in ["退出", "exit", "quit","q"]:
                await db_manager.close()
                print("再见！")
                break
            state["user_input"] = user_input
        else:
            # 在自动继续模式下，我们不需要用户的输入
            state["user_input"] = ""
        state = await work_graph.ainvoke(state,config=config)


if __name__ == '__main__':
    try:
        asyncio.run(run())
    except Exception as e:
        logger.error(f"测试案例智能生成助手运行异常: {str(e)}")
    finally:
        logger.info(f"============测试案例智能生成助手结束============")
