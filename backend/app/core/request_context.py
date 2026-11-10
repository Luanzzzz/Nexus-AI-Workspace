"""IP do cliente e proxies confiáveis."""

from fastapi import Request

from app.core.config import settings


def trusted_proxy_hosts() -> frozenset[str]:
    return frozenset(
        host.strip() for host in settings.trusted_proxies.split(",") if host.strip()
    )


def forwarded_hops(forwarded: str | None) -> list[str]:
    if not forwarded:
        return []
    return [hop.strip() for hop in forwarded.split(",") if hop.strip()]


def client_ip_from_peer_and_forwarded(
    peer: str, forwarded: str | None, trusted: frozenset[str]
) -> str:
    """IP do cliente: XFF só conta se o peer for proxy confiável.

    Percorre a cadeia da direita para a esquerda e devolve o primeiro hop
    que não está em `trusted`. Hop da esquerda é controlado pelo cliente.
    """
    if not peer:
        return "unknown"
    if peer not in trusted:
        return peer
    for hop in reversed(forwarded_hops(forwarded)):
        if hop not in trusted:
            return hop
    return peer


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client is not None else ""
    return client_ip_from_peer_and_forwarded(
        peer,
        request.headers.get("x-forwarded-for"),
        trusted_proxy_hosts(),
    )


def uvicorn_proxy_kwargs() -> dict[str, bool | str]:
    """Alinha o ProxyHeadersMiddleware do uvicorn a TRUSTED_PROXIES.

    Lista vazia: não honrar XFF nem de loopback (o default do uvicorn
    confiaria em 127.0.0.1 e reescreveria request.client).
    """
    trusted = settings.trusted_proxies.strip()
    if not trusted:
        return {"proxy_headers": False, "forwarded_allow_ips": ""}
    return {"proxy_headers": True, "forwarded_allow_ips": trusted}
