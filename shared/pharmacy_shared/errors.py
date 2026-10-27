"""Error format used by every service: {"code": ..., "message": ..., "details": {...}}.

Codes come from docs/spec.md (Errors, Security & reliability, AI service).
"""

from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ErrorCode(StrEnum):
    # Stock and batches
    OUT_OF_STOCK = "OUT_OF_STOCK"
    BATCH_EXPIRED = "BATCH_EXPIRED"
    BATCH_BLOCKED = "BATCH_BLOCKED"
    TRANSFER_STATE = "TRANSFER_STATE"
    # Prescriptions and controlled drugs
    RX_REQUIRED = "RX_REQUIRED"
    RX_EXPIRED = "RX_EXPIRED"
    RX_QTY_EXCEEDED = "RX_QTY_EXCEEDED"
    PHARMACIST_REQUIRED = "PHARMACIST_REQUIRED"
    PIN_REQUIRED = "PIN_REQUIRED"
    PIN_INVALID = "PIN_INVALID"
    WITNESS_REQUIRED = "WITNESS_REQUIRED"
    ALLERGY_WARNING = "ALLERGY_WARNING"
    # Money and contacts
    CREDIT_LIMIT_EXCEEDED = "CREDIT_LIMIT_EXCEEDED"
    DUPLICATE_PHONE = "DUPLICATE_PHONE"
    # Access and security
    BRANCH_FORBIDDEN = "BRANCH_FORBIDDEN"
    RATE_LIMITED = "RATE_LIMITED"
    ACCOUNT_LOCKED = "ACCOUNT_LOCKED"
    SESSION_REVOKED = "SESSION_REVOKED"
    FILE_REJECTED = "FILE_REJECTED"
    # AI
    AI_DISABLED = "AI_DISABLED"
    AI_UNAVAILABLE = "AI_UNAVAILABLE"
    AI_LIMIT_REACHED = "AI_LIMIT_REACHED"
    AI_UNREADABLE = "AI_UNREADABLE"
    # Authentication and sessions
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    NOT_AUTHENTICATED = "NOT_AUTHENTICATED"
    # Idempotency
    IDEMPOTENCY_KEY_REQUIRED = "IDEMPOTENCY_KEY_REQUIRED"
    IDEMPOTENCY_KEY_INVALID = "IDEMPOTENCY_KEY_INVALID"
    IDEMPOTENCY_KEY_REUSED = "IDEMPOTENCY_KEY_REUSED"
    IDEMPOTENCY_IN_PROGRESS = "IDEMPOTENCY_IN_PROGRESS"
    # Two-factor login
    MFA_REQUIRED = "MFA_REQUIRED"
    MFA_SETUP_REQUIRED = "MFA_SETUP_REQUIRED"
    INVALID_MFA_CODE = "INVALID_MFA_CODE"
    # Users, roles, branches
    FORBIDDEN = "FORBIDDEN"
    LAST_OWNER = "LAST_OWNER"
    ROLE_IN_USE = "ROLE_IN_USE"
    ROLE_NOT_EDITABLE = "ROLE_NOT_EDITABLE"
    UNKNOWN_ROLE = "UNKNOWN_ROLE"
    UNKNOWN_PERMISSION = "UNKNOWN_PERMISSION"
    UNKNOWN_BRANCH = "UNKNOWN_BRANCH"
    DUPLICATE_CODE = "DUPLICATE_CODE"
    WEAK_PASSWORD = "WEAK_PASSWORD"
    INVALID_PIN = "INVALID_PIN"
    CANNOT_CHANGE_SELF = "CANNOT_CHANGE_SELF"
    UNKNOWN_FEATURE = "UNKNOWN_FEATURE"
    # Products and imports
    DUPLICATE_SKU = "DUPLICATE_SKU"
    DUPLICATE_BARCODE = "DUPLICATE_BARCODE"
    DUPLICATE_NAME = "DUPLICATE_NAME"
    UNKNOWN_CATEGORY = "UNKNOWN_CATEGORY"
    UNKNOWN_BRAND = "UNKNOWN_BRAND"
    IMPORT_HAS_ERRORS = "IMPORT_HAS_ERRORS"
    IMPORT_STATE = "IMPORT_STATE"
    # Generic
    TEMPORARILY_UNAVAILABLE = "TEMPORARILY_UNAVAILABLE"
    NOT_FOUND = "NOT_FOUND"
    VALIDATION_ERROR = "VALIDATION_ERROR"


class AppError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        self.headers = headers
        super().__init__(message)


def error_body(code: ErrorCode, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details or {}}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.code, exc.message, exc.details),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=error_body(
                ErrorCode.VALIDATION_ERROR,
                "Invalid request",
                # Never echo the submitted input back: it may contain a password or PIN.
                {
                    "errors": [
                        {"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()
                    ]
                },
            ),
        )
