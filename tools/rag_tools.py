# 提供rag_tools
from typing import List
from fastmcp import Client
from utils import logger

async def query_scene_list(query: str) -> List[str]:
    """
    异步调用 FastMCP 工具，获取接口场景列表
    """
    logger.info("正在调用 query_scene_list 工具...")
    try:
        async with Client("mcp_servers/mcp_server_rag.py") as client:
            query = {"query": query}
            tool_result = await client.call_tool('rag_match', query)
            # 提取原始字符串
            raw_text = tool_result.content[0].text.strip()

            # 去掉前缀 `api_list = [` 和末尾 `]`
            if raw_text.startswith("api_list = [") and raw_text.endswith("]"):
                raw_text = raw_text[len("api_list = ["):-1].strip()

            # 用逗号拆分并组合成一项一项的字符串
            items = []
            parts = raw_text.split(", ")
            for i in range(0, len(parts), 2):
                if i + 1 < len(parts):
                    item = f'{parts[i]}, {parts[i + 1]}'
                    items.append(item)
            api_list = items
            return api_list

    except Exception as e:
        # 捕获所有异常（网络错误、格式错误等）
        raise RuntimeError(f"获取接口场景失败: {str(e)}")


async def query_scene_steps(interface_name: str, scenario_name: str):
    """
    处理"查找操作步骤"阶段的状态流转
    :param state: 当前状态（包含 选择的接口+场景 dict 等）
    :return: 更新后的状态（包含 origin_step_list 和 output）
    """
    logger.info("正在调用 query_scene_steps 工具...")
    try:
        async with Client("mcp_servers/mcp_server_rag.py") as client:
            query = {
                "interface_name": interface_name,
                "scenario_name": scenario_name
            }
            tool_result = await client.call_tool('get_api_steps', query)
            # 提取并格式化步骤
            steps = []
            if hasattr(tool_result, 'structured_content') and isinstance(tool_result.structured_content, dict):
                steps = tool_result.structured_content.get('result', [])

            # 格式化输出
            formatted_steps = [f"{i + 1}. {step}" for i, step in enumerate(steps)]
            print(f"最后得到的步骤:{formatted_steps}")
            return formatted_steps

    except Exception as e:
        # 捕获所有异常（网络错误、格式错误等）
        raise RuntimeError(f"获取接口场景失败: {str(e)}")
