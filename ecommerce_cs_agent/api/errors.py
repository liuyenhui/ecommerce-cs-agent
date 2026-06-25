from __future__ import annotations

from fastapi import HTTPException


def api_error(status_code: int, code: str, message: str, *, error_id: str | None = None) -> HTTPException:
    error = {
        "code": code,
        "message": message,
    }
    detail = {
        "detail": message,
        "error": error,
    }
    if error_id:
        detail["errorId"] = error_id
        error["errorId"] = error_id
    return HTTPException(
        status_code=status_code,
        detail=detail,
    )
