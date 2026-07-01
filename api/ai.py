from __future__ import annotations

import json
import time

from fastapi import APIRouter, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from api.support import require_identity, resolve_image_base_url
from services.auth_service import auth_service
from services.channel_service import channel_service
from services.config import config
from services.image_service import record_image_result
from services.log_service import LOG_TYPE_CALL, log_service
from services.observability import request_id_from_request


class ImageGenerationRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    model: str | None = None
    n: int = Field(default=1, ge=1, le=4)
    size: str | None = None
    resolution: str | None = None
    quality: str | None = None
    output_format: str | None = None
    output_compression: int | None = Field(default=None, ge=0, le=100)
    moderation: str | None = None
    background: str | None = None
    response_format: str = "b64_json"
    history_disabled: bool = True
    stream: bool | None = None


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str | None = None
    prompt: str | None = None
    n: int | None = None
    stream: bool | None = None
    modalities: list[str] | None = None
    messages: list[dict[str, object]] | None = None


class ResponseCreateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str | None = None
    input: object | None = None
    tools: list[dict[str, object]] | None = None
    tool_choice: object | None = None
    stream: bool | None = None


class AnthropicMessageRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str | None = None
    messages: list[dict[str, object]] | None = None
    system: object | None = None
    stream: bool | None = None


class ChatMessageRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str | None = None
    messages: list[dict[str, object]] = Field(default_factory=list)
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    max_completion_tokens: int | None = None
    presence_penalty: float | None = None
    frequency_penalty: float | None = None
    response_format: object | None = None
    stop: object | None = None
    tools: list[dict[str, object]] | None = None
    tool_choice: object | None = None
    stream: bool | None = None


