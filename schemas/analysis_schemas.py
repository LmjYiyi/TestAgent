from pydantic import BaseModel, Field
from typing import Literal, Optional

class NewFieldDetails(BaseModel):
    """描述新增字段的详细信息"""
    field_name: str = Field(description="新增字段的名称")
    is_required: bool = Field(description="该字段是否为必输项")

class ChangeAnalysisResult(BaseModel):
    """文档变更分析的结构化结果（数据合同）"""
    interface_name_en: Optional[str] = Field(None, description="接口英文名")
    interface_name_zh: Optional[str] = Field(None, description="接口中文名")
    change_summary: str = Field(description="核心变更内容的简洁摘要")
    change_type: Literal[
        "LOGIC_ONLY",
        "FIELD_VALUE_CHANGE",
        "NEW_FIELD_ADDITION",
        "UNKNOWN"
    ] = Field(description="判断出的核心变更类型")
    new_field_details: Optional[NewFieldDetails] = Field(None, description="新增字段的详细信息")
    expected_outcome: str = Field(description="变更后的预期结果或行为")