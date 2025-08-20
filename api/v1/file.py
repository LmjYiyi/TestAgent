# /api/v1/file.py

import os
import uuid
from fastapi import APIRouter, File, UploadFile, HTTPException, Path
from fastapi.responses import JSONResponse
from utils.parser_utils import extract_text_from_file, analyze_document_with_llm
from schemas.analysis_schemas import ChangeAnalysisResult
from workflows.requirement_graph import build_requirement_workflow, create_initial_requirement_state

router = APIRouter()
UPLOAD_DIRECTORY = "./uploaded_files_temp"
if not os.path.exists(UPLOAD_DIRECTORY):
    os.makedirs(UPLOAD_DIRECTORY)

@router.post("/uploadfile", summary="上传文件以供后续分析")
async def upload_file(file: UploadFile = File(...)):
    """
    处理文件上传。

    - **file**: 上传的文件对象。

    成功时返回包含文件ID的JSON响应，失败则引发HTTP异常。
    """
    try:
        file_extension = os.path.splitext(file.filename)[1].lower()
        file_id = f"{uuid.uuid4()}{file_extension}"
        file_path = os.path.join(UPLOAD_DIRECTORY, file_id)
        
        with open(file_path, "wb") as buffer:
            buffer.write(await file.read())
            
        return JSONResponse(status_code=200, content={"message": "文件上传成功", "file_id": file_id})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文件上传失败: {str(e)}")

@router.post("/analyze/{file_id}", summary="分析已上传的文档")
async def analyze_file(
    file_id: str = Path(..., description="通过 /uploadfile 获取的文件ID")
):
    """
    分析指定ID的已上传文件。

    - **file_id**: 从/uploadfile端点获取的唯一文件标识符。

    返回文档变更分析的结构化结果，使用图工作流引擎，处理各种潜在错误，并在分析后删除文件。
    """
    if "/" in file_id or "\\" in file_id:
        raise HTTPException(status_code=400, detail="无效的文件ID格式。")
    
    file_path = os.path.join(UPLOAD_DIRECTORY, file_id)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"文件 '{file_id}' 未找到。")

    try:
        document_content = extract_text_from_file(file_path)
        if not document_content.strip():
            raise HTTPException(status_code=400, detail="文件内容为空。")

        # 🔧 使用图工作流分析引擎
        workflow = await build_requirement_workflow()
        initial_state = create_initial_requirement_state(document_content)
        
        # 执行工作流直到需要用户交互或完成
        final_state = await workflow.ainvoke(initial_state)
        
        # 构建标准化的响应格式
        test_scenarios = final_state.get("test_scenarios", [])
        is_success = final_state.get("error_message") is None
        
        response_content = {
            "success": is_success,
            "message": final_state.get("result_message", "") if is_success else final_state.get("error_message", ""),
            "data": {
                "test_scenarios": test_scenarios,
                "analysis_type": "requirement_analysis",
                "has_scenarios": len(test_scenarios) > 0,
                "file_name": file_id,
                "scenario_count": len(test_scenarios),
                "current_stage": final_state.get("current_stage", ""),
                "requires_interaction": final_state.get("current_stage") == "select_scenario"
            }
        }
        
        return JSONResponse(
            status_code=200 if is_success else 400,
            content=response_content
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"处理文件时发生未知错误: {str(e)}")
    finally:
        # 确保临时文件在分析后被删除
        if os.path.exists(file_path):
            os.unlink(file_path)