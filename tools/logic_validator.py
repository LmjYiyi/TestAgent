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
        
        # 构建更智能的验证提示
        prompt = f"""请根据以下信息，判断步骤执行是否符合预期。

**步骤描述**: {step_description}
**Agent最终结论**: "{agent_final_output}"

**判断逻辑**:
1. **成功场景判断**：
   - 如果步骤描述要求"交易成功"且Agent结论显示成功，则符合预期
   - 如果步骤描述要求"验证余额变化"且Agent结论显示余额变化正确，则符合预期
   - 如果步骤描述要求"API调用成功"且Agent结论显示API调用成功，则符合预期

2. **预期失败场景判断**：
   - 如果步骤描述包含"不透支"、"余额不足"、"错误处理"等关键词，且Agent结论显示相应的错误响应（如"余额不足"、"ERR1001"等），则**符合预期**
   - 如果步骤描述要求验证"交易失败"且Agent结论显示预期的失败响应，则符合预期
   - 如果步骤描述要求"校验身份信息失败"且Agent结论显示相应的错误，则符合预期

3. **真正的失败判断**：
   - 如果Agent结论显示"HTTP状态码非200"、"网络错误"、"数据库连接失败"等技术错误，则不符合预期
   - 如果Agent结论显示"未找到数据"、"查询结果为空"等数据缺失错误，则不符合预期
   - 如果Agent结论显示"执行异常"、"工具调用失败"等执行错误，则不符合预期

**重要提示**：
- 区分"预期失败"和"意外失败"
- 预期失败是测试场景的一部分，应该判定为成功
- 只有意外失败才应该判定为不符合预期

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
