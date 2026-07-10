from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse, RedirectResponse
from pydantic import BaseModel

from api.support import require_admin, require_identity, resolve_image_base_url
from services.config import config
from services.payment_service import PaymentError, payment_service


class SubscriptionOrderRequest(BaseModel):
    plan_id: str


class SubscriptionOrderStatusRequest(BaseModel):
    status: str


class SubscriptionOrderDeleteRequest(BaseModel):
    ids: list[str] = []


def _first_header_value(value: object) -> str:
    return str(value or "").split(",", 1)[0].strip()


def _base_url_from_absolute_url(value: object) -> str:
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def _resolve_api_base_url(request: Request) -> str:
    if config.base_url:
        return config.base_url

    forwarded_host = _first_header_value(request.headers.get("x-forwarded-host"))
    if forwarded_host:
        forwarded_proto = _first_header_value(request.headers.get("x-forwarded-proto")) or str(request.url.scheme)
        if forwarded_proto in {"http", "https"}:
            return f"{forwarded_proto}://{forwarded_host}".rstrip("/")

    return f"{request.url.scheme}://{request.headers.get('host', request.url.netloc)}".rstrip("/")


def _subscription_return_url(request: Request, order: dict[str, object] | None, paid: bool) -> str:
    fallback_base_url = _resolve_api_base_url(request)
    return_base_url = _base_url_from_absolute_url((order or {}).get("return_base_url")) or fallback_base_url
    params = {"paid": "1" if paid else "0"}
    out_trade_no = str((order or {}).get("out_trade_no") or "").strip()
    if out_trade_no:
        params["order"] = out_trade_no
    return f"{return_base_url}/subscription?{urlencode(params)}"


async def _epay_params(request: Request) -> dict[str, str]:
    params = {str(key): str(value) for key, value in request.query_params.items()}
    body = await request.body()
    if body:
        try:
            body_text = body.decode("utf-8")
        except UnicodeDecodeError:
            body_text = body.decode("utf-8", errors="ignore")
        for key, value in parse_qsl(body_text, keep_blank_values=True):
            params[str(key)] = str(value)
    return params


def create_router() -> APIRouter:
    router = APIRouter()

    @router.post("/api/subscription/orders")
    async def create_subscription_order(body: SubscriptionOrderRequest, request: Request, authorization: str | None = Header(default=None)):
        identity = require_identity(authorization)
        if identity.get("role") != "user":
            raise HTTPException(status_code=403, detail={"error": "only users can buy subscription plans"})
        try:
            order, pay_url = await run_in_threadpool(
                payment_service.create_subscription_order,
                user=identity,
                plan_id=body.plan_id,
                api_base_url=_resolve_api_base_url(request),
                return_base_url=resolve_image_base_url(request),
            )
        except PaymentError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {"order": order, "pay_url": pay_url}

    @router.get("/api/me/subscription/orders")
    async def list_my_subscription_orders(authorization: str | None = Header(default=None)):
        identity = require_identity(authorization)
        return {
            "items": await run_in_threadpool(
                payment_service.list_user_orders,
                str(identity.get("id") or ""),
            )
        }

    @router.post("/api/me/subscription/orders/{out_trade_no}/pay")
    async def pay_my_subscription_order(out_trade_no: str, request: Request, authorization: str | None = Header(default=None)):
        identity = require_identity(authorization)
        if identity.get("role") != "user":
            raise HTTPException(status_code=403, detail={"error": "only users can pay subscription orders"})
        try:
            order, pay_url = await run_in_threadpool(
                payment_service.create_order_pay_url,
                user_id=str(identity.get("id") or ""),
                out_trade_no=out_trade_no,
                api_base_url=_resolve_api_base_url(request),
                return_base_url=resolve_image_base_url(request),
            )
        except PaymentError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {"order": order, "pay_url": pay_url}

    @router.post("/api/me/subscription/orders/{out_trade_no}/cancel")
    async def cancel_my_subscription_order(out_trade_no: str, authorization: str | None = Header(default=None)):
        identity = require_identity(authorization)
        if identity.get("role") != "user":
            raise HTTPException(status_code=403, detail={"error": "only users can cancel subscription orders"})
        try:
            item, canceled = await run_in_threadpool(
                payment_service.cancel_order,
                out_trade_no,
                user_id=str(identity.get("id") or ""),
                actor=identity,
                reason="user",
            )
        except PaymentError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {"item": item, "canceled": canceled}

    @router.get("/api/admin/subscription/orders")
    async def list_subscription_orders(
        status: str = "",
        query: str = "",
        limit: int = 200,
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        return {
            "items": await run_in_threadpool(
                payment_service.list_orders,
                status=status,
                query=query,
                limit=limit,
            )
        }

    @router.post("/api/admin/subscription/orders/{out_trade_no}/status")
    async def update_subscription_order_status(
        out_trade_no: str,
        body: SubscriptionOrderStatusRequest,
        authorization: str | None = Header(default=None),
    ):
        admin = require_admin(authorization)
        next_status = str(body.status or "").strip().lower()
        if next_status != "paid":
            raise HTTPException(status_code=400, detail={"error": "only marking orders as paid is supported"})
        try:
            item, granted = await run_in_threadpool(
                payment_service.mark_order_paid,
                out_trade_no,
                actor=admin,
            )
        except PaymentError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {"item": item, "granted": granted}

    @router.post("/api/admin/subscription/orders/{out_trade_no}/cancel")
    async def cancel_subscription_order(out_trade_no: str, authorization: str | None = Header(default=None)):
        admin = require_admin(authorization)
        try:
            item, canceled = await run_in_threadpool(
                payment_service.cancel_order,
                out_trade_no,
                actor=admin,
                reason="admin",
                include_admin=True,
            )
        except PaymentError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {"item": item, "canceled": canceled}

    @router.delete("/api/admin/subscription/orders")
    async def delete_canceled_subscription_orders(body: SubscriptionOrderDeleteRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            result = await run_in_threadpool(payment_service.delete_canceled_orders, body.ids)
        except PaymentError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return result

    @router.get("/api/payments/epay/notify")
    @router.post("/api/payments/epay/notify")
    async def epay_notify(request: Request):
        try:
            params = await _epay_params(request)
            await run_in_threadpool(payment_service.handle_epay_callback, params)
        except Exception:
            return PlainTextResponse("fail")
        return PlainTextResponse("success")

    @router.get("/api/payments/epay/return")
    @router.post("/api/payments/epay/return")
    async def epay_return(request: Request):
        order: dict[str, object] | None = None
        paid = False
        try:
            params = await _epay_params(request)
            order, _ = await run_in_threadpool(payment_service.handle_epay_callback, params)
            order = await run_in_threadpool(payment_service.get_order, params.get("out_trade_no", "")) or order
            paid = True
        except Exception:
            paid = False
        return RedirectResponse(_subscription_return_url(request, order, paid))

    return router
