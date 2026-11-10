"""Entrada do servidor HTTP alinhada a TRUSTED_PROXIES."""

from __future__ import annotations

import os

import uvicorn

from app.core.request_context import uvicorn_proxy_kwargs


def run() -> None:
    host = os.environ.get("APP_HOST") or "127.0.0.1"
    port = int(os.environ.get("APP_PORT") or "8000")
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        **uvicorn_proxy_kwargs(),
    )
