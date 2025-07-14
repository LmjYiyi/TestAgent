import json

from langchain.tools import Tool

from utils.app_mdretriever import mdretriever


def query_by_input(input_text: str) -> str:
    try:
        persist_directory = "../md_db"
        collection = "md_collection"
        filter = {"Header 2": {"$eq": "接口信息"}}
        query = input_text + "，请按照格式（接口英文名称：接口中文名称）返回接口列表，如果只有一个，返回一个即可，无需有其他描述"
        result = mdretriever(persist_directory, collection, filter, query)
        re = result.get("result")
        print(f"接口列表:{re}")
        return re
    except Exception as e:
        return f"Error: {e}"

qry_interface_tool = Tool(
    name="query_by_input",
    func=query_by_input,
    description="根据用户输入想测试的交易获取接口列表，例如：'接口A：com.icbc.ABC.qry'"
)

if __name__ == '__main__':
    query_by_input("我想测试查询交易，请按照格式（接口英文名称：接口中文名称）返回接口列表")