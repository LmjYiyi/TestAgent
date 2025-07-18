from utils.logger import setup_logger
from workflows.graph_builder import build_graph
import asyncio

logger = setup_logger(log_level="INFO")
async def run():
    logger.info("============测试案例智能生成助手启动============")
    # 构建工作流
    work_graph = build_graph()
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
    # 循环问用户
    while True:
        # 跳出循环的判断
        if state.get("output") and ("执行完毕" in state["output"] or "终止" in state["output"]):
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
        state = await work_graph.ainvoke(state)

if __name__ == '__main__':
    asyncio.run(run())