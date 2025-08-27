# 这里放远程的mcp_server端代码，主要是被测接口相关的调用
# 应该是远程提供
"""
通用的MCP API调用服务器
接收来自client的请求报文
请求发送给后端restful api完成调用。
"""
import sys
import logging
import asyncio
import httpx
import json
import os
import re
from datetime import datetime
from typing import Dict, Any, Optional, List, Union
from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent

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
    host=os.getenv("API_MCP_HOST", "localhost"),
    port=int(os.getenv("API_MCP_PORT", "8001")),
    sse_path = "/sse"
)

def _replace_datetime_placeholders(obj, now):
    """
    辅助函数 获取交易时间和日期且对应被测工程接口要求的时间格式
    """
    if isinstance(obj, dict):
        return {key: _replace_datetime_placeholders(value, now) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [_replace_datetime_placeholders(item, now) for item in obj]
    elif isinstance(obj, str):
        if obj == "yyyy-MM-dd":
            logger.info("Auto-replacing placeholder 'yyyy-MM-dd'")
            return now.strftime("%Y-%m-%d")
        if obj == "HH:mm:ss":
            logger.info("Auto-replacing placeholder 'HH:mm:ss'")
            return now.strftime("%H:%M:%S")
    return obj


def _remove_empty_fields(obj):
    """
    辅助函数 清洁报文中的空白字段
    """
    if isinstance(obj, dict):
        
        cleaned_children = {k: _remove_empty_fields(v) for k, v in obj.items()}
       
        return {
            k: v for k, v in cleaned_children.items()
            if v not in ["", [], {}, None]
        }
    elif isinstance(obj, list):
        return [_remove_empty_fields(item) for item in obj]
    else:
        return obj

@mcp_app.tool(description="处理API请求报文，自动填充日期时间占位符并清理空值字段。")
async def process_payload(payload: Dict[str, Any]) -> List[TextContent]:
    """
    处理API请求报文，执行以下操作：
    1. 替换日期时间占位符（如 ${CURRENT_DATE}, ${CURRENT_TIME} 等）
    2. 递归移除所有空值字段（空字符串、空列表、空字典、None）
    
    Args:
        payload (Dict[str, Any]): 要处理的API请求报文
        
    Returns:
        List[TextContent]: 包含处理后的报文的TextContent列表
    """
    logger.info(f"接收到报文处理请求: {payload}")
    
    try:
        now = datetime.now()
        
        # 1. 递归替换日期和时间占位符
        processed_payload = _replace_datetime_placeholders(payload, now)
        logger.info("已添加当前时间戳")
        
        # 2. 递归移除所有空值字段
        processed_payload = _remove_empty_fields(processed_payload)
        logger.info("已移除所有空值字段")
        
        result_text = json.dumps(processed_payload, ensure_ascii=False, indent=2)
        return [TextContent(type="text", text=result_text)]
        
    except Exception as e:
        logger.error(f"报文处理失败: {e}", exc_info=True)
        error_dict = {"error": "PayloadProcessingError", "message": str(e)}
        return [TextContent(type="text", text=json.dumps(error_dict))]

@mcp_app.tool(description="调用一个通用的HTTP/HTTPS API。对于复杂的参数，请将它们作为JSON字符串在'json_body'中传递。")
async def call_api(url: str, method: str = "POST",
                   headers: Optional[Dict[str, str]] = None,
                   json_body: Optional[Dict[str, Any]] = None
                   ) -> List[TextContent]:
    """
    使用httpx异步调用HTTP/HTTPS API。

    Args:
        url (str): 要请求的完整URL。
        method (str): HTTP请求方法 (例如, "GET", "POST")。默认为 "POST"。
        headers (Optional[Dict[str, str]]): 请求头。
        json_body (Optional[Dict[str, Any]]): 要在请求体中发送的JSON数据。

    Returns:
        List[TextContent]: 包含从API返回的JSON响应的TextContent列表。如果发生错误，则返回一个包含结构化错误信息的字典。
    """
    logger.info(f"接收到API调用请求:")
    logger.info(f"  - URL: {url}")
    logger.info(f"  - 方法: {method}")
    logger.info(f"  - 请求头: {headers}")
    logger.info(f"  - JSON请求体: {json_body}")

    result_dict = {}
    try:
        async with httpx.AsyncClient() as client:
            response = await client.request(
                method=method.upper(),
                url=url,
                headers=headers,
                json=json_body,
                timeout=15.0
            )
            response.raise_for_status()
            
            # 尝试解析JSON，如果响应体为空或不是JSON格式，则返回文本内容
            try:
                result_dict = response.json()
            except json.JSONDecodeError:
                result_dict = {"status_code": response.status_code, "content": response.text}

    except httpx.HTTPStatusError as e:
        logger.error(f"API请求返回失败的状态码: {e.response.status_code}", exc_info=True)
        result_dict = {
            "error": "HTTPStatusError",
            "status_code": e.response.status_code,
            "message": f"请求失败，状态码: {e.response.status_code}",
            "response": e.response.text
        }
    except httpx.TimeoutException as e:
        logger.error(f"API请求超时: {e}", exc_info=True)
        result_dict = {"error": "TimeoutException", "message": f"请求超时: {e}"}
    except httpx.RequestError as e:
        logger.error(f"API请求失败: {e}", exc_info=True)
        result_dict = {"error": "RequestError", "message": f"请求连接错误: {e}"}
    except Exception as e:
        logger.error(f"调用API时发生未知错误: {e}", exc_info=True)
        result_dict = {"error": "UnknownError", "message": f"发生未知错误: {str(e)}"}

    # 将结果字典转换为格式化的JSON字符串，并封装在TextContent中返回
    result_text = json.dumps(result_dict, ensure_ascii=False, indent=2)
    return [TextContent(type="text", text=result_text)]


@mcp_app.tool(description="一个用于在Agent内部传递或更新状态的工具。它接收一个JSON对象，并原封不动地返回。当步骤的输出是一个需要在后续步骤中使用的JSON对象（例如，组装好的API请求报文）时，请使用此工具。支持字符串JSON，会自动解析。")
async def update_state(state_object: Union[Dict[str, Any], str]) -> List[TextContent]:
    """
    接收一个字典（JSON对象）并将其作为字符串返回，用于在Agent的步骤之间传递状态。

    Args:
        state_object (Dict[str, Any]): 要传递或更新的状态对象。

    Returns:
        List[TextContent]: 包含输入对象的JSON字符串表示形式的TextContent列表。
    """
    logger.info(f"接收到状态更新请求: {state_object}")
    try:
        # 允许字符串形式的JSON，自动解析
        if isinstance(state_object, str):
            try:
                state_object = json.loads(state_object)
            except json.JSONDecodeError:
                # 若不是合法JSON，则包裹为 raw_text 字段
                state_object = {"raw_text": state_object}

        # 将输入对象转换为JSON字符串
        result_text = json.dumps(state_object, ensure_ascii=False, indent=2)
        return [TextContent(type="text", text=result_text)]
    except TypeError as e:
        logger.error(f"状态对象无法序列化为JSON: {e}", exc_info=True)
        error_dict = {"error": "SerializationError", "message": str(e)}
        return [TextContent(type="text", text=json.dumps(error_dict))]

def main():
    """主函数，启动MCP服务器"""
    logger.info("启动通用API调用MCP服务器...")
    try:
        mcp_app.run(transport='sse')
    except KeyboardInterrupt:
        logger.info("\n服务器被用户中断，正在关闭...")

if __name__ == "__main__":
    main()
