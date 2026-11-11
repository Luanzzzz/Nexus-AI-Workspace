"""Rotas de documentos (upload, consulta e exclusão)."""

from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Path,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.routing import APIRoute
from starlette.types import Message

from app.api.dependencies.auth import get_current_user
from app.api.dependencies.documents import get_document_service
from app.api.dependencies.workspace import (
    DELETE_DOCUMENT,
    READ,
    UPLOAD_DOCUMENT,
    require_permission,
)
from app.api.exception_handlers import document_too_large_response
from app.models.user import User
from app.models.workspace_member import WorkspaceMember
from app.schemas.document import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    DocumentListResponse,
    DocumentResponse,
)
from app.services.document import DocumentService
from app.services.document_validation import MAX_UPLOAD_BYTES

# Folga para boundaries e cabeçalhos do multipart sobre o limite do arquivo.
_MULTIPART_OVERHEAD = 64 * 1024


class _BodyTooLargeError(Exception):
    """Corpo acumulado acima do teto; interrompe a leitura do multipart."""


class _BoundedUploadRoute(APIRoute):
    """Limita o corpo da requisição ao teto do upload (413), com ou sem tamanho.

    O Starlette grava o multipart em arquivo temporário (acima de 1 MiB) antes
    das dependencies de autenticação rodarem. Este guarda:
    - recusa de imediato Content-Length declarado acima do teto;
    - envolve `receive` e, ao passar de MAX_UPLOAD_BYTES + folga, aborta a
      leitura (inclusive chunked, sem Content-Length) e responde 413.
    O spool anterior à autenticação continua existindo, mas fica limitado a
    ~10 MiB + folga por requisição (ver ADR 0009). O limite exato do arquivo
    vale no storage.
    """

    def get_route_handler(
        self,
    ) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()
        limit = MAX_UPLOAD_BYTES + _MULTIPART_OVERHEAD

        async def handler(request: Request) -> Response:
            declared = request.headers.get("content-length", "")
            if declared.isascii() and declared.isdigit() and int(declared) > limit:
                return document_too_large_response()

            receive = request.receive
            received = 0
            exceeded = False

            async def bounded_receive() -> Message:
                nonlocal received, exceeded
                message = await receive()
                if message["type"] == "http.request":
                    received += len(message.get("body", b""))
                    if received > limit:
                        exceeded = True
                        raise _BodyTooLargeError
                return message

            # Starlette não expõe API pública para trocar o receive de um Request.
            request._receive = bounded_receive
            try:
                return await original(request)
            except Exception:
                # O FastAPI converte falhas de parsing em HTTPException(400);
                # a flag identifica o estouro de teto de forma inequívoca.
                if exceeded:
                    return document_too_large_response()
                raise

        return handler


_UNAUTHORIZED = {"description": "Não autenticado."}
_FORBIDDEN = {"description": "Permissão insuficiente."}
_NOT_FOUND = {"description": "Workspace ou documento não encontrado."}

# Os ids são INTEGER no PostgreSQL: fora da faixa vira 422, não erro de banco.
DocumentId = Annotated[int, Path(ge=1, le=2147483647)]
DOCUMENT_NOT_FOUND_DETAIL = "Documento não encontrado."


def _document_not_found() -> HTTPException:
    # Mesmo corpo para inexistente e de outro workspace.
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail=DOCUMENT_NOT_FOUND_DETAIL
    )


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
        401: _UNAUTHORIZED,
        403: _FORBIDDEN,
        404: _NOT_FOUND,
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


@router.get(
    "",
    response_model=DocumentListResponse,
    responses={401: _UNAUTHORIZED, 404: _NOT_FOUND},
)
async def list_documents(
    membership: Annotated[WorkspaceMember, Depends(require_permission(READ))],
    service: Annotated[DocumentService, Depends(get_document_service)],
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)] = DEFAULT_PAGE_LIMIT,
    offset: Annotated[int, Query(ge=0, le=2147483647)] = 0,
) -> DocumentListResponse:
    items, total = await service.list_documents(
        workspace_id=membership.workspace_id, limit=limit, offset=offset
    )
    return DocumentListResponse(
        items=[DocumentResponse.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{document_id}",
    response_model=DocumentResponse,
    responses={401: _UNAUTHORIZED, 404: _NOT_FOUND},
)
async def get_document(
    document_id: DocumentId,
    membership: Annotated[WorkspaceMember, Depends(require_permission(READ))],
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> DocumentResponse:
    document = await service.get_document(
        workspace_id=membership.workspace_id, document_id=document_id
    )
    if document is None:
        raise _document_not_found()
    return DocumentResponse.model_validate(document)


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses={401: _UNAUTHORIZED, 403: _FORBIDDEN, 404: _NOT_FOUND},
)
async def delete_document(
    document_id: DocumentId,
    membership: Annotated[
        WorkspaceMember, Depends(require_permission(DELETE_DOCUMENT))
    ],
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> Response:
    deleted = await service.delete_document(
        workspace_id=membership.workspace_id, document_id=document_id
    )
    if not deleted:
        raise _document_not_found()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
