#!/usr/bin/env python3
"""End-to-end smoke test through Traefik (needs `make up` and `make owner` first).

    make smoke

S0 checks: health, protected routes, faked headers, login (+ 2FA), logout.
S1 checks (optional, you are asked): create a test branch, wait for the auth
service to learn about it over RabbitMQ, create a cashier there, check the
cashier's permissions, deactivate the cashier (logged out at once), User Log.
The test branch and cashier are deactivated at the end.

Uses only the Python standard library.
"""

import getpass
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("BASE_URL", "http://localhost").rstrip("/")
PREFIXES = [
    "auth", "branch", "catalog", "inventory", "stockcount", "prescription", "controlled",
    "sales", "customers", "purchasing", "reports", "notifications", "documents", "ai",
]  # fmt: skip
results: list[tuple[bool, str]] = []


def call(
    method: str, path: str, body: dict | None = None, token: str | None = None, headers: dict | None = None
):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=dict(headers or {}))
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as err:
        raw = err.read()
        try:
            return err.code, json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return err.code, {"raw": raw.decode(errors="replace")}
    except urllib.error.URLError as err:
        print(f"Cannot reach {BASE}: {err.reason}. Is the stack running (make up)?")
        sys.exit(2)


def check(ok: bool, label: str) -> bool:
    results.append((bool(ok), label))
    print(("  PASS  " if ok else "  FAIL  ") + label)
    return bool(ok)


def owner_login() -> dict | None:
    phone = os.environ.get("SMOKE_PHONE") or input("Owner phone: ")
    password = os.environ.get("SMOKE_PASSWORD") or getpass.getpass("Owner password: ")
    status, data = call("POST", "/api/auth/v1/login", {"phone": phone, "password": password})
    if not check(status == 200, f"owner login -> 200 (got {status} {data.get('code', '')})"):
        return None

    if data.get("mfa_required"):
        code = input("6-digit code from your authenticator app: ").strip()
        status, data = call("POST", "/api/auth/v1/login/2fa", {"mfa_token": data["mfa_token"], "code": code})
        if not check(status == 200, f"2FA code accepted (got {status} {data.get('code', '')})"):
            return None

    if data.get("mfa_setup_required"):
        status, _ = call("GET", "/api/sales/v1/whoami", token=data["access_token"])
        check(status == 403, f"before 2FA set-up, other services are blocked -> 403 (got {status})")
        print("\n  Two-factor login is required for the owner. Set it up now:")
        status, setup = call("POST", "/api/auth/v1/2fa/setup", token=data["access_token"])
        if not check(status == 200, f"2FA set-up started (got {status})"):
            return None
        print("  In Google Authenticator / Microsoft Authenticator / 2FAS, add an account")
        print(f"  with this key:  {setup['secret']}")
        print("  (or open the QR code from the API docs: POST /api/auth/v1/2fa/setup)\n")
        code = input("  6-digit code shown in the app: ").strip()
        status, data = call("POST", "/api/auth/v1/2fa/enable", {"code": code}, token=data["access_token"])
        if not check(status == 200, f"2FA turned on (got {status} {data.get('code', '')})"):
            return None
    return data


def s0_checks() -> dict | None:
    healthy = [p for p in PREFIXES if call("GET", f"/api/{p}/v1/health")[0] == 200]
    check(len(healthy) == len(PREFIXES), f"health is public on all services ({len(healthy)}/{len(PREFIXES)})")
    status, _ = call("GET", "/api/sales/v1/whoami")
    check(status == 401, f"protected endpoint without token -> 401 (got {status})")
    fake = {"X-User-Id": "11111111-1111-1111-1111-111111111111", "X-Role": "owner", "X-Permissions": "*"}
    status, _ = call("GET", "/api/sales/v1/whoami", headers=fake)
    check(status == 401, f"faked identity headers are ignored -> 401 (got {status})")

    tokens = owner_login()
    if tokens is None:
        return None
    token = tokens["access_token"]
    status, who = call("GET", "/api/sales/v1/whoami", token=token)
    check(
        status == 200 and who.get("permissions") == ["*"],
        f"owner reaches other services with all permissions ({status})",
    )
    status, who = call(
        "GET",
        "/api/sales/v1/whoami",
        token=token,
        headers={**fake, "X-User-Id": "2" * 8 + "-2222-2222-2222-" + "2" * 12},
    )
    check(
        status == 200 and who.get("user_id") == tokens["user"]["id"],
        "with a token, faked headers are replaced",
    )
    status, me = call("GET", "/api/auth/v1/me", token=token)
    check(
        status == 200 and len(me.get("menu", [])) > 10,
        f"/me returns permissions and menu ({len(me.get('menu', []))} items)",
    )
    return tokens


