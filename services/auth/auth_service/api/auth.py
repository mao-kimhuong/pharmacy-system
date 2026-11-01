from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser, current_user
from pharmacy_shared.errors import AppError, ErrorCode

from ..config import Settings, get_settings
from ..db import db
from ..models import User
from ..permissions import menu_for
from ..schemas.auth import (
    BackupCodesOut,
    BackupCodesRequest,
    ChangePasswordRequest,
    Login2faRequest,
    LoginRequest,
    LogoutRequest,
    MenuItemOut,
    MeResponse,
    RefreshRequest,
    SessionOut,
    SetPinRequest,
    TokenResponse,
    TwoFactorEnableRequest,
    TwoFactorSetupResponse,
)
from ..services import auth as auth_service
from ..services import backup_codes, two_factor
from ..services import my_sessions as sessions_service
from ..services import users as users_service
from ..services.access import load_permissions, mfa_setup_required
from ..services.audit import write_audit
from ..services.passwords import verify_password
from ..services.tokens import AccessClaims, decode_access_token

router = APIRouter(tags=["auth"])


async def get_redis(request: Request) -> Redis:
    return request.app.state.redis.client()


def client_info(request: Request) -> auth_service.ClientInfo:
    forwarded = request.headers.get("x-forwarded-for", "")
    ip = forwarded.split(",")[0].strip() or (request.client.host if request.client else None)
    return auth_service.ClientInfo(ip=ip, user_agent=request.headers.get("user-agent"))


def bearer_claims(
    authorization: str | None = Header(default=None), settings: Settings = Depends(get_settings)
) -> AccessClaims:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AppError(ErrorCode.NOT_AUTHENTICATED, "Missing bearer token", status_code=401)
    return decode_access_token(authorization[7:].strip(), settings)


def me_response(user: User, permissions: list[str], settings: Settings) -> MeResponse:
    out = MeResponse.model_validate(user)
    out.has_pin = user.pin_hash is not None
    out.permissions = permissions
    out.menu = [MenuItemOut(**item) for item in menu_for(set(permissions))]
    out.mfa_setup_required = mfa_setup_required(user, settings)
    return out


def token_response(tokens: auth_service.IssuedTokens, settings: Settings) -> TokenResponse:
    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
        user=me_response(tokens.user, tokens.permissions, settings),
        mfa_setup_required=tokens.mfa_setup_required,
    )


