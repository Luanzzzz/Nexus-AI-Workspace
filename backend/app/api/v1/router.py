# Nesse arquivo, seu objetivo é apenas:
# 1. importar APIRouter;
# 2. criar um router principal;
# 3. definir nele o prefixo /api/v1.

from fastapi import APIRouter

# Importar os routers de cada endpoint
from app.api.v1.health import router as health_router

# Adicionar os routers ao router principal
router = APIRouter(prefix="/api/v1")

router.include_router(health_router)