import os
from models.dquestion import get_llm
from langchain_core.prompts import ChatPromptTemplate
from schemas.analysis_schemas import ChangeAnalysisResult  # 从schemas导入
from utils.logger import setup_logger

logger = setup_logger('INFO')

# --- 文本提取工具 ---
def extract_text_from_file(file_path: str) -> str:
    """从不同类型的文件中提取纯文本内容。"""
    logger.info(f"从文件提取文本: {file_path}")
    try:
        if file_path.endswith('.md') or file_path.endswith('.txt'):
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        else:
            raise ValueError(f"不支持的文件类型: {os.path.splitext(file_path)[1]}")
    except Exception as e:
        logger.error(f"提取文件 '{file_path}' 文本时出错: {e}", exc_info=True)
        raise

# --- LLM 解析工具 ---
model = get_llm()

PROMPT_TEMPLATE = """ 
你是一位顶级的软件需求分析专家。你的任务是深入分析用户提供的技术需求文档，并严格按照指定的JSON格式输出你的分析结果。

**分析规则**:
1. **提取接口名**: 找到文档中提到的接口中英文名称。
2. **总结变更**: 用一两句话概括本次需求的核心变更内容。
3. **判断变更类型 (`change_type`)**: 这是最关键的一步。你必须将变更归类为以下几种类型之一：
    - `LOGIC_ONLY`: 如果变更只涉及后端逻辑、计算方法等，但数据结构没有改变。
    - `FIELD_VALUE_CHANGE`: 如果数据结构没变，但某个字段的可选值范围发生了变化。
    - `NEW_FIELD_ADDITION`: 如果报文中明确增加了新的字段。
    - `UNKNOWN`: 如果不属于以上任何一种。
4. **提取新增字段详情**: 如果 `change_type` 是 `NEW_FIELD_ADDITION`，你必须提取新增字段的名称，并判断它是否是必填项。
5. **提取预期结果**: 总结文档中描述的，本次变更完成后系统应该表现出的预期行为。

**待分析的文档内容**:
---
{document_content}
---
"""

async def analyze_document_with_llm(document_content: str) -> ChangeAnalysisResult:
    """使用大模型将文档纯文本内容解析为结构化的对象。"""
    logger.info("开始使用 LLM 进行文档结构化解析...")
    prompt = ChatPromptTemplate.from_template(PROMPT_TEMPLATE)
    structured_llm = model.with_structured_output(ChangeAnalysisResult)
    chain = prompt | structured_llm
    
    try:
        result = await chain.ainvoke({"document_content": document_content})
        logger.info("文档结构化解析成功。")
        return result
    except Exception as e:
        logger.error(f"LLM 解析失败: {e}", exc_info=True)
        raise ValueError(f"无法使用LLM解析文档内容: {e}")