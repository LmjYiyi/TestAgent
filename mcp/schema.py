from pydantic import BaseModel
# 定义请求/响应模型
class MCPRequest(BaseModel):
    session_id: str
    input: str
    task_type: str = "default"

class MCPResponse(BaseModel):
    output: str

