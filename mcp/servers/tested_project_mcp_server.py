"""
通用的MCP API调用服务器
接收来自client的请求报文
请求发送给后端restful api完成调用。
"""
import sys
import logging
import asyncio
import requests
import json
from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent
from typing import Dict, Any, Optional, List

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("tested_project_mcp_server")

# 会话处理函数
async def session_handler(ctx):
    """会话处理函数"""
    logger.info(f"客户端已连接，开始会话. Session ID: {ctx.session_id}")
    try:
        result = await ctx.run()
        logger.info(f"会话处理完成: {result}")
        return result
    except Exception as e:
        logger.error(f"会话处理出错: {str(e)}", exc_info=True)
        raise
    finally:
        logger.info("客户端会话结束")


# 创建一个MCP服务器示例
logger.debug("创建FastMCP实例")
mcp_app = FastMCP(
    "tested_project_mcp_server",
    instructions="基于mcp协议的后端接口调用服务",
    session_handler=session_handler,
    host = "localhost",
    port = 8001,
    sse_path = "/sse"
)

@mcp_app.tool()
async def call_api(url: str, method: str = "POST",
         headers: Optional[Dict[str, str]] = None,
         json_body: Optional[Dict[str, Any]] = None
        ) -> List[TextContent]:
    """
    用于调用HTTP请求。
    使用asyncio.to_thread在一个独立的线程中运行同步的requests库，避免阻塞事件循环。

    Args:
        url (str): 要请求的完整URL。
        method (str): HTTP请求方法 (例如, "GET", "POST")。默认为 "POST"。
        headers (Optional[Dict[str, str]]): 请求头。
        json_body (Optional[Dict[str, Any]]): 要在请求体中发送的JSON数据。

    Returns:
        List[TextContent]: 包含从API返回的JSON响应的TextContent列表。如果发生错误，则返回一个包含错误信息的字典。
    """
    logger.info(f"接收到API调用请求:")
    logger.info(f"  - URL: {url}")
    logger.info(f"  - 方法: {method}")
    logger.info(f"  - 请求头: {headers}")
    logger.info(f"  - JSON请求体: {json_body}")

    def _sync_request_wrapper():
        """同步执行requests调用的包装函数"""
        try:
            response = requests.request(
                method=method.upper(),
                url=url,
                headers=headers,
                json=json_body,
                timeout=15  # 设置一个合理的超时时间
            )
            response.raise_for_status()  # 对失败的HTTP状态码抛出异常
            
            # 尝试解析JSON，如果响应体为空或不是JSON格式，则返回文本内容
            try:
                return response.json()
            except json.JSONDecodeError:
                return {"status_code": response.status_code, "content": response.text}
        except requests.exceptions.RequestException as e:
            logger.error(f"API请求失败: {e}", exc_info=True)
            return {"error": f"请求失败: {e}"}

    # 在一个单独的线程中运行同步的HTTP请求，以避免阻塞asyncio事件循环
    result_dict = await asyncio.to_thread(_sync_request_wrapper)
    
    # 将结果字典转换为格式化的JSON字符串，并封装在TextContent中返回
    result_text = json.dumps(result_dict, ensure_ascii=False, indent=2)
    return [TextContent(type="text", text=result_text)]

def main():
    """主函数，启动MCP服务器"""
    logger.info("启动通用API调用MCP服务器...")
    try:
        mcp_app.run(transport='sse')
    except KeyboardInterrupt:
        logger.info("\n服务器被用户中断，正在关闭...")

if __name__ == "__main__":
    main()
