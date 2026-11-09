from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from app.api.exception_handlers import (
    internal_error_exception_handler,
    invalid_credentials_exception_handler,
    request_validation_exception_handler,
)
from app.api.v1.router import router as api_v1_router
from app.core.config import settings
from app.core.exceptions import CredentialVerificationError, InvalidCredentialsError

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    debug=settings.debug,
)

app.include_router(api_v1_router)
# O handler padrão do FastAPI devolveria error["input"], inclusive a senha.
app.add_exception_handler(
    RequestValidationError,
    request_validation_exception_handler,
)
app.add_exception_handler(
    InvalidCredentialsError,
    invalid_credentials_exception_handler,
)
app.add_exception_handler(
    CredentialVerificationError,
    internal_error_exception_handler,
)
# Erros inesperados (ex.: banco) também viram 500 genérico.
app.add_exception_handler(Exception, internal_error_exception_handler)
