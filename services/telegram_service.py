"""Telegram Bot delivery helpers for operational notifications."""

from __future__ import annotations

from queue import Full, Queue
from threading import Lock, Thread
from typing import Any
from urllib.parse import quote

from curl_cffi.requests import Session

from services.proxy_service import proxy_settings


TELEGRAM_API_BASE_URL = "https://api.telegram.org"
TELEGRAM_MESSAGE_LIMIT = 4096
TELEGRAM_REQUEST_TIMEOUT = 10
_NOTIFICATION_QUEUE_SIZE = 100

_notification_queue: Queue[dict[str, Any]] = Queue(maxsize=_NOTIFICATION_QUEUE_SIZE)
_worker_lock = Lock()
_worker_started = False


class TelegramDeliveryError(RuntimeError):
    """Raised when Telegram rejects or cannot receive a notification."""


def _config():
    # Keep this import lazy so config and log_service can be imported during startup.
    from services.config import config

    return config


def _clean(value: object) -> str:
    return str(value or "").strip()


def _telegram_request(*, token: str, chat_id: str, text: str) -> dict[str, Any]:
    encoded_token = quote(token, safe=":-_.")
    url = f"{TELEGRAM_API_BASE_URL}/bot{encoded_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text[:TELEGRAM_MESSAGE_LIMIT],
        "disable_web_page_preview": True,
    }
    session = Session(**proxy_settings.build_session_kwargs(verify=True))
    try:
        response = session.post(
            url,
            json=payload,
            headers={"Accept": "application/json"},
            timeout=TELEGRAM_REQUEST_TIMEOUT,
        )
    except Exception as exc:
        raise TelegramDeliveryError(f"telegram request failed: {exc}") from exc
    finally:
        session.close()

    if not response.ok:
        raise TelegramDeliveryError(f"telegram request failed HTTP {response.status_code}: {response.text[:300]}")

    try:
        result = response.json()
    except (TypeError, ValueError) as exc:
        raise TelegramDeliveryError("telegram response is invalid") from exc
    if not isinstance(result, dict) or not result.get("ok"):
        description = _clean(result.get("description")) if isinstance(result, dict) else ""
        raise TelegramDeliveryError(description or "telegram rejected the message")
    return result


def send_telegram_message(text: str) -> dict[str, Any]:
    """Send a message using the currently configured Bot credentials."""

    settings = _config()
    token = _clean(settings.telegram_bot_token)
    chat_id = _clean(settings.telegram_chat_id)
    if not token:
        raise ValueError("telegram bot token is not configured")
    if not chat_id:
        raise ValueError("telegram chat id is not configured")
    message = _clean(text)
    if not message:
        raise ValueError("telegram message is empty")
    return _telegram_request(token=token, chat_id=chat_id, text=message)


def send_telegram_test_message() -> dict[str, Any]:
    settings = _config()
    title = _clean(settings.site_title) or "Image Studio"
    return send_telegram_message(f"[{title}] Telegram 错误通知测试成功。")


def format_error_log_message(item: dict[str, Any]) -> str:
    detail = item.get("detail") if isinstance(item.get("detail"), dict) else {}
    fields = [
        ("时间", item.get("time")),
        ("类型", item.get("type")),
        ("摘要", item.get("summary")),
        ("状态", detail.get("status") or item.get("status")),
        ("接口", detail.get("endpoint") or item.get("endpoint")),
        ("模型", detail.get("model") or item.get("model")),
        ("渠道", detail.get("channel") or item.get("channel")),
        ("请求 ID", item.get("request_id") or detail.get("request_id")),
        ("用户", detail.get("user_email") or detail.get("user_name") or item.get("user_email")),
        ("错误", detail.get("error") or item.get("error")),
    ]
    lines = ["[系统错误通知]"]
    for label, value in fields:
        normalized = _clean(value)
        if normalized:
            lines.append(f"{label}: {normalized}")
    return "\n".join(lines)[:TELEGRAM_MESSAGE_LIMIT]


def _notifications_configured() -> bool:
    settings = _config()
    return bool(
        settings.telegram_error_notifications_enabled
        and _clean(settings.telegram_bot_token)
        and _clean(settings.telegram_chat_id)
    )


def _notification_worker() -> None:
    while True:
        item = _notification_queue.get()
        try:
            if _notifications_configured():
                send_telegram_message(format_error_log_message(item))
        except Exception as exc:
            # Delivery failures must never create another system log/notification loop.
            print(f"[telegram] error notification failed: {exc}")
        finally:
            _notification_queue.task_done()


def _ensure_worker() -> None:
    global _worker_started
    if _worker_started:
        return
    with _worker_lock:
        if _worker_started:
            return
        Thread(target=_notification_worker, name="telegram-notification", daemon=True).start()
        _worker_started = True


def notify_error_log(item: dict[str, Any]) -> bool:
    """Queue an error log for Telegram delivery without blocking the request path."""

    if not _notifications_configured():
        return False
    try:
        _notification_queue.put_nowait(dict(item))
    except Full:
        print("[telegram] error notification queue is full; dropping notification")
        return False
    _ensure_worker()
    return True
