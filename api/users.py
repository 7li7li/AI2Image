from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.support import require_admin, require_identity, resolve_image_base_url
from services.auth_service import DEFAULT_USER_IMAGE_CHANNEL_MODELS, auth_service
from services.channel_service import channel_service
from services.image_service import collect_downloadable_images, delete_images, list_images
from services.log_service import audit_service
from services.model_service import model_service
from services.config import config
from services.payment_service import payment_service
from services.webdav_service import get_webdav_config, save_webdav_config, sync_images_to_webdav


class ProfileUpdateRequest(BaseModel):
    name: str | None = None


class UserImageChannelRequest(BaseModel):
    enabled: bool = False
    name: str = ""
    base_url: str = ""
    api_key: str = ""
    models: list[str] | str = Field(default_factory=lambda: list(DEFAULT_USER_IMAGE_CHANNEL_MODELS))
    timeout: int = 600


class UserImageChannelTestRequest(UserImageChannelRequest):
    test_models: list[str] = Field(default_factory=list)


class WebDAVConfigRequest(BaseModel):
    enabled: bool = False
    url: str = ""
    username: str = ""
    password: str = ""
    root_path: str = ""


class ImageSelectionItem(BaseModel):
    id: str = ""
    record_id: str = ""
    url: str = ""


class ImageSelectionRequest(BaseModel):
    ids: list[str] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)
    items: list[ImageSelectionItem] = Field(default_factory=list)


class MyImagesWebDAVSyncRequest(BaseModel):
    start_date: str = ""
    end_date: str = ""
    ids: list[str] = Field(default_factory=list)


class RedeemRequest(BaseModel):
    code: str


class AdminUserCreateRequest(BaseModel):
    email: str
    password: str
    name: str = ""
    quota: float = 0
    quota_expires_at: str | None = None
    status: str = "active"


class AdminUserUpdateRequest(BaseModel):
    email: str | None = None
    name: str | None = None
    status: str | None = None
    quota: float | None = None
    quota_expires_at: str | None = None


class AdminUserQuotaRequest(BaseModel):
    amount: float
    mode: str = "add"
    quota_expires_at: str | None = None


class AdminUserSubscriptionRequest(BaseModel):
    plan_id: str = ""
    expires_at: str | None = None


class ResetPasswordRequest(BaseModel):
    password: str = ""


class IdsDeleteRequest(BaseModel):
    ids: list[str] = Field(default_factory=list)


class RedeemCodeCreateRequest(BaseModel):
    quota: int = Field(default=1, ge=1)
    count: int = Field(default=1, ge=1, le=500)
    max_uses: int = Field(default=1, ge=1)
    valid_months: int = Field(default=0, ge=0)
    expires_at: str | None = None
    note: str = ""


class RedeemCodeUpdateRequest(BaseModel):
    status: str | None = None
    quota: int | None = None
    max_uses: int | None = None
    valid_months: int | None = None
    expires_at: str | None = None
    note: str | None = None


class ChannelRequest(BaseModel):
    type: str = "openai_image"
    name: str = ""
    base_url: str = ""
    api_key: str = ""
    models: list[str] | str | None = None
    weight: int = 1
    priority: int = 0
    timeout: int = 600
    enabled: bool = True


class ChannelUpdateRequest(BaseModel):
    type: str | None = None
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    models: list[str] | str | None = None
    weight: int | None = None
    priority: int | None = None
    timeout: int | None = None
    enabled: bool | None = None


class ChannelModelTestRequest(BaseModel):
    models: list[str] = Field(default_factory=list)


class ModelPricingRequest(BaseModel):
    model: str = ""
    enabled: bool | None = None
    billing_mode: str | None = None
    currency: str | None = None
    input_price_per_million: float | None = None
    output_price_per_million: float | None = None
    model_ratio: float | None = None
    completion_ratio: float | None = None
    model_price: float | None = None
    image_resolutions: list[str] | None = None
    note: str | None = None


def _selection_targets(body: ImageSelectionRequest) -> tuple[list[str], list[str]]:
    record_ids = [
        *body.ids,
        *[item.record_id or item.id for item in body.items if item.record_id or item.id],
    ]
    urls = [
        *body.urls,
        *[item.url for item in body.items if item.url],
    ]
    return record_ids, urls


