"""The auth routes a logged-out user needs must not sit behind auth-forward.

Regression: /api/auth/v1/login/2fa matched only the protected `auth` router, so an
owner with 2FA turned on (code or backup code) got 401 from Traefik and could not log in.
"""

import re
from pathlib import Path

import pytest

COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.yml"
LABEL = re.compile(r"traefik\.http\.routers\.([\w-]+)\.(rule|priority|middlewares)=(.+)$")
MATCHER = re.compile(r"(Path|PathPrefix)\(`([^`]+)`\)")


def _routers() -> dict[str, dict[str, str]]:
    if not COMPOSE.exists():
        pytest.skip("docker-compose.yml not in this checkout")
    routers: dict[str, dict[str, str]] = {}
    for line in COMPOSE.read_text().splitlines():
        found = LABEL.search(line.strip())
        if found:
            routers.setdefault(found[1], {})[found[2]] = found[3]
    return routers


def _matches(rule: str, path: str) -> bool:
    # rules here are only Path / PathPrefix joined by ||
    return any(path == p if kind == "Path" else path.startswith(p) for kind, p in MATCHER.findall(rule))


def _router_for(path: str) -> tuple[str, dict[str, str]]:
    hits = [(name, r) for name, r in _routers().items() if "rule" in r and _matches(r["rule"], path)]
    assert hits, f"no router for {path}"
    return max(hits, key=lambda hit: int(hit[1].get("priority", "0")))


@pytest.mark.parametrize("path", ["/api/auth/v1/login", "/api/auth/v1/login/2fa", "/api/auth/v1/refresh"])
def test_logged_out_auth_routes_are_public(path: str) -> None:
    name, router = _router_for(path)
    assert "auth-forward" not in router.get("middlewares", ""), f"{path} goes through {name} (auth-forward)"


def test_login_steps_share_the_strict_rate_limit() -> None:
    assert "ratelimit-login" in _router_for("/api/auth/v1/login/2fa")[1]["middlewares"]


@pytest.mark.parametrize(
    "path", ["/api/auth/v1/me/2fa/disable", "/api/auth/v1/me/2fa/reset", "/api/auth/v1/me/2fa/reset/confirm", "/api/auth/v1/2fa/backup-codes"]
)
def test_two_factor_checks_are_protected_and_limited_like_login(path: str) -> None:
    middlewares = _router_for(path)[1]["middlewares"]
    assert "auth-forward" in middlewares and "ratelimit-login" in middlewares


def test_everything_else_in_auth_is_protected() -> None:
    assert "auth-forward" in _router_for("/api/auth/v1/me")[1]["middlewares"]


@pytest.mark.parametrize(
    "path",
    ["/api/auth/v1/login", "/api/auth/v1/me", "/api/sales/v1/invoices", "/api/reports/v1/dashboard", "/api/documents/v1/render"],
)
def test_api_paths_never_reach_the_web_app(path: str) -> None:
    # The web router is PathPrefix(`/`) at priority 1: every API router must win.
    assert _router_for(path)[0] != "web"


def test_web_app_is_public_static_files() -> None:
    name, router = _router_for("/pos")
    assert name == "web"
    assert "auth-forward" not in router["middlewares"]


def test_web_app_files_have_their_own_larger_limit() -> None:
    # A service worker install fetches every precached file at once; several tills share one IP.
    middlewares = _router_for("/assets/index.js")[1]["middlewares"]
    assert "ratelimit-static" in middlewares and "ratelimit-flood" not in middlewares
    text = (COMPOSE.parent / "traefik" / "dynamic" / "middlewares.yml").read_text()
    burst = int(re.search(r"ratelimit-static:\s+rateLimit:(?:\s+\w+: \S+)*?\s+burst: (\d+)", text)[1])
    assert burst >= 1000
