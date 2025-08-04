# 提供rag_tools
import asyncio
from typing import List, Tuple
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


async def query_interface_details(interface_name: str, scenario_name: str) -> dict:
    """
    统一查询接口的步骤、请求参数和响应参数
    :param interface_name: 接口名称
    :param scenario_name: 场景名称
    :return: (步骤列表, 请求参数, 响应参数)
    """
    try:
        async with Client("mcp_servers/mcp_server_rag.py") as client:
            # 1. 查询场景步骤
            steps_result = await client.call_tool('get_api_steps', {
                "interface_name": interface_name,
                "scenario_name": scenario_name
            })

            # 2. 查询请求参数
            request_result = await client.call_tool('generate_api_request', {
                "interface_name": interface_name
            })

            # 3. 查询响应参数
            response_result = await client.call_tool('generate_api_response', {
                "interface_name": interface_name
            })

            # 处理步骤结果
            steps = []
            if hasattr(steps_result, 'structured_content') and isinstance(steps_result.structured_content, dict):
                steps = steps_result.structured_content.get('result', [])
            # formatted_steps = [step for step in enumerate(steps)]

            # 处理请求和响应参数
            request_params = request_result.content[0].text.strip()
            response_params = response_result.content[0].text.strip()

            result = {
                "steps": steps,
                "request_payload": request_params,
                "expected_response": response_params
            }

            return result

    except Exception as e:
        raise RuntimeError(f"查询接口详情失败: {str(e)}")


# async def main():
#     # try:
#     #     api_list = await query_scene_list('查询信用卡转账接口场景')
#     #     print("最终结果:", api_list)
#     #     # step_list = await query_scene_steps('信用卡转账支付', '信用卡转账支付-场景分支1-基准分支-正常交易')
#     #     # print("步骤列表：", step_list)
#     #     # request_params = await query_request_params('信用卡转账支付')
#     #     # print("请求参数报文：", request_params)
#     #     # response_params = await query_response_params('信用卡转账支付')
#     #     # print("响应参数报文：", response_params)
#     # except Exception as e:
#     #     print(f"发生错误: {e}")
#     try:
#         steps, request_params, response_params = await query_interface_details(
#             "信用卡转账支付",
#             "信用卡转账支付-场景分支1-基准分支-正常交易"
#         )
#
#         print("接口步骤:")
#         for step in steps:
#             print(step)
#
#         print("\n请求参数:")
#         print(request_params)
#
#         print("\n响应参数:")
#         print(response_params)
#
#     except Exception as e:
#         print(f"发生错误: {e}")
#
# if __name__ == "__main__":
#     asyncio.run(main())