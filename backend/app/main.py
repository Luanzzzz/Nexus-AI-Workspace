from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from app.api.exception_handlers import (
    document_too_large_exception_handler,
    duplicate_slug_exception_handler,
    internal_error_exception_handler,
    invalid_credentials_exception_handler,
    invalid_document_exception_handler,
    request_validation_exception_handler,
    unsupported_document_exception_handler,
)
from app.api.middleware import RequestContextMiddleware
from app.api.v1.router import router as api_v1_router
from app.core.config import settings
from app.core.exceptions import (
    CredentialVerificationError,
    DocumentDeleteError,
    DocumentTooLargeError,
    DocumentUploadError,
    DuplicateSlugError,
    InvalidCredentialsError,
    InvalidDocumentError,
    UnsupportedDocumentTypeError,
)
from app.core.logging import configure_logging


def create_app() -> FastAPI:
    configure_logging()
    docs_url = "/docs" if settings.expose_openapi else None
    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        debug=settings.fastapi_debug,
        docs_url=docs_url,
        redoc_url="/redoc" if settings.expose_openapi else None,
        openapi_url="/openapi.json" if settings.expose_openapi else None,
    )
    application.include_router(api_v1_router)
    # O handler padrão do FastAPI devolveria error["input"], inclusive a senha.
    application.add_exception_handler(
        RequestValidationError,
        request_validation_exception_handler,
    )
    application.add_exception_handler(
        InvalidCredentialsError,
        invalid_credentials_exception_handler,
    )
    application.add_exception_handler(
        CredentialVerificationError,
        internal_error_exception_handler,
    )
    application.add_exception_handler(
        DuplicateSlugError,
        duplicate_slug_exception_handler,
    )
    application.add_exception_handler(
        UnsupportedDocumentTypeError,
        unsupported_document_exception_handler,
    )
    application.add_exception_handler(
        InvalidDocumentError,
        invalid_document_exception_handler,
    )
    application.add_exception_handler(
        DocumentTooLargeError,
        document_too_large_exception_handler,
    )
    application.add_exception_handler(
        DocumentDeleteError,
        internal_error_exception_handler,
    )
    application.add_exception_handler(
        DocumentUploadError,
        internal_error_exception_handler,
    )
    application.add_middleware(RequestContextMiddleware)
    return application


app = create_app()
