from datetime import datetime
from utils import logger

def _replace_datetime_placeholders(obj, now):
    """
    辅助函数 获取交易时间和日期且对应被测工程接口要求的时间格式
    """
    if isinstance(obj, dict):
        return {key: _replace_datetime_placeholders(value, now) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [_replace_datetime_placeholders(item, now) for item in obj]
    elif isinstance(obj, str):
        if obj == "yyyy-MM-dd":
            logger.info("Auto-replacing placeholder 'yyyy-MM-dd'")
            return now.strftime("%Y-%m-%d")
        if obj == "HH:mm:ss":
            logger.info("Auto-replacing placeholder 'HH:mm:ss'")
            return now.strftime("%H:%M:%S")
    return obj


def _remove_empty_fields(obj):
    """
    辅助函数 清洁报文中的空白字段
    """
    if isinstance(obj, dict):
        
        cleaned_children = {k: _remove_empty_fields(v) for k, v in obj.items()}
       
        return {
            k: v for k, v in cleaned_children.items()
            if v not in ["", [], {}, None]
        }
    elif isinstance(obj, list):
        return [_remove_empty_fields(item) for item in obj]
    else:
        return obj
