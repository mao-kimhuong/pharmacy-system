"""Two-factor login with an authenticator app (TOTP, 6 digits, 30 seconds).

- The secret is encrypted in the database (Fernet).
- A code is accepted for the current 30-second step and one step either side
  (phone clocks drift), and each step can be used only once.
"""

import base64
import hashlib
import io
import time

import pyotp
import segno
from cryptography.fernet import Fernet, InvalidToken

from ..config import Settings
from ..models import User

STEP_SECONDS = 30


def _fernet(settings: Settings) -> Fernet:
    key = settings.totp_encryption_key
    if not key:
        digest = hashlib.sha256(("totp:" + settings.jwt_secret).encode()).digest()
        key = base64.urlsafe_b64encode(digest).decode()
    return Fernet(key.encode())


def encrypt_secret(secret: str, settings: Settings) -> str:
    return _fernet(settings).encrypt(secret.encode()).decode()


def decrypt_secret(token: str, settings: Settings) -> str | None:
    try:
        return _fernet(settings).decrypt(token.encode()).decode()
    except InvalidToken:
        return None


def new_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, user: User, settings: Settings) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=user.phone, issuer_name=settings.totp_issuer)


def qr_svg_data_uri(uri: str) -> str:
    """The QR code to scan with the authenticator app, as an <img src> value."""
    out = io.BytesIO()
    segno.make(uri, error="m").save(out, kind="svg", scale=5, border=2)
    return "data:image/svg+xml;base64," + base64.b64encode(out.getvalue()).decode()


def check_code(
    user: User, code: str, settings: Settings, now: float | None = None, secret_enc: str | None = None
) -> bool:
    """True if the code is valid and not used before. Records the used step on the user.
    `secret_enc`: check against this secret (a pending new key) instead of the live one."""
    secret_enc = secret_enc or user.totp_secret_enc
    if not secret_enc or not code or not code.isdigit() or len(code) != 6:
        return False
    secret = decrypt_secret(secret_enc, settings)
    if secret is None:
        return False
    totp = pyotp.TOTP(secret)
    now = time.time() if now is None else now
    current = int(now // STEP_SECONDS)
    for step in (current, current - 1, current + 1):
        if totp.at(step * STEP_SECONDS) == code:
            if user.totp_last_step is not None and step <= user.totp_last_step:
                return False  # replayed code
            user.totp_last_step = step
            return True
    return False
