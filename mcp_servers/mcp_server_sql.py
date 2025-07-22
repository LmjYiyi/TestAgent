# 这里放远程SSE的mcp_server端，主要是数据库相关工具集
# 这里应该是远程提供

"""
MySQL MCPServer 
接收来自client发送的sql语句，调用aiomysql执行sql获得结果
"""

import logging
import sys
import json
import os
import asyncio
import aiomysql
from typing import List
from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("mysql_mcp_server")

def get_db_config():
    """从环境变量加载数据库配置，如果未设置则使用默认值。"""
    return {
        "host": os.getenv("MYSQL_HOST", "localhost"),
        "port": int(os.getenv("MYSQL_PORT", "3306")),
        "user": os.getenv("MYSQL_USER", "root"),
        "password": os.getenv("MYSQL_PASSWORD", "123456"),
        "db": os.getenv("MYSQL_DB", "test"),
        "autocommit": False # 将autocommit 设置为 False，以便手动控制事务
    }

async def _run_db_operation(query: str, is_read_only: bool = False):
    """使用 aiomysql 异步运行数据库操作。"""
    config = get_db_config()
    conn = None
    try:
        conn = await aiomysql.connect(**config)
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(query)
            
            if is_read_only:
                rows = await cursor.fetchall()
                if not rows:
                    return "查询结果为空。"
                # 处理 datetime 对象，将其转换为 ISO 格式字符串 避免序列化失败 
                return json.dumps(rows, indent=2, default=str)
            else:
                # 显式提交事务，确保数据持久化
                await conn.commit()
                return f"操作成功。受影响的行数: {cursor.rowcount}"
            
    except Exception as e:
        logger.error(f"数据库操作失败: {e}", exc_info=True)
        if conn:
            # 发生错误时回滚事务
            await conn.rollback()
        return f"MySQL错误: {str(e)}"
    finally:
        if conn:
            # 确保在关闭连接前所有操作完成，增加延迟
            await asyncio.sleep(0.1) 
            conn.close()

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

# 创建FastMCP实例
logger.debug("创建FastMCP实例...")
mcp_app = FastMCP(
    "mysql-mcp-server",
    instructions="基于MCP协议的MySQL数据库查询服务",
    session_handler=session_handler,
    host=os.getenv("MYSQL_MCP_HOST", "127.0.0.1"),
    port=int(os.getenv("MYSQL_MCP_PORT", "8000")),
    sse_path="/sse"
)

@mcp_app.tool(description="执行只读SQL查询 (SELECT语句)")
async def run_sql_query(query: str) -> List[TextContent]:
    logger.info(f"收到只读SQL查询请求: {query}")
    query_upper = query.strip().upper()
    if not (query_upper.startswith("SELECT") or query_upper.startswith("SHOW") or query_upper.startswith("DESCRIBE") or query_upper.startswith("WITH")):
        error_msg = "run_sql_query 工具只允许执行 SELECT, SHOW, DESCRIBE 或 WITH 查询。"
        logger.error(error_msg)
        return [TextContent(type="text", text=error_msg)]
    
    result = await _run_db_operation(query, is_read_only=True)
    return [TextContent(type="text", text=result)]


@mcp_app.tool(description="向MySQL数据库中的表插入数据。")
async def insert_data(query: str) -> List[TextContent]:
    logger.info(f"收到INSERT INTO请求: {query}")
    query_upper = query.strip().upper()
    if not (query_upper.startswith("INSERT INTO") or query_upper.startswith("INSERT IGNORE INTO")):
        error_msg = "insert_data 工具只允许执行 INSERT INTO 或 INSERT IGNORE INTO 查询。"
        logger.error(error_msg)
        return [TextContent(type="text", text=error_msg)]

    result = await _run_db_operation(query, is_read_only=False)
    return [TextContent(type="text", text=result)]

@mcp_app.tool(description="更新MySQL数据库中的表数据。")
async def update_data(query: str) -> List[TextContent]:
    logger.info(f"收到UPDATE请求: {query}")
    query_upper = query.strip().upper()
    if not query_upper.startswith("UPDATE"):
        error_msg = "update_data 工具只允许执行 UPDATE 查询。"
        logger.error(error_msg)
        return [TextContent(type="text", text=error_msg)]

    result = await _run_db_operation(query, is_read_only=False)
    return [TextContent(type="text", text=result)]

@mcp_app.tool(description="从MySQL数据库中的表删除数据。")
async def delete_data(query: str) -> List[TextContent]:
    logger.info(f"收到DELETE FROM请求: {query}")
    query_upper = query.strip().upper()
    if not query_upper.startswith("DELETE FROM"):
        error_msg = "delete_data 工具只允许执行 DELETE FROM 查询。"
        logger.error(error_msg)
        return [TextContent(type="text", text=error_msg)]

    result = await _run_db_operation(query, is_read_only=False)
    return [TextContent(type="text", text=result)]

@mcp_app.tool(description="执行任何非SELECT的SQL语句 (例如 ALTER TABLE, DROP等)。")
async def execute_sql(query: str) -> List[TextContent]:
    logger.info(f"收到通用SQL执行请求: {query}")
    query_upper = query.strip().upper()
    if query_upper.startswith("SELECT") or query_upper.startswith("SHOW") or query_upper.startswith("DESCRIBE"):
        error_msg = "execute_sql 工具不允许执行 SELECT, SHOW 或 DESCRIBE 查询。请使用 run_sql_query 工具。"
        logger.error(error_msg)
        return [TextContent(type="text", text=error_msg)]

    result = await _run_db_operation(query)
    return [TextContent(type="text", text=result)]

@mcp_app.resource("mysql://schema", description="获取数据库表结构")
async def get_schema() -> List[TextContent]:
    """获取数据库表结构"""
    config = get_db_config()
    conn = None
    try:
        conn = await aiomysql.connect(**config)
        async with conn.cursor() as cursor:
            await cursor.execute("SHOW TABLES;")
            tables = await cursor.fetchall()
            
            schema_info = []
            for table in tables:
                table_name = table[0]
                await cursor.execute(f"DESCRIBE {table_name};")
                columns = await cursor.fetchall()
                schema_info.append(f"表 {table_name}:")
                for col in columns:
                    schema_info.append(f"  - {col[0]} ({col[1]})")
            
            return [TextContent(type="text", text="\n".join(schema_info))]
    except Exception as e:
        error_msg = f"MySQL错误: {str(e)}"
        logger.error(f"获取表结构失败: {error_msg}")
        return [TextContent(type="text", text=error_msg)]
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    logger.info("启动MCP SSE/HTTP服务器...")
    try:
        mcp_app.run(transport='sse')
    except KeyboardInterrupt:
        logger.info("\n服务器被用户中断，正在关闭...")
