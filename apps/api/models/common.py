from pydantic import BaseModel
from typing import Any, Optional


def api_response(success: bool, data: Any = None, error: Optional[str] = None) -> dict:
    return {"success": success, "data": data, "error": error}
