# 这里放本地的mcp_server端代码，主要是RAG相关工具集

from typing import Any
import httpx
from mcp.server.fastmcp import FastMCP

# 初始化 FastMCP server
mcp = FastMCP("RAG")







if __name__ == "__main__":
    # 初始化并运行 server
    mcp.run(transport='stdio')