def create_router() -> APIRouter:
    router = APIRouter()

    def successful_image_count(result: object) -> int:
        if not isinstance(result, dict) or not isinstance(result.get("data"), list):
            return 0
        return sum(
            1
            for item in result.get("data") or []
            if isinstance(item, dict) and (item.get("b64_json") or item.get("url"))
        )

    def reserve_image_quota(identity: dict[str, object], amount: int, request_id: str) -> str | None:
        if identity.get("role") != "user":
            return None
        try:
            auth_service.reserve_quota(str(identity.get("id") or ""), amount, request_id)
        except ValueError as exc:
            raise HTTPException(status_code=429, detail={"error": str(exc)}) from exc
        return request_id

    def finalize_quota(request_id: str | None, count: int) -> None:
        if not request_id:
            return
        if count > 0:
            auth_service.confirm_quota(request_id, count)
        else:
            auth_service.release_quota(request_id)

    def finalize_image_result(
            identity: dict[str, object],
            result: dict[str, object],
            *,
            prompt: str,
            mode: str,
            model: str,
            size: str | None,
            channel: str,
            request_id: str,
    ) -> int:
        count = successful_image_count(result)
        if count <= 0:
            return 0
        record_image_result(
            identity,
            result,
            prompt=prompt,
            mode=mode,
            model=model,
            size=size,
            channel=channel,
            quota_cost=image_quota_cost(identity, channel),
            request_id=request_id,
        )
        return count

    def require_channel_success(payload: dict[str, object]) -> None:
        channel_error = str(payload.get("_channel_error") or "").strip()
        if channel_error:
            raise HTTPException(status_code=502, detail={"error": channel_error})
        raise HTTPException(status_code=503, detail={"error": "no enabled image channel supports this request"})

    def log_channel_failure(
            *,
            identity: dict[str, object],
            endpoint: str,
            model: str,
            payload: dict[str, object],
            request_id: str,
    ) -> None:
        channel_error = str(payload.get("_channel_error") or "").strip()
        if not channel_error:
            return
        log_service.add(
            LOG_TYPE_CALL,
            "image channel call failed",
            endpoint=endpoint,
            model=model,
            status="error",
            error=channel_error,
            request_id=request_id,
            user_id=str(identity.get("id") or ""),
            user_name=str(identity.get("name") or ""),
            user_email=str(identity.get("email") or ""),
        )

    def image_quota_cost(identity: dict[str, object], channel: str) -> int:
        if identity.get("role") != "user":
            return 0
        return 1

    def chat_quota_cost(identity: dict[str, object], channel: str) -> int:
        if identity.get("role") != "user":
            return 0
        return 1

    def build_chat_response(
            result: dict[str, object],
            model: str | None,
            channel_name: str,
            request_id: str,
    ) -> dict[str, object]:
        choices = result.get("choices")
        if not isinstance(choices, list) or not choices:
            raise HTTPException(status_code=502, detail={"error": "chat channel response missing choices"})
        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise HTTPException(status_code=502, detail={"error": "chat channel response is invalid"})
        message = first_choice.get("message")
        if not isinstance(message, dict):
            raise HTTPException(status_code=502, detail={"error": "chat channel response missing message"})
        usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
        response_model = str(model or result.get("model") or "").strip()
        created_value = result.get("created")
        try:
            created = int(created_value or 0)
        except (TypeError, ValueError):
            created = int(time.time())
        return {
            "id": str(result.get("id") or f"chatcmpl-{request_id}"),
            "object": str(result.get("object") or "chat.completion"),
            "created": created,
            "model": response_model,
            "channel": channel_name,
            "choices": [
                {
                    "index": int(first_choice.get("index") or 0),
                    "message": message,
                    "finish_reason": first_choice.get("finish_reason") or "stop",
                }
            ],
            "usage": usage,
        }

    def sse_event(event: str, data: dict[str, object]) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    @router.get("/v1/models")
    async def list_models(authorization: str | None = Header(default=None)):
        require_identity(authorization)
        items: list[dict[str, object]] = []
        seen: set[str] = set()
        for channel in channel_service.list_channels():
            if not channel.get("enabled"):
                continue
            for model in channel.get("models") or []:
                model_id = str(model or "").strip()
                if not model_id or model_id in seen:
                    continue
                seen.add(model_id)
                items.append(
                    {
                        "id": model_id,
                        "object": "model",
                        "created": 0,
                        "owned_by": str(channel.get("name") or "channel"),
                    }
                )
        return {"object": "list", "data": items}

    @router.post("/v1/images/generations")
    async def generate_images(
            body: ImageGenerationRequest,
            request: Request,
            authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization)
        if body.stream:
            raise HTTPException(status_code=400, detail={"error": "stream is not supported for channel image tasks"})
        request_id = request_id_from_request(request)
        payload = body.model_dump(mode="python")
        payload["model"] = body.model or config.default_image_model
        payload["base_url"] = resolve_image_base_url(request)
        payload["request_id"] = request_id
        quota_request_id = reserve_image_quota(identity, int(body.n or 1), request_id)
        try:
            if not body.stream:
                routed = await run_in_threadpool(channel_service.call_generation, payload)
                if routed is not None:
                    result, channel_name = routed
                    log_service.add(
                        LOG_TYPE_CALL,
                        "文生图 渠道调用完成",
                        endpoint="/v1/images/generations",
                        model=str(payload.get("model") or ""),
                        channel=channel_name,
                        status="success",
                        request_id=request_id,
                    )
                    count = finalize_image_result(
                        identity,
                        result,
                        prompt=body.prompt,
                        mode="generate",
                        model=str(payload.get("model") or ""),
                        size=body.size,
                        channel=channel_name,
                        request_id=request_id,
                    )
                    finalize_quota(quota_request_id, count)
                    return result
            log_channel_failure(
                identity=identity,
                endpoint="/v1/images/generations",
                model=str(payload.get("model") or ""),
                payload=payload,
                request_id=request_id,
            )
            require_channel_success(payload)
        except Exception:
            if quota_request_id:
                auth_service.release_quota(quota_request_id)
            raise

    @router.post("/v1/images/edits")
    async def edit_images(
            request: Request,
            authorization: str | None = Header(default=None),
            image: list[UploadFile] | None = File(default=None),
            image_list: list[UploadFile] | None = File(default=None, alias="image[]"),
            prompt: str = Form(...),
            model: str | None = Form(default=None),
            n: int = Form(default=1),
            size: str | None = Form(default=None),
            resolution: str | None = Form(default=None),
            quality: str | None = Form(default=None),
            output_format: str | None = Form(default=None),
            output_compression: int | None = Form(default=None),
            moderation: str | None = Form(default=None),
            background: str | None = Form(default=None),
            response_format: str = Form(default="b64_json"),
            stream: bool | None = Form(default=None),
    ):
        identity = require_identity(authorization)
        if stream:
            raise HTTPException(status_code=400, detail={"error": "stream is not supported for channel image tasks"})
        if n < 1 or n > 4:
            raise HTTPException(status_code=400, detail={"error": "n must be between 1 and 4"})
        uploads = [*(image or []), *(image_list or [])]
        if not uploads:
            raise HTTPException(status_code=400, detail={"error": "image file is required"})
        images: list[tuple[bytes, str, str]] = []
        for upload in uploads:
            image_data = await upload.read()
            if not image_data:
                raise HTTPException(status_code=400, detail={"error": "image file is empty"})
            images.append((image_data, upload.filename or "image.png", upload.content_type or "image/png"))
        request_id = request_id_from_request(request)
        payload = {
            "prompt": prompt,
            "images": images,
            "model": model or config.default_image_model,
            "n": n,
            "size": size,
            "resolution": resolution,
            "quality": quality,
            "output_format": output_format,
            "output_compression": output_compression,
            "moderation": moderation,
            "background": background,
            "response_format": response_format,
            "stream": stream,
            "base_url": resolve_image_base_url(request),
            "request_id": request_id,
        }
        quota_request_id = reserve_image_quota(identity, int(n or 1), request_id)
        try:
            if not stream:
                routed = await run_in_threadpool(channel_service.call_edit, payload)
                if routed is not None:
                    result, channel_name = routed
                    log_service.add(
                        LOG_TYPE_CALL,
                        "图生图 渠道调用完成",
                        endpoint="/v1/images/edits",
                        model=str(payload.get("model") or ""),
                        channel=channel_name,
                        status="success",
                        request_id=request_id,
                    )
                    count = finalize_image_result(
                        identity,
                        result,
                        prompt=prompt,
                        mode="edit",
                        model=str(payload.get("model") or ""),
                        size=size,
                        channel=channel_name,
                        request_id=request_id,
                    )
                    finalize_quota(quota_request_id, count)
                    return result
            log_channel_failure(
                identity=identity,
                endpoint="/v1/images/edits",
                model=str(payload.get("model") or ""),
                payload=payload,
                request_id=request_id,
            )
            require_channel_success(payload)
        except Exception:
            if quota_request_id:
                auth_service.release_quota(quota_request_id)
            raise

    @router.post("/v1/chat/completions")
    async def create_chat_completion(
            body: ChatCompletionRequest,
            request: Request,
            authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization)
        if identity.get("role") == "user":
            raise HTTPException(status_code=403, detail={"error": "personal users can only use image features"})
        raise HTTPException(status_code=410, detail={"error": "text compatibility endpoints are disabled; use image channels"})

    @router.post("/v1/responses")
    async def create_response(
            body: ResponseCreateRequest,
            request: Request,
            authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization)
        if identity.get("role") == "user":
            raise HTTPException(status_code=403, detail={"error": "personal users can only use image features"})
        raise HTTPException(status_code=410, detail={"error": "text compatibility endpoints are disabled; use image channels"})

    @router.post("/v1/messages")
    async def create_message(
            body: AnthropicMessageRequest,
            request: Request,
            authorization: str | None = Header(default=None),
            x_api_key: str | None = Header(default=None, alias="x-api-key"),
            anthropic_version: str | None = Header(default=None, alias="anthropic-version"),
    ):
        identity = require_identity(authorization or (f"Bearer {x_api_key}" if x_api_key else None))
        if identity.get("role") == "user":
            raise HTTPException(status_code=403, detail={"error": "personal users can only use image features"})
        raise HTTPException(status_code=410, detail={"error": "text compatibility endpoints are disabled; use image channels"})

    @router.post("/api/chat/completions")
    async def create_app_chat_completion(
            body: ChatMessageRequest,
            request: Request,
            authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization)
        messages = [message for message in body.messages if isinstance(message, dict)]
        if not messages:
            raise HTTPException(status_code=400, detail={"error": "messages are required"})
        request_id = request_id_from_request(request)
        stream = bool(body.stream)
        payload = {
            "model": body.model or config.default_text_model,
            "messages": messages,
            "temperature": body.temperature,
            "top_p": body.top_p,
            "max_tokens": body.max_tokens,
            "max_completion_tokens": body.max_completion_tokens,
            "presence_penalty": body.presence_penalty,
            "frequency_penalty": body.frequency_penalty,
            "response_format": body.response_format,
            "stop": body.stop,
            "tools": body.tools,
            "tool_choice": body.tool_choice,
            "stream": stream,
            "base_url": resolve_image_base_url(request),
            "request_id": request_id,
        }
        quota_request_id = None
        if identity.get("role") == "user":
            try:
                auth_service.reserve_quota(str(identity.get("id") or ""), chat_quota_cost(identity, "chat"), request_id)
                quota_request_id = request_id
            except ValueError as exc:
                raise HTTPException(status_code=429, detail={"error": str(exc)}) from exc
        if stream:
            async def stream_events():
                completed = False
                try:
                    routed = await run_in_threadpool(channel_service.call_chat_completion_stream, payload)
                    if routed is None:
                        channel_error = str(payload.get("_channel_error") or "").strip()
                        yield sse_event(
                            "error",
                            {
                                "error": channel_error or "no enabled text channel supports this request",
                                "request_id": request_id,
                            },
                        )
                        return
                    chunks, channel_name = routed
                    yield sse_event(
                        "meta",
                        {
                            "model": str(payload.get("model") or ""),
                            "channel": channel_name,
                            "request_id": request_id,
                        },
                    )
                    for chunk in chunks:
                        if await request.is_disconnected():
                            break
                        text = str(chunk or "")
                        if text:
                            yield sse_event("delta", {"content": text, "request_id": request_id})
                    else:
                        completed = True
                    if completed:
                        log_service.add(
                            LOG_TYPE_CALL,
                            "text chat channel stream completed",
                            endpoint="/api/chat/completions",
                            model=str(payload.get("model") or ""),
                            channel=channel_name,
                            status="success",
                            request_id=request_id,
                        )
                        if quota_request_id:
                            auth_service.confirm_quota(quota_request_id, 1)
                        yield sse_event(
                            "done",
                            {
                                "model": str(payload.get("model") or ""),
                                "channel": channel_name,
                                "request_id": request_id,
                            },
                        )
                    elif quota_request_id:
                        auth_service.release_quota(quota_request_id)
                except Exception as exc:
                    if quota_request_id:
                        auth_service.release_quota(quota_request_id)
                    message = str(exc).strip() or exc.__class__.__name__
                    yield sse_event("error", {"error": message, "request_id": request_id})

            return StreamingResponse(
                stream_events(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        try:
            routed = await run_in_threadpool(channel_service.call_chat_completion, payload)
            if routed is None:
                channel_error = str(payload.get("_channel_error") or "").strip()
                if channel_error:
                    raise HTTPException(status_code=502, detail={"error": channel_error})
                raise HTTPException(status_code=503, detail={"error": "no enabled text channel supports this request"})
            result, channel_name = routed
            count = 1 if isinstance(result, dict) and result.get("choices") else 0
            response_payload = build_chat_response(result, str(payload.get("model") or body.model or ""), channel_name, request_id)
            log_service.add(
                LOG_TYPE_CALL,
                "text chat channel call completed",
                endpoint="/api/chat/completions",
                model=str(payload.get("model") or ""),
                channel=channel_name,
                status="success",
                request_id=request_id,
            )
            if quota_request_id:
                if count > 0:
                    auth_service.confirm_quota(quota_request_id, count)
                else:
                    auth_service.release_quota(quota_request_id)
            return response_payload
        except Exception:
            if quota_request_id:
                auth_service.release_quota(quota_request_id)
            raise

    return router
