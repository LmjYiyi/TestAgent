from models.dquestion import get_llm
from utils import logger
import json

async def validate_step_logic(step_description: str, agent_final_output: str) -> tuple[bool, str]:
    """
    轻量级验证步骤执行结果是否符合预期
    
    Args:
        step_description: 步骤描述
        agent_final_output: Agent执行后的最终结论
    
    Returns:
        tuple: (是否有效, 诊断信息)
    """
    try:
        llm = get_llm()
        
        # 构建精简的验证提示
        prompt = f"""请根据以下信息，判断步骤执行是否成功。

**步骤描述**: {step_description}
**Agent最终结论**: "{agent_final_output}"

**判断逻辑**:
1.  如果“Agent最终结论”明确表示成功、完成或已找到/创建所需数据，则视为 **符合预期**。
2.  如果“Agent最终结论”明确包含“错误”、“失败”、“未找到”、“无法继续”、“查询结果为空”、“HTTP状态码非200”等失败信号，则视为 **不符合预期**。
3.  根据你的综合判断，给出最终结论。

**回复格式**:
- 符合预期：回复 "OK"
- 不符合预期：回复 "FAIL: [请从结论中提取简明的失败原因]"

**你的判断是**:"""
        
        response = await llm.ainvoke(prompt)
        result = response.content.strip()
        
        logger.info(f"快速逻辑验证: {result}")
        
        if result == "OK":
            return True, "验证通过"
        elif result.startswith("FAIL:"):
            return False, result[5:].strip()
        else:
            return True, "验证格式异常，默认继续"
            
    except Exception as e:
        logger.error(f"验证过程出错: {str(e)}")
        return True, f"验证出错: {str(e)}，继续执行"
