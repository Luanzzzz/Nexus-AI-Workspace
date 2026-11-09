from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from app.api.exception_handlers import request_validation_exception_handler
from app.api.v1.router import router as api_v1_router
from app.core.config import settings

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
