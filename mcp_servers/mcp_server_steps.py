import sys

sys.path.append('/TCGT')
from fastmcp import FastMCP
from langchain_chroma import Chroma
from models import dquestion
import re
from typing import List, Optional
# 创建 FastMCP 实例
mcp = FastMCP('find_step')


def extract_steps(page_content: str) -> List[str]:
    """
    从文档内容中提取操作步骤列表

    参数:
        page_content: 包含步骤的文本内容

    返回:
        格式化后的步骤列表（去除编号和多余空格）
    """
    if not page_content:
        return []

    try:
        # 提取步骤部分（从"步骤："开始到下一个标题或结束）
        steps_part = re.split(r'步骤：\s*', page_content, flags=re.IGNORECASE)[-1]
        steps_part = re.split(r'\n\s*#{1,3}\s+|\n---', steps_part)[0]

        # 匹配所有带编号的步骤行
        steps = re.findall(r'\d+\.\s*(.+?)\s*$', steps_part, flags=re.MULTILINE)
        return [step.strip() for step in steps if step.strip()]

    except Exception as e:
        print(f"步骤提取出错: {e}")
        return []


@mcp.tool
def get_operation_steps(interface_name: str, scenario_name: str) -> Optional[List[str]]:
    """
    获取指定接口中文名和场景名的操作步骤

    参数:
        interface_name: 接口中文名 (如"用户注册")
        scenario_name: 场景名 (如"普通用户注册")

    返回:
        操作步骤列表 (成功时)
        None (失败时)
    """
    try:
        # 1. 初始化向量数据库
        persist_path = "../db/siliconflow_vector_db"
        vectorstore = Chroma(
            persist_directory=persist_path,
            embedding_function=dquestion.get_embedding()
        )

        # 2. 创建带过滤条件的检索器
        retriever = vectorstore.as_retriever(
            search_kwargs={
                "filter": {
                    "$and": [
                        {"接口中文名": {"$eq": interface_name}},
                        {"场景名": {"$eq": scenario_name}}
                    ]
                },
                "k": 1  # 只返回最相关的1个文档
            }
        )

        # 3. 执行检索
        docs = retriever.invoke(f"{scenario_name}流程") or retriever.invoke(f"{interface_name}步骤")

        if not docs:
            print(f"未找到匹配文档 - 场景名: {scenario_name}, 接口名: {interface_name}")
            return None

        # 4. 提取并返回步骤
        steps = extract_steps(docs[0].page_content)
        return steps if steps else None

    except Exception as e:
        print(f"操作步骤获取失败: {e}")
        return None


if __name__ == '__main__':
    mcp.run(transport="stdio")
