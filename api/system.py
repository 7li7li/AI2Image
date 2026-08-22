from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from api.support import require_admin, require_identity, resolve_image_base_url
from services.auth_service import auth_service
from services.background_task_service import background_task_service
from services.config import config
from services.email_service import send_email, send_password_reset_email, send_verification_email
from services.image_service import delete_images, list_images
from services.log_service import LOG_TYPE_AUDIT, audit_service, log_service
from services.proxy_service import test_proxy
from services.telegram_service import send_telegram_test_message
from services.webdav_service import get_webdav_config, save_webdav_config, sync_images_to_webdav


class SettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")


class ProxyTestRequest(BaseModel):
    url: str = ""


class LoginRequest(BaseModel):
    email: str = ""
    password: str = ""


class RegisterRequest(BaseModel):
    email: str = ""
    password: str = ""
    name: str = ""


class EmailVerificationRequest(BaseModel):
    email: str = ""
    code: str = ""


class ResendEmailVerificationRequest(BaseModel):
    email: str = ""
    password: str = ""


class PasswordResetRequest(BaseModel):
    email: str = ""


class PasswordResetConfirmRequest(BaseModel):
    email: str = ""
    code: str = ""
    password: str = ""


class SMTPTestRequest(BaseModel):
    to_email: str = ""


class ImageDeleteItem(BaseModel):
    id: str = ""
    record_id: str = ""
    url: str = ""


class ImageDeleteRequest(BaseModel):
    ids: list[str] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)
    items: list[ImageDeleteItem] = Field(default_factory=list)


class WebDAVConfigRequest(BaseModel):
    enabled: bool = False
    url: str = ""
    username: str = ""
    password: str = ""
    root_path: str = ""


class ImagesWebDAVSyncRequest(BaseModel):
    start_date: str = ""
    end_date: str = ""
    user_id: str = ""
    channel: str = ""
    request_id: str = ""
    ids: list[str] = Field(default_factory=list)


