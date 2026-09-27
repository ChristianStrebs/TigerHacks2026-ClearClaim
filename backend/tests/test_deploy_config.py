"""Optional hosting configs must stay in sync with the code they deploy."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings

yaml = pytest.importorskip("yaml")

REPO = Path(__file__).resolve().parents[2]
RENDER = yaml.safe_load((REPO / "render.yaml").read_text("utf-8"))
VERCEL = json.loads((REPO / "frontend" / "vercel.json").read_text("utf-8"))
SECRETS = {"GEMINI_API_KEY", "SUPABASE_PUBLISHABLE_KEY"}


def _api_service() -> dict:
    (service,) = RENDER["services"]
    return service


def _env_vars() -> dict[str, dict]:
    return {var["key"]: var for var in _api_service()["envVars"]}


def test_render_builds_from_the_backend_folder() -> None:
    service = _api_service()
    backend = REPO / service["rootDir"]
    assert (backend / "requirements.txt").is_file()
    assert "-r requirements.txt" in service["buildCommand"]
    assert "app.main:app" in service["startCommand"]
    assert "$PORT" in service["startCommand"]
    assert "0.0.0.0" in service["startCommand"]


def test_render_health_check_path_is_a_real_route(client: TestClient) -> None:
    assert client.get(_api_service()["healthCheckPath"]).status_code == 200


def test_render_env_vars_are_ones_the_app_reads() -> None:
    aliases = {field.alias for field in Settings.model_fields.values()}
    for key in _env_vars():
        if key != "PYTHON_VERSION":
            assert key in aliases, key


def test_render_keeps_secrets_out_of_git() -> None:
    env = _env_vars()
    for key in SECRETS | {"CORS_ORIGINS"}:
        assert env[key].get("sync") is False
        assert "value" not in env[key]
    for var in env.values():
        assert not str(var.get("value", "")).startswith(("sb_secret_", "sb_publishable_", "AIza"))


def test_render_pins_a_full_python_version() -> None:
    assert re.fullmatch(r"3\.\d+\.\d+", _env_vars()["PYTHON_VERSION"]["value"])


def test_vercel_builds_the_vite_app_with_pnpm() -> None:
    frontend = REPO / "frontend"
    scripts = json.loads((frontend / "package.json").read_text("utf-8"))["scripts"]
    assert VERCEL["framework"] == "vite"
    assert VERCEL["buildCommand"] == "pnpm run build"
    assert "build" in scripts
    assert "--frozen-lockfile" in VERCEL["installCommand"]
    assert (frontend / "pnpm-lock.yaml").is_file()
    assert VERCEL["outputDirectory"] == "dist"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://clearclaim.vercel.app/", ["https://clearclaim.vercel.app"]),
        (
            " https://a.vercel.app , http://localhost:5173/ ,, ",
            ["https://a.vercel.app", "http://localhost:5173"],
        ),
        ("", []),
    ],
)
def test_cors_origins_tolerate_spaces_and_trailing_slashes(raw: str, expected: list[str]) -> None:
    assert Settings(CORS_ORIGINS=raw, _env_file=None).cors_origin_list == expected