def _build_image_download_zip(downloads: list[dict[str, object]]) -> bytes:
    archive = BytesIO()
    with ZipFile(archive, mode="w", compression=ZIP_DEFLATED) as zip_file:
        for item in downloads:
            path = item.get("path")
            if not isinstance(path, Path):
                continue
            zip_file.write(path, arcname=str(item.get("name") or path.name))
    return archive.getvalue()


def create_router() -> APIRouter:
    router = APIRouter()

    def with_task_access(user: dict[str, object] | None) -> dict[str, object] | None:
        if user is None or user.get("role") != "user":
            return user
        access = payment_service.active_subscription_access(
            str(user.get("id") or ""),
            default=max(1, int(config.background_task_user_limit or 1)),
        )
        enriched = dict(user)
        enriched["task_concurrency"] = int(access["concurrency"])
        subscription = access.get("subscription")
        enriched["subscription"] = subscription
        enriched["subscription_concurrency"] = int(
            ((subscription or {}).get("concurrency") or 0)
        )
        enriched["community_groups"] = config.community_groups_for_user(
            has_subscription=subscription is not None
        )
        return enriched

    def with_resolved_task_access(user: dict[str, object], access: dict[str, object]) -> dict[str, object]:
        enriched = dict(user)
        enriched["task_concurrency"] = int(access["concurrency"])
        enriched["subscription"] = access.get("subscription")
        enriched["subscription_concurrency"] = int(
            ((access.get("subscription") or {}).get("concurrency") or 0)
        )
        return enriched

    def list_users_with_task_access(query: str = "", status: str = "", role: str = "") -> list[dict[str, object]]:
        users = auth_service.list_users(query=query, status=status, role=role)
        default = max(1, int(config.background_task_user_limit or 1))
        access_by_user = payment_service.active_subscription_accesses(users, default=default)
        return [
            with_resolved_task_access(
                user,
                access_by_user.get(str(user.get("id") or ""), {"concurrency": default, "subscription": None}),
            )
            if user.get("role") == "user"
            else user
            for user in users
        ]

    @router.get("/api/me")
    async def get_me(authorization: str | None = Header(default=None)):
        identity = require_identity(authorization)
        if identity.get("role") == "user":
            user = auth_service.get_user(str(identity.get("id") or ""))
            if user is not None:
                return {"user": with_task_access(user)}
        return {"user": identity}

    @router.post("/api/me/profile")
    async def update_profile(body: ProfileUpdateRequest, authorization: str | None = Header(default=None)):
        identity = require_identity(authorization)
        if identity.get("role") != "user":
            return {"user": identity}
        try:
            user = auth_service.update_user(str(identity.get("id") or ""), body.model_dump(exclude_none=True))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        if user is None:
            raise HTTPException(status_code=404, detail={"error": "user not found"})
        return {"user": with_task_access(user)}

    @router.get("/api/me/image-channel")
    async def get_my_image_channel(authorization: str | None = Header(default=None)):
        identity = require_identity(authorization)
        if identity.get("role") != "user":
            raise HTTPException(status_code=403, detail={"error": "user permission required"})
        try:
            channel = auth_service.get_user_image_channel_config(str(identity.get("id") or ""))
        except ValueError as exc:
            raise HTTPException(status_code=404, detail={"error": str(exc)}) from exc
        return {"channel": channel}

    @router.post("/api/me/image-channel")
    async def save_my_image_channel(body: UserImageChannelRequest, authorization: str | None = Header(default=None)):
        identity = require_identity(authorization)
        if identity.get("role") != "user":
            raise HTTPException(status_code=403, detail={"error": "user permission required"})
        user_id = str(identity.get("id") or "")
        try:
            channel = auth_service.save_user_image_channel_config(user_id, body.model_dump(mode="python"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        audit_service.add(
            actor=identity,
            action="me.image_channel.update",
            resource="image_channel",
            target_id=user_id,
            detail={
                "enabled": channel.get("enabled"),
                "name": channel.get("name"),
                "base_url": channel.get("base_url"),
                "models": channel.get("models"),
                "timeout": channel.get("timeout"),
                "has_api_key": channel.get("has_api_key"),
            },
        )
        return {"channel": channel, "user": with_task_access(auth_service.get_user(user_id))}

    @router.post("/api/me/image-channel/models/test")
    async def test_my_image_channel_models(
            body: UserImageChannelTestRequest | None = None,
            authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization)
        if identity.get("role") != "user":
            raise HTTPException(status_code=403, detail={"error": "user permission required"})
        user_id = str(identity.get("id") or "")
        updates = {} if body is None else body.model_dump(exclude={"test_models"}, mode="python")
        selected_models = [] if body is None else body.test_models
        try:
            channel_config = auth_service.merge_user_image_channel_config(
                user_id,
                updates,
                include_api_key=True,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        result = await run_in_threadpool(
            channel_service.test_personal_channel_models,
            channel_config,
            selected_models,
            owner_user_id=user_id,
        )
        return result

    @router.post("/api/me/redeem")
    async def redeem(body: RedeemRequest, authorization: str | None = Header(default=None)):
        identity = require_identity(authorization)
        if identity.get("role") != "user":
            raise HTTPException(status_code=403, detail={"error": "user permission required"})
        try:
            user, code = auth_service.redeem_code(str(identity.get("id") or ""), body.code)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {"user": with_task_access(user), "redeem_code": code}

    @router.get("/api/me/images")
    async def get_my_images(
            request: Request,
            start_date: str = "",
            end_date: str = "",
            request_id: str = "",
            page: int = 1,
            page_size: int = 48,
            authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization)
        if identity.get("role") != "user":
            raise HTTPException(status_code=403, detail={"error": "user permission required"})
        return list_images(
            resolve_image_base_url(request),
            start_date=start_date.strip(),
            end_date=end_date.strip(),
            owner_user_id=str(identity.get("id") or ""),
            request_id=request_id.strip(),
            page=page,
            page_size=page_size,
        )

    @router.delete("/api/me/images")
    async def delete_my_images(body: ImageSelectionRequest, authorization: str | None = Header(default=None)):
        identity = require_identity(authorization)
        if identity.get("role") != "user":
            raise HTTPException(status_code=403, detail={"error": "user permission required"})
        record_ids, urls = _selection_targets(body)
        if not any(str(value or "").strip() for value in [*record_ids, *urls]):
            raise HTTPException(status_code=400, detail={"error": "image ids or urls are required"})
        result = delete_images(
            record_ids=record_ids,
            urls=urls,
            owner_user_id=str(identity.get("id") or ""),
        )
        audit_service.add(
            actor=identity,
            action="me.images.delete",
            resource="image",
            target_id=",".join(str(value) for value in record_ids[:5] if str(value).strip()),
            detail={
                "requested": len(body.items) or len(record_ids) or len(urls),
                **result,
            },
        )
        return result

    @router.post("/api/me/images/download")
    async def download_my_images(body: ImageSelectionRequest, authorization: str | None = Header(default=None)):
        identity = require_identity(authorization)
        if identity.get("role") != "user":
            raise HTTPException(status_code=403, detail={"error": "user permission required"})
        record_ids, urls = _selection_targets(body)
        if not any(str(value or "").strip() for value in [*record_ids, *urls]):
            raise HTTPException(status_code=400, detail={"error": "image ids or urls are required"})
        downloads = await run_in_threadpool(
            collect_downloadable_images,
            record_ids=record_ids,
            urls=urls,
            owner_user_id=str(identity.get("id") or ""),
        )
        if not downloads:
            raise HTTPException(status_code=404, detail={"error": "no downloadable local image files found"})
        content = await run_in_threadpool(_build_image_download_zip, downloads)
        filename = f"my-images-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
        return StreamingResponse(
            iter([content]),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @router.get("/api/me/images/webdav")
    async def get_my_images_webdav(authorization: str | None = Header(default=None)):
        identity = require_identity(authorization)
        if identity.get("role") != "user":
            raise HTTPException(status_code=403, detail={"error": "user permission required"})
        return {"webdav": get_webdav_config("user", user_id=str(identity.get("id") or ""))}

    @router.post("/api/me/images/webdav")
    async def save_my_images_webdav(body: WebDAVConfigRequest, authorization: str | None = Header(default=None)):
        identity = require_identity(authorization)
        if identity.get("role") != "user":
            raise HTTPException(status_code=403, detail={"error": "user permission required"})
        try:
            webdav = save_webdav_config("user", body.model_dump(mode="python"), user_id=str(identity.get("id") or ""))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {"webdav": webdav}

    @router.post("/api/me/images/webdav/sync")
    async def sync_my_images_webdav(body: MyImagesWebDAVSyncRequest, authorization: str | None = Header(default=None)):
        identity = require_identity(authorization)
        if identity.get("role") != "user":
            raise HTTPException(status_code=403, detail={"error": "user permission required"})
        try:
            result = await run_in_threadpool(
                sync_images_to_webdav,
                scope="user",
                identity=identity,
                filters={
                    "start_date": body.start_date.strip(),
                    "end_date": body.end_date.strip(),
                    "record_ids": [item.strip() for item in body.ids if item.strip()],
                },
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {"result": result}

    @router.get("/api/admin/users")
    async def admin_list_users(
            query: str = "",
            status: str = "",
            role: str = "",
            authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        return {"items": list_users_with_task_access(query=query, status=status, role=role)}

    @router.post("/api/admin/users")
    async def admin_create_user(body: AdminUserCreateRequest, authorization: str | None = Header(default=None)):
        admin = require_admin(authorization)
        try:
            user, password_or_token = auth_service.create_user(
                email=body.email,
                password=body.password,
                name=body.name,
                quota=body.quota,
                quota_expires_at=body.quota_expires_at,
                status=body.status,
                role="user",
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        audit_service.add(
            actor=admin,
            action="users.create",
            resource="user",
            target_id=str(user.get("id") or ""),
            detail={
                "email": user.get("email"),
                "quota": user.get("quota"),
                "quota_expires_at": user.get("quota_expires_at"),
                "status": user.get("status"),
            },
        )
        return {"item": with_task_access(user), "password": body.password, "session_token": password_or_token, "items": list_users_with_task_access()}

    @router.post("/api/admin/users/{user_id}")
    async def admin_update_user(user_id: str, body: AdminUserUpdateRequest, authorization: str | None = Header(default=None)):
        admin = require_admin(authorization)
        updates = body.model_dump(exclude_unset=True, exclude_none=True)
        before = auth_service.get_user(user_id)
        try:
            user = auth_service.update_user(user_id, updates)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        if user is None:
            raise HTTPException(status_code=404, detail={"error": "user not found"})
        if updates:
            audit_service.add(
                actor=admin,
                action="users.update",
                resource="user",
                target_id=user_id,
                detail={
                    "updates": updates,
                    "previous_quota": (before or {}).get("quota"),
                    "current_quota": user.get("quota"),
                },
            )
        return {"item": with_task_access(user), "items": list_users_with_task_access()}

    @router.delete("/api/admin/users/{user_id}")
    async def admin_delete_user(user_id: str, authorization: str | None = Header(default=None)):
        admin = require_admin(authorization)
        if not auth_service.delete_user(user_id):
            raise HTTPException(status_code=404, detail={"error": "user not found"})
        audit_service.add(actor=admin, action="users.delete", resource="user", target_id=user_id)
        return {"items": list_users_with_task_access()}

    @router.delete("/api/admin/users")
    async def admin_delete_users(body: IdsDeleteRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        if not body.ids:
            raise HTTPException(status_code=400, detail={"error": "ids are required"})
        removed = auth_service.delete_users(body.ids)
        if removed <= 0:
            raise HTTPException(status_code=404, detail={"error": "users not found"})
        return {"items": list_users_with_task_access(), "removed": removed}

    @router.post("/api/admin/users/{user_id}/quota")
    async def admin_update_user_quota(user_id: str, body: AdminUserQuotaRequest, authorization: str | None = Header(default=None)):
        admin = require_admin(authorization)
        before = auth_service.get_user(user_id)
        updates = body.model_dump(exclude_unset=True, mode="python")
        if "quota_expires_at" in updates:
            user = auth_service.adjust_user_quota(user_id, body.amount, body.mode, updates.get("quota_expires_at"))
        else:
            user = auth_service.adjust_user_quota(user_id, body.amount, body.mode)
        if user is None:
            raise HTTPException(status_code=404, detail={"error": "user not found"})
        audit_service.add(
            actor=admin,
            action="users.quota.adjust",
            resource="user",
            target_id=user_id,
            detail={
                "mode": body.mode,
                "amount": body.amount,
                "previous_quota": (before or {}).get("quota"),
                "current_quota": user.get("quota"),
                "previous_quota_expires_at": (before or {}).get("quota_expires_at"),
                "current_quota_expires_at": user.get("quota_expires_at"),
            },
        )
        return {"item": with_task_access(user), "items": list_users_with_task_access()}

    @router.post("/api/admin/users/{user_id}/subscription")
    async def admin_update_user_subscription(
            user_id: str,
            body: AdminUserSubscriptionRequest,
            authorization: str | None = Header(default=None),
    ):
        admin = require_admin(authorization)
        plan_id = body.plan_id.strip()
        plan = next((item for item in config.subscription_plans if str(item.get("id") or "") == plan_id), None)
        if plan_id and plan is None:
            raise HTTPException(status_code=400, detail={"error": "subscription plan not found"})
        before = with_task_access(auth_service.get_user(user_id))
        try:
            user = auth_service.set_user_subscription(
                user_id,
                plan_id=plan_id,
                plan_name=str((plan or {}).get("name") or ""),
                concurrency=int((plan or {}).get("concurrency") or 1),
                valid_months=int((plan or {}).get("valid_months") or 1),
                expires_at=body.expires_at,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        if user is None:
            raise HTTPException(status_code=404, detail={"error": "user not found"})
        enriched = with_task_access(user)
        audit_service.add(
            actor=admin,
            action="users.subscription.update",
            resource="user",
            target_id=user_id,
            detail={
                "previous_subscription": (before or {}).get("subscription"),
                "current_subscription": (enriched or {}).get("subscription"),
            },
        )
        return {"item": enriched, "items": list_users_with_task_access()}

    @router.post("/api/admin/users/{user_id}/reset-password")
    async def admin_reset_password(user_id: str, body: ResetPasswordRequest, authorization: str | None = Header(default=None)):
        admin = require_admin(authorization)
        try:
            result = auth_service.reset_password(user_id, body.password)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        if result is None:
            raise HTTPException(status_code=404, detail={"error": "user not found"})
        user, password = result
        audit_service.add(
            actor=admin,
            action="users.password.reset",
            resource="user",
            target_id=user_id,
            detail={
                "email": user.get("email"),
                "generated": not bool(body.password.strip()),
            },
        )
        return {"item": with_task_access(user), "password": password}

    @router.get("/api/admin/redeem-codes")
    async def admin_list_redeem_codes(query: str = "", status: str = "", authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"items": auth_service.list_redeem_codes(query=query, status=status)}

    @router.post("/api/admin/redeem-codes")
    async def admin_create_redeem_code(body: RedeemCodeCreateRequest, authorization: str | None = Header(default=None)):
        admin = require_admin(authorization)
        items = auth_service.create_redeem_codes(
            quota=body.quota,
            count=1,
            max_uses=body.max_uses,
            valid_months=body.valid_months,
            expires_at=body.expires_at,
            created_by=str(admin.get("id") or ""),
            note=body.note,
        )
        return {"items": auth_service.list_redeem_codes(), "created": items}

    @router.post("/api/admin/redeem-codes/batch")
    async def admin_create_redeem_code_batch(body: RedeemCodeCreateRequest, authorization: str | None = Header(default=None)):
        admin = require_admin(authorization)
        created = auth_service.create_redeem_codes(
            quota=body.quota,
            count=body.count,
            max_uses=body.max_uses,
            valid_months=body.valid_months,
            expires_at=body.expires_at,
            created_by=str(admin.get("id") or ""),
            note=body.note,
        )
        return {"items": auth_service.list_redeem_codes(), "created": created}

    @router.post("/api/admin/redeem-codes/{code_id}")
    async def admin_update_redeem_code(code_id: str, body: RedeemCodeUpdateRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        item = auth_service.update_redeem_code(code_id, body.model_dump(exclude_none=True))
        if item is None:
            raise HTTPException(status_code=404, detail={"error": "redeem code not found"})
        return {"item": item, "items": auth_service.list_redeem_codes()}

    @router.delete("/api/admin/redeem-codes")
    async def admin_delete_redeem_codes(body: IdsDeleteRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        if not body.ids:
            raise HTTPException(status_code=400, detail={"error": "ids are required"})
        removed = auth_service.delete_redeem_codes(body.ids)
        if removed <= 0:
            raise HTTPException(status_code=404, detail={"error": "redeem codes not found"})
        return {"items": auth_service.list_redeem_codes(), "removed": removed}

    @router.get("/api/admin/channels")
    async def admin_list_channels(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"items": channel_service.list_channels()}

    @router.get("/api/admin/models")
    async def admin_list_models(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return model_service.list_catalog()

    @router.post("/api/admin/models/pricing")
    async def admin_update_model_pricing(body: ModelPricingRequest, authorization: str | None = Header(default=None)):
        admin = require_admin(authorization)
        try:
            item = model_service.update_pricing(
                body.model,
                body.model_dump(exclude={"model"}, exclude_none=True, mode="python"),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        audit_service.add(
            actor=admin,
            action="models.pricing.update",
            resource="model",
            target_id=str(item.get("model") or ""),
            detail={"pricing": item},
        )
        return {"item": item, **model_service.list_catalog()}

    @router.post("/api/admin/channels")
    async def admin_create_channel(body: ChannelRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            item = channel_service.create_channel(body.model_dump(mode="python"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {"item": item, "items": channel_service.list_channels()}

    @router.post("/api/admin/channels/{channel_id}")
    async def admin_update_channel(channel_id: str, body: ChannelUpdateRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            item = channel_service.update_channel(channel_id, body.model_dump(exclude_none=True, mode="python"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        if item is None:
            raise HTTPException(status_code=404, detail={"error": "channel not found"})
        return {"item": item, "items": channel_service.list_channels()}

    @router.post("/api/admin/channels/{channel_id}/models/refresh")
    async def admin_refresh_channel_models(channel_id: str, authorization: str | None = Header(default=None)):
        admin = require_admin(authorization)
        try:
            result = await run_in_threadpool(model_service.refresh_channel_models, channel_id)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        if result is None:
            raise HTTPException(status_code=404, detail={"error": "channel not found"})
        audit_service.add(
            actor=admin,
            action="channels.models.refresh",
            resource="channel",
            target_id=channel_id,
            detail={"models": result.get("models"), "channel": result.get("channel")},
        )
        return {**result, **model_service.list_catalog()}

    @router.post("/api/admin/channels/{channel_id}/models/test")
    async def admin_test_channel_models(
            channel_id: str,
            body: ChannelModelTestRequest | None = None,
            authorization: str | None = Header(default=None),
    ):
        admin = require_admin(authorization)
        selected_models = [] if body is None else body.models
        result = await run_in_threadpool(channel_service.test_channel_models, channel_id, selected_models)
        if result is None:
            raise HTTPException(status_code=404, detail={"error": "channel not found"})
        audit_service.add(
            actor=admin,
            action="channels.models.test",
            resource="channel",
            target_id=channel_id,
            detail={
                "ok": result.get("ok"),
                "model_count": result.get("model_count"),
                "tested_models": result.get("tested_models"),
                "missing_models": result.get("missing_models"),
                "latency_ms": result.get("latency_ms"),
                "error": result.get("error"),
            },
        )
        return result

    @router.delete("/api/admin/channels/{channel_id}")
    async def admin_delete_channel(channel_id: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        if not channel_service.delete_channel(channel_id):
            raise HTTPException(status_code=404, detail={"error": "channel not found"})
        return {"items": channel_service.list_channels()}

    return router
