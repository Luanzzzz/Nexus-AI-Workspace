"""Camada de serviços não depende da camada HTTP (app.api, HTTPException)."""

import ast
from pathlib import Path

SERVICES_DIR = Path(__file__).resolve().parents[2] / "app" / "services"


def _violations(path: Path) -> list[str]:
    found: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found += [
                a.name for a in node.names if a.name.split(".")[:2] == ["app", "api"]
            ]
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "app.api" or node.module.startswith("app.api."):
                found.append(node.module)
            if node.module.split(".")[0] == "fastapi" and any(
                a.name == "HTTPException" for a in node.names
            ):
                found.append("fastapi.HTTPException")
        elif isinstance(node, ast.Attribute) and node.attr == "HTTPException":
            found.append("HTTPException")
    return found


def test_services_do_not_import_api_layer_or_http_exception():
    files = sorted(SERVICES_DIR.glob("*.py"))
    assert files
    offenders = {f.name: _violations(f) for f in files if _violations(f)}
    assert offenders == {}


def test_scanner_detects_violations(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text(
        "from app.api.dependencies.x import y\nfrom fastapi import HTTPException\n"
    )
    assert _violations(bad) == ["app.api.dependencies.x", "fastapi.HTTPException"]