def create_router(app_version: str) -> APIRouter:
    router = APIRouter()

    def auth_payload(user: dict[str, object], token: str) -> dict[str, object]:
        return {
            "ok": True,
            "version": app_version,
            "role": user.get("role"),
            "subject_id": user.get("id"),
            "name": user.get("name"),
            "email": user.get("email"),
            "quota": user.get("quota"),
            "token": token,
        }

    def health_payload() -> dict[str, object]:
        storage = config.get_storage_backend()
        storage_health = storage.health_check()
        status = "healthy" if storage_health.get("status") == "healthy" else "unhealthy"
        return {
            "status": status,
            "version": app_version,
            "storage": storage_health,
            "background_tasks": background_task_service.stats(),
        }

    @router.post("/auth/login")
    async def login(body: LoginRequest | None = None, authorization: str | None = Header(default=None)):
        if body and body.email.strip():
            try:
                user, token = auth_service.login_user(email=body.email, password=body.password)
            except ValueError as exc:
                raise HTTPException(status_code=401, detail={"error": str(exc)}) from exc
            return auth_payload(user, token)
        identity = require_identity(authorization)
        return {
            "ok": True,
            "version": app_version,
            "role": identity.get("role"),
            "subject_id": identity.get("id"),
            "name": identity.get("name"),
            "email": identity.get("email"),
            "quota": identity.get("quota"),
        }

    @router.post("/auth/register")
    async def register(body: RegisterRequest):
        email = body.email.strip().lower()
        if not config.allow_user_registration:
            raise HTTPException(status_code=403, detail={"error": "user registration is disabled"})
        if not config.email_allowed_for_registration(email):
            raise HTTPException(status_code=403, detail={"error": "email is not allowed to register"})
        if config.email_verification_enabled and not config.smtp_configured:
            raise HTTPException(status_code=400, detail={"error": "smtp is not configured"})

        created_user_id = ""
        try:
            if config.email_verification_enabled:
                user, _ = auth_service.create_user(
                    email=email,
                    password=body.password,
                    name=body.name,
                    quota=config.new_user_initial_quota,
                    quota_expires_at=config.new_user_quota_expires_at(),
                    role="user",
                    status="pending",
                    email_verified=False,
                    create_session=False,
                )
                created_user_id = str(user.get("id") or "")
                user, code = auth_service.create_email_verification(email)
                try:
                    await run_in_threadpool(send_verification_email, to_email=email, code=code)
                except Exception as exc:
                    if created_user_id:
                        auth_service.delete_user(created_user_id)
                    raise HTTPException(
                        status_code=502,
                        detail={"error": f"failed to send verification email: {exc}"},
                    ) from exc
                return {
                    "ok": True,
                    "version": app_version,
                    "verification_required": True,
                    "email": user.get("email"),
                }
            user, token = auth_service.create_user(
                email=email,
                password=body.password,
                name=body.name,
                quota=config.new_user_initial_quota,
                quota_expires_at=config.new_user_quota_expires_at(),
                role="user",
                status="active",
                email_verified=True,
                create_session=True,
            )
            return {**auth_payload(user, token), "verification_required": False}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.post("/auth/verify-email")
    async def verify_email(body: EmailVerificationRequest):
        if not config.allow_user_registration:
            raise HTTPException(status_code=403, detail={"error": "user registration is disabled"})
        try:
            user, token = auth_service.verify_email(email=body.email, code=body.code)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {**auth_payload(user, token), "verification_required": False}

    @router.post("/auth/resend-verification")
    async def resend_email_verification(body: ResendEmailVerificationRequest):
        if not config.allow_user_registration:
            raise HTTPException(status_code=403, detail={"error": "user registration is disabled"})
        if not config.email_verification_enabled:
            raise HTTPException(status_code=400, detail={"error": "email verification is disabled"})
        if not config.smtp_configured:
            raise HTTPException(status_code=400, detail={"error": "smtp is not configured"})
        email = body.email.strip().lower()
        try:
            user, code = auth_service.create_email_verification(email, body.password)
            await run_in_threadpool(send_verification_email, to_email=email, code=code)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail={"error": f"failed to send verification email: {exc}"}) from exc
        return {
            "ok": True,
            "version": app_version,
            "verification_required": True,
            "email": user.get("email"),
        }

    @router.post("/auth/password-reset/request")
    async def request_password_reset(body: PasswordResetRequest):
        if not config.smtp_configured:
            raise HTTPException(status_code=400, detail={"error": "smtp is not configured"})
        email = body.email.strip().lower()
        try:
            _, code = auth_service.create_password_reset(email)
        except ValueError:
            return {"ok": True, "version": app_version}
        try:
            await run_in_threadpool(send_password_reset_email, to_email=email, code=code)
        except Exception as exc:
            raise HTTPException(status_code=502, detail={"error": f"failed to send password reset email: {exc}"}) from exc
        return {"ok": True, "version": app_version}

    @router.post("/auth/password-reset/confirm")
    async def confirm_password_reset(body: PasswordResetConfirmRequest):
        try:
            auth_service.reset_password_with_code(
                email=body.email,
                code=body.code,
                password=body.password,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {"ok": True, "version": app_version}

    @router.get("/version")
    async def get_version():
        return {"version": app_version}

    @router.get("/health")
    async def health_check():
        return health_payload()

    @router.get("/api/health")
    async def api_health_check(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return health_payload()

    @router.get("/api/public/settings")
    async def get_public_settings():
        return {"settings": config.public_settings()}

    @router.get("/api/public/auth-settings")
    async def get_public_auth_settings():
        return {"settings": config.public_auth_settings()}

    @router.get("/api/announcements")
    async def get_announcements(authorization: str | None = Header(default=None)):
        require_identity(authorization)
        return {"items": config.public_announcements()}

    @router.get("/api/settings")
    async def get_settings(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"config": config.get()}

    @router.post("/api/settings")
    async def save_settings(body: SettingsUpdateRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"config": config.update(body.model_dump(mode="python"))}

    @router.post("/api/settings/smtp/test")
    async def test_smtp(body: SMTPTestRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        to_email = body.to_email.strip().lower() or config.smtp_from_email
        if not to_email:
            raise HTTPException(status_code=400, detail={"error": "test recipient email is required"})
        try:
            await run_in_threadpool(
                send_email,
                to_email=to_email,
                subject=f"{config.site_title} SMTP 测试邮件",
                text=f"这是一封来自 {config.site_title} 的 SMTP 配置测试邮件。",
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail={"error": str(exc)}) from exc
        return {"ok": True}

    @router.post("/api/settings/telegram/test")
    async def test_telegram(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            await run_in_threadpool(send_telegram_test_message)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail={"error": str(exc)}) from exc
        return {"ok": True}

    @router.get("/api/images")
    async def get_images(
            request: Request,
            start_date: str = "",
            end_date: str = "",
            user_id: str = "",
            channel: str = "",
            request_id: str = "",
            page: int = 1,
            page_size: int = 48,
            authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        return list_images(
            resolve_image_base_url(request),
            start_date=start_date.strip(),
            end_date=end_date.strip(),
            owner_user_id=user_id.strip(),
            channel=channel.strip(),
            request_id=request_id.strip(),
            page=page,
            page_size=page_size,
        )

    @router.delete("/api/images")
    async def delete_image_items(body: ImageDeleteRequest, authorization: str | None = Header(default=None)):
        admin = require_admin(authorization)
        record_ids = [
            *body.ids,
            *[item.record_id or item.id for item in body.items if item.record_id or item.id],
        ]
        urls = [
            *body.urls,
            *[item.url for item in body.items if item.url],
        ]
        if not any(str(value or "").strip() for value in [*record_ids, *urls]):
            raise HTTPException(status_code=400, detail={"error": "image ids or urls are required"})
        result = delete_images(record_ids=record_ids, urls=urls)
        audit_service.add(
            actor=admin,
            action="images.delete",
            resource="image",
            target_id=",".join(str(value) for value in record_ids[:5] if str(value).strip()),
            detail={
                "requested": len(body.items) or len(record_ids) or len(urls),
                **result,
            },
        )
        return result

    @router.get("/api/images/webdav")
    async def get_images_webdav(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"webdav": get_webdav_config("admin")}

    @router.post("/api/images/webdav")
    async def save_images_webdav(body: WebDAVConfigRequest, authorization: str | None = Header(default=None)):
        admin = require_admin(authorization)
        try:
            webdav = save_webdav_config("admin", body.model_dump(mode="python"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        audit_service.add(
            actor=admin,
            action="images.webdav.update",
            resource="image_webdav",
            detail={
                "enabled": webdav.get("enabled"),
                "url": webdav.get("url"),
                "root_path": webdav.get("root_path"),
                "password_set": webdav.get("password_set"),
            },
        )
        return {"webdav": webdav}

    @router.post("/api/images/webdav/sync")
    async def sync_images_webdav(body: ImagesWebDAVSyncRequest, authorization: str | None = Header(default=None)):
        admin = require_admin(authorization)
        try:
            result = await run_in_threadpool(
                sync_images_to_webdav,
                scope="admin",
                identity=admin,
                filters={
                    "start_date": body.start_date.strip(),
                    "end_date": body.end_date.strip(),
                    "owner_user_id": body.user_id.strip(),
                    "channel": body.channel.strip(),
                    "request_id": body.request_id.strip(),
                    "record_ids": [item.strip() for item in body.ids if item.strip()],
                },
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        audit_service.add(
            actor=admin,
            action="images.webdav.sync",
            resource="image",
            detail=result,
        )
        return {"result": result}

    @router.get("/api/logs")
    async def get_logs(
            type: str = "",
            start_date: str = "",
            end_date: str = "",
            request_id: str = "",
            status: str = "",
            user: str = "",
            page: int = 1,
            page_size: int = 50,
            authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        if type.strip() == LOG_TYPE_AUDIT:
            return audit_service.query(
                start_date=start_date.strip(),
                end_date=end_date.strip(),
                request_id=request_id.strip(),
                user=user.strip(),
                page=page,
                page_size=page_size,
            )
        return log_service.query(
            type=type.strip(),
            start_date=start_date.strip(),
            end_date=end_date.strip(),
            request_id=request_id.strip(),
            status=status.strip(),
            user=user.strip(),
            page=page,
            page_size=page_size,
        )

    @router.get("/api/audit-logs")
    async def get_audit_logs(
            action: str = "",
            resource: str = "",
            start_date: str = "",
            end_date: str = "",
            request_id: str = "",
            user: str = "",
            page: int = 1,
            page_size: int = 50,
            authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        return audit_service.query(
            action=action.strip(),
            resource=resource.strip(),
            start_date=start_date.strip(),
            end_date=end_date.strip(),
            request_id=request_id.strip(),
            user=user.strip(),
            page=page,
            page_size=page_size,
        )

    @router.post("/api/proxy/test")
    async def test_proxy_endpoint(body: ProxyTestRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        candidate = (body.url or "").strip() or config.get_proxy_settings()
        if not candidate:
            raise HTTPException(status_code=400, detail={"error": "proxy url is required"})
        return {"result": await run_in_threadpool(test_proxy, candidate)}

    @router.get("/api/storage/info")
    async def get_storage_info(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        storage = config.get_storage_backend()
        return {
            "backend": storage.get_backend_info(),
            "health": storage.health_check(),
        }

    return router
