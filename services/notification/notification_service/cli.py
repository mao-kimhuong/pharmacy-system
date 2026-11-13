"""Telegram bot set-up. Prints no token or secret.

  python -m notification_service.cli set-webhook --url https://pharmacy.example.com
      → Telegram posts updates to <url>/api/notifications/v1/telegram/webhook with TELEGRAM_WEBHOOK_SECRET
  python -m notification_service.cli webhook-info
  python -m notification_service.cli delete-webhook      (before TELEGRAM_MODE=polling)
"""

import argparse
import asyncio
import sys

from .config import get_settings
from .services.telegram import Sender


async def _run(args: argparse.Namespace) -> int:
    s = get_settings()
    if not s.telegram_bot_token:
        print("TELEGRAM_BOT_TOKEN is not set")
        return 1
    sender = Sender(s)
    if args.command == "set-webhook":
        if len(s.telegram_webhook_secret) < 32:
            print("TELEGRAM_WEBHOOK_SECRET is not set (32+ characters of A-Z a-z 0-9 _ -)")
            return 1
        url = args.url.rstrip("/") + f"{s.api_prefix}/telegram/webhook"
        status, body = await sender.call("setWebhook", {
            "url": url, "secret_token": s.telegram_webhook_secret, "allowed_updates": ["message", "callback_query"],
            "drop_pending_updates": False})  # fmt: skip
        print(f"setWebhook {url}: {status} {body.get('description') or body.get('ok')}")
        await sender.call("setMyCommands", {"commands": [
            {"command": "settings", "description": "Choose your messages / ជ្រើសរើសសារ"},
            {"command": "stop", "description": "Stop and unlink / បញ្ឈប់"},
            {"command": "help", "description": "Help / ជំនួយ"}]})  # fmt: skip
        return 0 if status == 200 else 1
    if args.command == "delete-webhook":
        status, body = await sender.call("deleteWebhook", {"drop_pending_updates": False})
        print(f"deleteWebhook: {status} {body.get('description') or body.get('ok')}")
        return 0 if status == 200 else 1
    status, body = await sender.call("getWebhookInfo")
    info = body.get("result") or {}
    print(f"url: {info.get('url') or '(none)'} · pending: {info.get('pending_update_count')} · "
          f"last error: {info.get('last_error_message') or '-'}")  # fmt: skip
    return 0 if status == 200 else 1


def main() -> None:
    parser = argparse.ArgumentParser(prog="notification_service.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    hook = sub.add_parser("set-webhook", help="Point Telegram at this server")
    hook.add_argument("--url", required=True, help="The public https address of the stack")
    sub.add_parser("webhook-info")
    sub.add_parser("delete-webhook")
    sys.exit(asyncio.run(_run(parser.parse_args())))


if __name__ == "__main__":
    main()