def s1_checks(token: str) -> None:
    code = f"T{random.randint(1000, 9999)}"
    status, branch = call(
        "POST",
        "/api/branch/v1/branches",
        {"code": code, "name_km": "សាខាតេស្ត", "name_en": f"Smoke test {code}"},
        token=token,
    )
    if not check(status == 201, f"create test branch {code} -> 201 (got {status} {branch.get('code', '')})"):
        return
    bid = branch["id"]

    phone = f"09{random.randint(1000000, 9999999)}"
    password = f"smoke-{random.randint(100000, 999999)}"
    body = {
        "name": "Smoke cashier",
        "phone": phone,
        "password": password,
        "role": "cashier",
        "branch_ids": [bid],
    }
    status, cashier = 0, {}
    for _ in range(20):  # the branch reaches the auth service through RabbitMQ
        status, cashier = call("POST", "/api/auth/v1/users", body, token=token)
        if cashier.get("code") != "UNKNOWN_BRANCH":
            break
        time.sleep(0.5)
    if not check(
        status == 201,
        f"auth learned the branch over RabbitMQ; cashier created -> 201 (got {status} {cashier.get('code', '')})",
    ):
        call("POST", f"/api/branch/v1/branches/{bid}/deactivate", {"reason": "smoke test"}, token=token)
        return

    status, ctok = call("POST", "/api/auth/v1/login", {"phone": phone, "password": password})
    check(status == 200, f"cashier logs in without 2FA -> 200 (got {status})")
    ctoken = ctok.get("access_token", "")
    status, who = call("GET", "/api/sales/v1/whoami", token=ctoken)
    check(status == 200 and "pos.sell" in who.get("permissions", []), "cashier has pos.sell")
    check("settings.users" not in who.get("permissions", []), "cashier does not have settings.users")
    status, _ = call("GET", "/api/auth/v1/users", token=ctoken)
    check(status == 403, f"cashier opening user management -> 403 (got {status})")
    status, _ = call("GET", "/api/branch/v1/branches", token=ctoken)
    check(status == 200, "cashier sees their branch")

    status, _ = call(
        "POST", f"/api/auth/v1/users/{cashier['id']}/deactivate", {"reason": "smoke test"}, token=token
    )
    check(status == 200, f"owner deactivates the cashier -> 200 (got {status})")
    status, _ = call("GET", "/api/sales/v1/whoami", token=ctoken)
    check(status == 401, f"deactivated cashier is logged out at once -> 401 (got {status})")

    status, log = call("GET", "/api/auth/v1/audit-logs?action=user.deactivated&size=5", token=token)
    check(status == 200 and log.get("total", 0) >= 1, "User Log shows the deactivation")
    found = False
    for _ in range(20):  # branch.created comes from the branch service as an event
        status, log = call(
            "GET", f"/api/auth/v1/audit-logs?action=branch.created&entity_id={bid}", token=token
        )
        if log.get("total"):
            found = True
            break
        time.sleep(0.5)
    check(found, "User Log shows the branch creation sent by the branch service")

    status, _ = call(
        "POST", f"/api/branch/v1/branches/{bid}/deactivate", {"reason": "smoke test"}, token=token
    )
    check(status == 200, "test branch deactivated")


def main() -> int:
    print(f"Smoke test against {BASE}\n")
    tokens = s0_checks()
    if tokens is None:
        return summary()
    run_s1 = os.environ.get("SMOKE_S1") or input(
        "\nAlso run the S1 checks? It creates a test branch and cashier, then deactivates them. [y/N] "
    )
    if run_s1.strip().lower() in ("y", "yes", "1"):
        print()
        s1_checks(tokens["access_token"])

    status, _ = call(
        "POST",
        "/api/auth/v1/logout",
        {"refresh_token": tokens["refresh_token"]},
        token=tokens["access_token"],
    )
    check(status == 204, f"logout -> 204 (got {status})")
    status, _ = call("GET", "/api/sales/v1/whoami", token=tokens["access_token"])
    check(status == 401, f"same token after logout -> 401 (got {status})")
    return summary()


def summary() -> int:
    failed = [label for ok, label in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
