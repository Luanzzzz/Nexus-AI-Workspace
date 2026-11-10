"""IP do cliente e proxies confiáveis."""

from fastapi import Request

from app.core.config import settings


def trusted_proxy_hosts() -> frozenset[str]:
    return frozenset(
        host.strip() for host in settings.trusted_proxies.split(",") if host.strip()
    )


def client_ip(request: Request) -> str:
    """IP do peer, salvo se ele estiver em TRUSTED_PROXIES.

    Só então o primeiro hop de X-Forwarded-For é usado. O padrão da lista
    é vazio: um X-Forwarded-For forjado a partir da internet é ignorado.
    O proxy precisa sobrescrever o cabeçalho, não anexar o valor do cliente.
    """
    peer = request.client.host if request.client is not None else ""
    if not peer:
        return "unknown"
    if peer not in trusted_proxy_hosts():
        return peer
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded is None:
        return peer
    first = forwarded.split(",", 1)[0].strip()
    return first or peer
