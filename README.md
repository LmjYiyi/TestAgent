## 环境
创建虚拟环境 python -m venv env
启动虚拟环境.\env\Scripts\activate
 
## 启动mcpserver
uvicorn mcp.server:app --host 0.0.0.0 --port 8001

## 启动整体项目后台服务
uvicorn app:app --reload --port 8000