@router.post("/login", response_model=TokenResponse, response_model_exclude_none=True)
async def login(
    body: LoginRequest,
    request: Request,
    session: AsyncSession = Depends(db.session),
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    """Step 1. If `mfa_required` comes back, send the 6-digit code to /login/2fa."""
    result = await auth_service.login(
        session, redis, settings, body.phone, body.password, client_info(request)
    )
    if isinstance(result, auth_service.MfaChallenge):
        return TokenResponse(mfa_required=True, mfa_token=result.mfa_token)
    return token_response(result, settings)


@router.post("/login/2fa", response_model=TokenResponse, response_model_exclude_none=True)
async def login_2fa(
    body: Login2faRequest,
    request: Request,
    session: AsyncSession = Depends(db.session),
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    """Step 2: the 6-digit code from the authenticator app, or (lost phone) one backup code."""
    tokens = await auth_service.login_2fa(
        session, redis, settings, body.mfa_token, body.code, client_info(request), body.backup_code
    )
    return token_response(tokens, settings)


@router.post("/refresh", response_model=TokenResponse, response_model_exclude_none=True)
async def refresh(
    body: RefreshRequest,
    request: Request,
    session: AsyncSession = Depends(db.session),
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    tokens = await auth_service.refresh(session, redis, settings, body.refresh_token, client_info(request))
    return token_response(tokens, settings)


@router.post("/logout", status_code=204)
async def logout(
    body: LogoutRequest | None = None,
    claims: AccessClaims = Depends(bearer_claims),
    session: AsyncSession = Depends(db.session),
    redis: Redis = Depends(get_redis),
) -> Response:
    body = body or LogoutRequest()
    await auth_service.logout(session, redis, claims, body.refresh_token, body.all_devices)
    return Response(status_code=204)


@router.get("/me", response_model=MeResponse)
async def me(
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(db.session),
    settings: Settings = Depends(get_settings),
) -> MeResponse:
    """The logged-in user, their permissions and the menu items to show.
    The front end also hides items whose feature is off (branch service /features)."""
    account = await session.get(User, user.id)
    if account is None or not account.is_active:
        raise AppError(ErrorCode.NOT_AUTHENTICATED, "Not authenticated", status_code=401)
    out = me_response(account, await load_permissions(session, account.role), settings)
    if account.totp_enabled:
        out.backup_codes_left = await backup_codes.left(session, account.id)
    return out


@router.post("/me/password", status_code=204)
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(db.session),
    redis: Redis = Depends(get_redis),
) -> Response:
    """Change your own password. All your sessions end; log in again."""
    await users_service.change_own_password(
        session, redis, user.id, body.current_password, body.new_password, client_info(request).ip
    )
    return Response(status_code=204)


@router.put("/me/pin", status_code=204)
async def set_pin(
    body: SetPinRequest,
    request: Request,
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(db.session),
) -> Response:
    """Set your 4-6 digit PIN (controlled-drug dispensing, quick user switch on shared POS)."""
    await users_service.set_own_pin(session, user.id, body.password, body.pin, client_info(request).ip)
    return Response(status_code=204)


@router.post("/2fa/setup", response_model=TwoFactorSetupResponse, tags=["2fa"])
async def setup_2fa(
    claims: AccessClaims = Depends(bearer_claims),
    session: AsyncSession = Depends(db.session),
    settings: Settings = Depends(get_settings),
) -> TwoFactorSetupResponse:
    """Show the QR code to scan with an authenticator app."""
    info = await two_factor.start_setup(session, settings, claims.user_id)
    return TwoFactorSetupResponse(secret=info.secret, otpauth_uri=info.otpauth_uri, qr_svg=info.qr_svg)


@router.post("/2fa/enable", response_model=TokenResponse, response_model_exclude_none=True, tags=["2fa"])
async def enable_2fa(
    body: TwoFactorEnableRequest,
    request: Request,
    claims: AccessClaims = Depends(bearer_claims),
    session: AsyncSession = Depends(db.session),
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    """Confirm with the first 6-digit code. Returns new tokens that open everything, and
    10 backup codes (shown only now)."""
    tokens = await two_factor.enable(session, redis, settings, claims, body.code, client_info(request))
    codes = await backup_codes.regenerate(session, tokens.user)
    await session.commit()
    out = token_response(tokens, settings)
    out.backup_codes = codes
    return out


@router.post("/2fa/backup-codes", response_model=BackupCodesOut, tags=["2fa"])
async def new_backup_codes(
    body: BackupCodesRequest, request: Request, claims: AccessClaims = Depends(bearer_claims),
    session: AsyncSession = Depends(db.session),
) -> BackupCodesOut:  # fmt: skip
    """A new set of 10 backup codes (your password; the old set stops working). Shown only now."""
    user = await session.get(User, claims.user_id, with_for_update=True)
    if user is None or not user.is_active or not verify_password(user.password_hash, body.password):
        raise AppError(ErrorCode.INVALID_CREDENTIALS, "Wrong password", status_code=401)
    if not user.totp_enabled:
        raise AppError(ErrorCode.VALIDATION_ERROR, "Turn two-factor login on first", status_code=409)
    codes = await backup_codes.regenerate(session, user)
    write_audit(session, action="user.backup_codes_regenerated", entity_type="user", entity_id=user.id,
                actor_id=user.id, actor_role=user.role, branch_id=user.branch_ids[0] if user.branch_ids else None,
                after={"codes": len(codes)}, ip=client_info(request).ip, only_changes=False)  # fmt: skip
    await session.commit()
    return BackupCodesOut(codes=codes)


@router.get("/me/sessions", response_model=list[SessionOut])
async def my_sessions(claims: AccessClaims = Depends(bearer_claims), session: AsyncSession = Depends(db.session)) -> list:
    """Where you are logged in (one row per login), newest first; `current` = this one."""
    return await sessions_service.list_sessions(session, claims)


@router.post("/me/sessions/{session_id}/revoke", status_code=204)
async def revoke_session(
    session_id: UUID, request: Request, claims: AccessClaims = Depends(bearer_claims),
    session: AsyncSession = Depends(db.session), redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> Response:  # fmt: skip
    """End one of your sessions at once (revoking the current one logs you out)."""
    await sessions_service.revoke(session, redis, settings, claims, session_id, client_info(request).ip)
    return Response(status_code=204)


@router.get("/verify", include_in_schema=False)
async def verify(
    authorization: str | None = Header(default=None),
    x_forwarded_uri: str | None = Header(default=None),
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Traefik ForwardAuth target. 200 + identity headers, or 401/403."""
    claims = await auth_service.verify(redis, settings, authorization, x_forwarded_uri)
    return Response(
        status_code=200,
        headers={
            "X-User-Id": str(claims.user_id),
            "X-Role": claims.role,
            "X-Branch-Ids": ",".join(str(b) for b in claims.branch_ids),
            "X-Is-Pharmacist": "true" if claims.is_pharmacist else "false",
            "X-Permissions": ",".join(claims.permissions),
        },
    )
