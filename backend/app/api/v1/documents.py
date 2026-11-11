"""Rotas de documentos (upload)."""

from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile, status
from fastapi.routing import APIRoute

from app.api.dependencies.auth import get_current_user
from app.api.dependencies.documents import get_document_service
from app.api.dependencies.workspace import UPLOAD_DOCUMENT, require_permission
from app.api.exception_handlers import document_too_large_response
from app.models.user import User
from app.models.workspace_member import WorkspaceMember
from app.schemas.document import DocumentResponse
from app.services.document import DocumentService
from app.services.document_validation import MAX_UPLOAD_BYTES

# Folga para boundaries e cabeçalhos do multipart sobre o limite do arquivo.
_MULTIPART_OVERHEAD = 64 * 1024


class _BoundedUploadRoute(APIRoute):
    """Recusa cedo (413) corpos com Content-Length claramente acima do limite.

    O Starlette grava o multipart em arquivo temporário antes da rota rodar;
    este guarda evita isso quando o cliente declara o tamanho. Corpos sem
    Content-Length (chunked) passam e o limite exato vale no storage.
    """

    def get_route_handler(
        self,
    ) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            declared = request.headers.get("content-length", "")
            if declared.isascii() and declared.isdigit():
                if int(declared) > MAX_UPLOAD_BYTES + _MULTIPART_OVERHEAD:
                    return document_too_large_response()
            return await original(request)

        return handler


router = APIRouter(
    prefix="/workspaces/{workspace_id}/documents",
    tags=["documents"],
    route_class=_BoundedUploadRoute,
)


@router.post(
    "",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        413: {"description": "Arquivo acima de 10 MiB."},
        415: {"description": "Tipo de arquivo não suportado."},
        422: {"description": "Arquivo vazio, inválido ou nome inválido."},
    },
)
async def upload_document(
    membership: Annotated[
        WorkspaceMember, Depends(require_permission(UPLOAD_DOCUMENT))
    ],
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[DocumentService, Depends(get_document_service)],
    file: Annotated[UploadFile, File()],
) -> DocumentResponse:
    # A autorização (dependency acima) roda antes de qualquer escrita no storage.
    document = await service.upload_document(
        workspace_id=membership.workspace_id, user=current_user, upload=file
    )
    return DocumentResponse.model_validate(document)
