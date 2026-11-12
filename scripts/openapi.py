"""make openapi: write every service's OpenAPI document to openapi/<api name>.json
(the folder is git-ignored: generated, for the web team and API tools)."""

import importlib
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("OUTBOX_RELAY_ENABLED", "false")
os.environ.setdefault("EVENT_CONSUMER_ENABLED", "false")
os.environ["KHQR_PROVIDER"] = "fake"  # the documents do not depend on it; .env may say payway (keys only in Docker)
SERVICES = ("auth", "branch", "catalog", "inventory", "stockcount", "prescription", "controlled", "sales",
            "customers", "purchasing", "reports", "notification", "document", "ai")  # fmt: skip


def main() -> int:
    out = Path(__file__).resolve().parents[1] / "openapi"
    out.mkdir(exist_ok=True)
    for service in SERVICES:
        app = importlib.import_module(f"{service}_service.main").app
        name = app.state.settings.api_prefix.split("/")[2]
        doc = app.openapi()
        (out / f"{name}.json").write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
        print(f"openapi/{name}.json  {sum(len(m) for m in doc['paths'].values())} operations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
