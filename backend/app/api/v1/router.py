# Nesse arquivo, seu objetivo é apenas:
# 1. importar APIRouter;
# 2. criar um router principal;
# 3. definir nele o prefixo /api/v1.

from fastapi import APIRouter

# Importar os routers de cada endpoint
from app.api.v1.auth import router as auth_router
from app.api.v1.documents import router as documents_router
from app.api.v1.health import router as health_router
from app.api.v1.workspaces import router as workspaces_router

# Adicionar os routers ao router principal
router = APIRouter(prefix="/api/v1")

router.include_router(health_router)
router.include_router(auth_router)
router.include_router(workspaces_router)
router.include_router(documents_router)
