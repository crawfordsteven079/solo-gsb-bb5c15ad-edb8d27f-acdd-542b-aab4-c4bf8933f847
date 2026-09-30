"""领域错误与统一 JSON 错误格式。

统一响应体：{"error": {"code": "...", "message": "...", "details": {...}}}
"""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class InvalidStratumError(AppError):
    status_code = 422
    code = "invalid_stratum"


class DuplicateEvidenceError(AppError):
    status_code = 422
    code = "duplicate_evidence"


class MissingAssertionError(AppError):
    status_code = 404
    code = "assertion_not_found"


class StaleRevisionError(AppError):
    status_code = 409
    code = "stale_revision"


class SelfRelationError(AppError):
    status_code = 422
    code = "self_relation"


class CrossSiteError(AppError):
    status_code = 422
    code = "cross_site_relation"


class ContradictionError(AppError):
    status_code = 409
    code = "contradiction"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


def install_exception_handlers(app) -> None:
    @app.exception_handler(AppError)
    async def _handle_app_error(_: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                }
            },
        )
