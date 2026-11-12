"""Camada de serviços não depende da camada HTTP (app.api, fastapi, starlette)."""

import ast
from pathlib import Path

SERVICES_DIR = Path(__file__).resolve().parents[2] / "app" / "services"
_HTTP_FRAMEWORKS = frozenset({"fastapi", "starlette"})


def _is_http_module(name: str) -> bool:
    parts = name.split(".")
    return parts[:2] == ["app", "api"] or parts[0] in _HTTP_FRAMEWORKS


def _violations(path: Path) -> list[str]:
    found: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names if _is_http_module(a.name)]
        elif isinstance(node, ast.ImportFrom) and node.module:
            if _is_http_module(node.module):
                found.append(node.module)
        elif isinstance(node, ast.Attribute) and node.attr == "HTTPException":
            found.append("HTTPException")
    return found


def test_services_do_not_import_api_layer_or_http_frameworks():
    files = sorted(SERVICES_DIR.glob("*.py"))
    assert files
    offenders = {f.name: _violations(f) for f in files if _violations(f)}
    assert offenders == {}


def test_scanner_detects_violations(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text(
        "from app.api.dependencies.x import y\n"
        "from fastapi import UploadFile\n"
        "from starlette.responses import Response\n"
        "import fastapi.security\n"
        "import app.api.v1\n"
    )
    assert _violations(bad) == [
        "app.api.dependencies.x",
        "fastapi",
        "starlette.responses",
        "fastapi.security",
        "app.api.v1",
    ]
