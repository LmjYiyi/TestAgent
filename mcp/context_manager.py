# 简化的上下文存储
session_context = {}

def get_context(session_id: str) -> list[str]:
    return session_context.get(session_id, [])

def update_context(session_id: str, message: str):
    history = session_context.setdefault(session_id, [])
    history.append(message)
