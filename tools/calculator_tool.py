from langchain.tools import Tool

def calculator(input_text: str) -> str:
    try:
        result = eval(input_text)
        print(f"计算结果:{result}")
        return f"{input_text} = {result}"
    except Exception as e:
        return f"Error: {e}"

calculator_tool = Tool(
    name="calculator",
    func=calculator,
    description="用于计算数学表达式，例如：'2 + 3 * (4 - 1)'"
)