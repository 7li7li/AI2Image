from __future__ import annotations

from calendar import monthrange
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN
import hashlib
import hmac
import json
import secrets
from pathlib import Path
from threading import RLock
from typing import Mapping
from urllib.parse import urlencode

from services.auth_service import AuthService, auth_service
from services.config import DATA_DIR, ConfigStore, config

ORDER_PAYMENT_TIMEOUT_MINUTES = 30


class PaymentError(ValueError):
    """Base payment service error."""


class PaymentConfigurationError(PaymentError):
    """Raised when the payment gateway is not ready."""


class PaymentSignatureError(PaymentError):
    """Raised when an Epay callback signature is invalid."""


class PaymentStatusError(PaymentError):
    """Raised when a payment callback does not represent a successful payment."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _add_months(value: datetime, months: int) -> datetime:
    month_index = value.month - 1 + max(0, int(months or 0))
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def _clean(value: object) -> str:
    return str(value or "").strip()


def _parse_time(value: object) -> datetime | None:
    text = _clean(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_money(value: object) -> str:
    text = _clean(value)
    if not text:
        raise PaymentError("plan price is required")
    try:
        amount = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise PaymentError("plan price must be a number") from exc
    if amount <= 0:
        raise PaymentError("plan price must be greater than 0")
    cents = amount.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    if cents != amount:
        raise PaymentError("plan price can have at most 2 decimal places")
    return f"{cents:.2f}"


def _money_equals(left: object, right: object) -> bool:
    try:
        return _normalize_money(left) == _normalize_money(right)
    except PaymentError:
        return False


def epay_sign(params: Mapping[str, object], key: str) -> str:
    pairs: list[str] = []
    for name in sorted(str(item) for item in params.keys()):
        if name in {"sign", "sign_type"}:
            continue
        value = params.get(name)
        text = _clean(value)
        if not text:
            continue
        pairs.append(f"{name}={text}")
    raw = "&".join(pairs) + key
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


class PaymentService:
    def __init__(
        self,
        *,
        config_store: ConfigStore = config,
        auth: AuthService = auth_service,
        data_dir: Path = DATA_DIR,
    ):
        self.config = config_store
        self.auth = auth
        self.path = Path(data_dir) / "payment_orders.json"
        self._lock = RLock()

    def _load_orders_unlocked(self) -> list[dict[str, object]]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if not isinstance(data, list):
            return []
        return [dict(item) for item in data if isinstance(item, dict)]

    def _save_orders_unlocked(self, orders: list[dict[str, object]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(orders, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _order_expires_at(self, order: Mapping[str, object]) -> datetime:
        expires_at = _parse_time(order.get("expires_at"))
        if expires_at is not None:
            return expires_at
        created_at = _parse_time(order.get("created_at")) or _now()
        return created_at + timedelta(minutes=ORDER_PAYMENT_TIMEOUT_MINUTES)

    def _ensure_order_expires_at_unlocked(self, order: dict[str, object]) -> bool:
        if _clean(order.get("status")).lower() != "pending":
            return False
        if _clean(order.get("expires_at")):
            return False
        order["expires_at"] = self._order_expires_at(order).isoformat()
        return True

    def _cancel_order_unlocked(
        self,
        order: dict[str, object],
        *,
        reason: str,
        actor: Mapping[str, object] | None = None,
        now: datetime | None = None,
    ) -> tuple[dict[str, object], bool]:
        status = _clean(order.get("status")).lower()
        if status == "paid":
            raise PaymentError("paid payment order cannot be canceled")
        if status == "canceled":
            return order, False
        if status and status != "pending":
            raise PaymentError("payment order cannot be canceled")
        current_time = now or _now()
        order.update(
            {
                "status": "canceled",
                "canceled_at": current_time.isoformat(),
                "cancel_reason": reason,
                "updated_at": current_time.isoformat(),
            }
        )
        if actor is not None:
            order["canceled_by"] = {
                "id": actor.get("id"),
                "name": actor.get("name"),
                "email": actor.get("email"),
                "role": actor.get("role"),
            }
        return order, True

    def _expire_pending_orders_unlocked(self, orders: list[dict[str, object]], *, now: datetime | None = None) -> bool:
        current_time = now or _now()
        changed = False
        for order in orders:
            if not isinstance(order, dict):
                continue
            if self._ensure_order_expires_at_unlocked(order):
                changed = True
            if _clean(order.get("status")).lower() != "pending":
                continue
            if self._order_expires_at(order) <= current_time:
                self._cancel_order_unlocked(order, reason="timeout", now=current_time)
                changed = True
        return changed

    def _require_epay_configured(self) -> None:
        if not self.config.epay_enabled:
            raise PaymentConfigurationError("epay payment is disabled")
        if not self.config.epay_pid or not self.config.epay_key:
            raise PaymentConfigurationError("epay merchant id or key is not configured")
        if not self.config.epay_url:
            raise PaymentConfigurationError("epay gateway url is not configured")

    def _find_plan(self, plan_id: str) -> dict[str, object]:
        normalized_id = _clean(plan_id)
        for plan in self.config.subscription_plans:
            if _clean(plan.get("id")) == normalized_id:
                return dict(plan)
        raise PaymentError("subscription plan not found")

    def _submit_url(self) -> str:
        gateway_url = self.config.epay_url.rstrip("/")
        if gateway_url.lower().endswith("/submit.php"):
            return gateway_url
        return f"{gateway_url}/submit.php"

    def _build_pay_url(self, order: Mapping[str, object], *, api_base_url: str) -> str:
        api_base = api_base_url.rstrip("/")
        out_trade_no = _clean(order.get("out_trade_no"))
        if not out_trade_no:
            raise PaymentError("out_trade_no is required")
        params: dict[str, object] = {
            "pid": self.config.epay_pid,
            "out_trade_no": out_trade_no,
            "notify_url": f"{api_base}/api/payments/epay/notify",
            "return_url": f"{api_base}/api/payments/epay/return",
            "name": str(order.get("plan_name") or out_trade_no)[:80],
            "money": _normalize_money(order.get("money") or order.get("price")),
            "param": out_trade_no,
        }
        if self.config.epay_type:
            params["type"] = self.config.epay_type
        params["sign"] = epay_sign(params, self.config.epay_key)
        params["sign_type"] = "MD5"
        return f"{self._submit_url()}?{urlencode(params)}"

    def _public_order(self, order: Mapping[str, object]) -> dict[str, object]:
        return {
            "id": order.get("id"),
            "out_trade_no": order.get("out_trade_no"),
            "plan_id": order.get("plan_id"),
            "plan_name": order.get("plan_name"),
            "quota": order.get("quota"),
            "valid_months": order.get("valid_months"),
            "concurrency": order.get("concurrency") or 1,
            "price": order.get("price"),
            "money": order.get("money"),
            "status": order.get("status"),
            "created_at": order.get("created_at"),
            "expires_at": order.get("expires_at"),
            "paid_at": order.get("paid_at"),
            "canceled_at": order.get("canceled_at"),
            "cancel_reason": order.get("cancel_reason"),
            "quota_expires_at": order.get("quota_expires_at"),
            "epay_trade_no": order.get("epay_trade_no"),
        }

    def _admin_order(self, order: Mapping[str, object]) -> dict[str, object]:
        return {
            **self._public_order(order),
            "user_id": order.get("user_id"),
            "user_email": order.get("user_email"),
            "payment_type": order.get("payment_type"),
            "paid_source": order.get("paid_source"),
            "paid_by": order.get("paid_by"),
            "canceled_by": order.get("canceled_by"),
            "updated_at": order.get("updated_at"),
        }

    def _mark_order_paid_unlocked(
        self,
        order: dict[str, object],
        *,
        epay_trade_no: str = "",
        raw_notify: Mapping[str, object] | None = None,
        paid_source: str = "epay",
        paid_by: Mapping[str, object] | None = None,
    ) -> tuple[dict[str, object], bool]:
        status = _clean(order.get("status")).lower()
        if status == "paid" and order.get("quota_granted_at"):
            return order, False
        if status == "canceled":
            raise PaymentError("canceled payment order cannot be marked as paid")

        now = _now()
        user = self.auth.grant_subscription(
            _clean(order.get("user_id")),
            plan_id=_clean(order.get("plan_id")),
            plan_name=_clean(order.get("plan_name")),
            order_id=_clean(order.get("out_trade_no")),
            quota=int(order.get("quota") or 0),
            valid_months=int(order.get("valid_months") or 1),
            concurrency=int(order.get("concurrency") or 1),
        )
        if user is None:
            raise PaymentError("payment user not found")

        order.update(
            {
                "status": "paid",
                "paid_at": order.get("paid_at") or now.isoformat(),
                "updated_at": now.isoformat(),
                "quota_expires_at": user.get("quota_expires_at"),
                "quota_granted_at": now.isoformat(),
                "epay_trade_no": epay_trade_no or _clean(order.get("epay_trade_no")),
                "paid_source": paid_source,
            }
        )
        if raw_notify is not None:
            order["raw_notify"] = {str(key): _clean(value) for key, value in raw_notify.items()}
        if paid_by is not None:
            order["paid_by"] = {
                "id": paid_by.get("id"),
                "name": paid_by.get("name"),
                "email": paid_by.get("email"),
                "role": paid_by.get("role"),
            }
        return order, True

    def create_subscription_order(
        self,
        *,
        user: Mapping[str, object],
        plan_id: str,
        api_base_url: str,
        return_base_url: str = "",
    ) -> tuple[dict[str, object], str]:
        self._require_epay_configured()
        if user.get("role") != "user":
            raise PaymentError("only users can buy subscription plans")
        user_id = _clean(user.get("id"))
        if not user_id:
            raise PaymentError("user is required")

        plan = self._find_plan(plan_id)
        quota = int(plan.get("quota") or 0)
        valid_months = int(plan.get("valid_months") or 0)
        concurrency = int(plan.get("concurrency") or 1)
        money = _normalize_money(plan.get("price"))
        now = _now()
        out_trade_no = f"IKUN{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{secrets.token_hex(4).upper()}"
        api_base = api_base_url.rstrip("/")
        return_base = return_base_url.rstrip("/")
        order: dict[str, object] = {
            "id": out_trade_no,
            "out_trade_no": out_trade_no,
            "user_id": user_id,
            "user_email": user.get("email"),
            "plan_id": plan.get("id"),
            "plan_name": plan.get("name"),
            "quota": quota,
            "valid_months": valid_months,
            "concurrency": concurrency,
            "price": plan.get("price"),
            "money": money,
            "status": "pending",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "expires_at": (now + timedelta(minutes=ORDER_PAYMENT_TIMEOUT_MINUTES)).isoformat(),
            "paid_at": None,
            "canceled_at": None,
            "cancel_reason": "",
            "quota_expires_at": None,
            "epay_trade_no": "",
            "payment_type": self.config.epay_type,
            "return_base_url": return_base,
        }

        with self._lock:
            orders = self._load_orders_unlocked()
            orders.insert(0, order)
            self._save_orders_unlocked(orders)

        return self._public_order(order), self._build_pay_url(order, api_base_url=api_base)

    def list_user_orders(self, user_id: str, *, limit: int = 20) -> list[dict[str, object]]:
        normalized_user_id = _clean(user_id)
        with self._lock:
            raw_orders = self._load_orders_unlocked()
            if self._expire_pending_orders_unlocked(raw_orders):
                self._save_orders_unlocked(raw_orders)
            orders = [
                self._public_order(order)
                for order in raw_orders
                if _clean(order.get("user_id")) == normalized_user_id
            ]
        return orders[: max(1, min(100, int(limit or 20)))]

    def active_subscription_concurrency(self, user_id: str, *, default: int = 1) -> int:
        return int(self.active_subscription_access(user_id, default=default)["concurrency"])

    def active_subscription_access(self, user_id: str, *, default: int = 1) -> dict[str, object]:
        normalized_user_id = _clean(user_id)
        user = self.auth.get_user(normalized_user_id)
        if user is None:
            return {"concurrency": max(1, int(default or 1)), "subscription": None}
        return self.active_subscription_accesses([user], default=default).get(
            normalized_user_id,
            {"concurrency": max(1, int(default or 1)), "subscription": None},
        )

    def active_subscription_accesses(
        self,
        users: list[Mapping[str, object]],
        *,
        default: int = 1,
    ) -> dict[str, dict[str, object]]:
        normalized_default = max(1, int(default or 1))
        access_by_user: dict[str, dict[str, object]] = {}
        overridden_user_ids: set[str] = set()
        for user in users:
            user_id = _clean(user.get("id"))
            if not user_id:
                continue
            selected = dict(user.get("subscription") or {})
            access_by_user[user_id] = {
                "concurrency": max(normalized_default, int(selected.get("concurrency") or 0)),
                "subscription": selected or None,
            }
            if self.auth.subscription_is_admin_overridden(user_id):
                overridden_user_ids.add(user_id)

        now = _now()
        with self._lock:
            orders = self._load_orders_unlocked()
            for order in orders:
                user_id = _clean(order.get("user_id"))
                if (
                    user_id not in access_by_user
                    or user_id in overridden_user_ids
                    or _clean(order.get("status")).lower() != "paid"
                    or (_parse_time(order.get("quota_expires_at")) or now) <= now
                ):
                    continue
                access = access_by_user[user_id]
                selected = dict(access.get("subscription") or {})
                raw_concurrency = order.get("concurrency")
                if raw_concurrency is None or raw_concurrency == "":
                    try:
                        raw_concurrency = self._find_plan(_clean(order.get("plan_id"))).get("concurrency")
                    except PaymentError:
                        raw_concurrency = 1
                try:
                    current_concurrency = max(1, min(50, int(raw_concurrency or 1)))
                    if current_concurrency > int(selected.get("concurrency") or 0):
                        selected = {
                            "plan_id": order.get("plan_id"),
                            "plan_name": order.get("plan_name"),
                            "concurrency": current_concurrency,
                            "expires_at": order.get("quota_expires_at"),
                        }
                    access["concurrency"] = max(int(access.get("concurrency") or normalized_default), current_concurrency)
                    access["subscription"] = selected or None
                except (TypeError, ValueError):
                    continue
        return access_by_user

    def list_orders(self, *, status: str = "", query: str = "", limit: int = 200) -> list[dict[str, object]]:
        normalized_status = _clean(status).lower()
        if normalized_status not in {"", "pending", "paid", "canceled"}:
            normalized_status = ""
        normalized_query = _clean(query).lower()
        with self._lock:
            raw_orders = self._load_orders_unlocked()
            if self._expire_pending_orders_unlocked(raw_orders):
                self._save_orders_unlocked(raw_orders)
            orders: list[dict[str, object]] = []
            for order in raw_orders:
                if normalized_status and _clean(order.get("status")).lower() != normalized_status:
                    continue
                if normalized_query:
                    values = [
                        order.get("out_trade_no"),
                        order.get("epay_trade_no"),
                        order.get("plan_name"),
                        order.get("user_id"),
                        order.get("user_email"),
                    ]
                    if not any(normalized_query in _clean(value).lower() for value in values):
                        continue
                orders.append(self._admin_order(order))
        return orders[: max(1, min(500, int(limit or 200)))]

    def get_order(self, out_trade_no: str) -> dict[str, object] | None:
        normalized_trade_no = _clean(out_trade_no)
        if not normalized_trade_no:
            return None
        with self._lock:
            orders = self._load_orders_unlocked()
            if self._expire_pending_orders_unlocked(orders):
                self._save_orders_unlocked(orders)
            for order in orders:
                if _clean(order.get("out_trade_no")) == normalized_trade_no:
                    return dict(order)
        return None

    def create_order_pay_url(
        self,
        *,
        user_id: str,
        out_trade_no: str,
        api_base_url: str,
        return_base_url: str = "",
    ) -> tuple[dict[str, object], str]:
        self._require_epay_configured()
        normalized_user_id = _clean(user_id)
        normalized_trade_no = _clean(out_trade_no)
        if not normalized_user_id:
            raise PaymentError("user is required")
        if not normalized_trade_no:
            raise PaymentError("out_trade_no is required")
        with self._lock:
            orders = self._load_orders_unlocked()
            expired = self._expire_pending_orders_unlocked(orders)
            index = next(
                (item_index for item_index, item in enumerate(orders) if _clean(item.get("out_trade_no")) == normalized_trade_no),
                -1,
            )
            if index < 0:
                raise PaymentError("payment order not found")
            order = dict(orders[index])
            if _clean(order.get("user_id")) != normalized_user_id:
                raise PaymentError("payment order not found")
            if _clean(order.get("status")).lower() != "pending":
                if expired:
                    self._save_orders_unlocked(orders)
                raise PaymentError("payment order is not pending")
            if return_base_url:
                order["return_base_url"] = return_base_url.rstrip("/")
                order["updated_at"] = _now().isoformat()
                orders[index] = order
                self._save_orders_unlocked(orders)
            elif expired:
                self._save_orders_unlocked(orders)
            return self._public_order(order), self._build_pay_url(order, api_base_url=api_base_url)

    def cancel_order(
        self,
        out_trade_no: str,
        *,
        user_id: str = "",
        actor: Mapping[str, object] | None = None,
        reason: str = "user",
        include_admin: bool = False,
    ) -> tuple[dict[str, object], bool]:
        normalized_trade_no = _clean(out_trade_no)
        normalized_user_id = _clean(user_id)
        if not normalized_trade_no:
            raise PaymentError("out_trade_no is required")
        with self._lock:
            orders = self._load_orders_unlocked()
            expired = self._expire_pending_orders_unlocked(orders)
            index = next(
                (item_index for item_index, item in enumerate(orders) if _clean(item.get("out_trade_no")) == normalized_trade_no),
                -1,
            )
            if index < 0:
                if expired:
                    self._save_orders_unlocked(orders)
                raise PaymentError("payment order not found")
            order = dict(orders[index])
            if normalized_user_id and _clean(order.get("user_id")) != normalized_user_id:
                if expired:
                    self._save_orders_unlocked(orders)
                raise PaymentError("payment order not found")
            order, canceled = self._cancel_order_unlocked(order, reason=reason, actor=actor)
            orders[index] = order
            self._save_orders_unlocked(orders)
            return (self._admin_order(order) if include_admin else self._public_order(order)), canceled

    def delete_canceled_orders(self, out_trade_nos: list[str]) -> dict[str, object]:
        normalized_trade_nos: list[str] = []
        seen: set[str] = set()
        for value in out_trade_nos:
            trade_no = _clean(value)
            if not trade_no or trade_no in seen:
                continue
            normalized_trade_nos.append(trade_no)
            seen.add(trade_no)
        if not normalized_trade_nos:
            raise PaymentError("payment order ids are required")

        with self._lock:
            orders = self._load_orders_unlocked()
            self._expire_pending_orders_unlocked(orders)
            by_trade_no = {_clean(order.get("out_trade_no")): order for order in orders if isinstance(order, dict)}
            targets = [by_trade_no.get(trade_no) for trade_no in normalized_trade_nos]
            if any(order is None for order in targets):
                raise PaymentError("payment orders not found")
            if any(_clean(order.get("status")).lower() != "canceled" for order in targets if order is not None):
                raise PaymentError("only canceled payment orders can be deleted")

            remaining = [order for order in orders if _clean(order.get("out_trade_no")) not in seen]
            removed = len(orders) - len(remaining)
            if removed <= 0:
                raise PaymentError("payment orders not found")
            self._save_orders_unlocked(remaining)
            return {
                "removed": removed,
                "removed_ids": normalized_trade_nos,
            }

    def mark_order_paid(self, out_trade_no: str, *, actor: Mapping[str, object] | None = None) -> tuple[dict[str, object], bool]:
        normalized_trade_no = _clean(out_trade_no)
        if not normalized_trade_no:
            raise PaymentError("out_trade_no is required")
        with self._lock:
            orders = self._load_orders_unlocked()
            expired = self._expire_pending_orders_unlocked(orders)
            index = next(
                (item_index for item_index, item in enumerate(orders) if _clean(item.get("out_trade_no")) == normalized_trade_no),
                -1,
            )
            if index < 0:
                if expired:
                    self._save_orders_unlocked(orders)
                raise PaymentError("payment order not found")
            order = dict(orders[index])
            if _clean(order.get("status")).lower() == "canceled":
                if expired:
                    self._save_orders_unlocked(orders)
                raise PaymentError("canceled payment order cannot be marked as paid")
            order, granted = self._mark_order_paid_unlocked(
                order,
                epay_trade_no=_clean(order.get("epay_trade_no")) or f"manual-{normalized_trade_no}",
                paid_source="admin",
                paid_by=actor,
            )
            orders[index] = order
            self._save_orders_unlocked(orders)
            return self._admin_order(order), granted

    def verify_epay_signature(self, params: Mapping[str, object]) -> None:
        self._require_epay_configured()
        provided = _clean(params.get("sign"))
        if not provided:
            raise PaymentSignatureError("epay sign is required")
        expected = epay_sign(params, self.config.epay_key)
        if not hmac.compare_digest(provided.lower(), expected.lower()):
            raise PaymentSignatureError("epay sign is invalid")

    def handle_epay_callback(self, params: Mapping[str, object]) -> tuple[dict[str, object], bool]:
        self.verify_epay_signature(params)
        if _clean(params.get("trade_status")) != "TRADE_SUCCESS":
            raise PaymentStatusError("epay trade is not successful")
        if _clean(params.get("pid")) != self.config.epay_pid:
            raise PaymentError("epay merchant id mismatch")

        out_trade_no = _clean(params.get("out_trade_no"))
        if not out_trade_no:
            raise PaymentError("out_trade_no is required")

        with self._lock:
            orders = self._load_orders_unlocked()
            expired = self._expire_pending_orders_unlocked(orders)
            index = next(
                (item_index for item_index, item in enumerate(orders) if _clean(item.get("out_trade_no")) == out_trade_no),
                -1,
            )
            if index < 0:
                if expired:
                    self._save_orders_unlocked(orders)
                raise PaymentError("payment order not found")
            order = dict(orders[index])
            if _clean(order.get("status")).lower() == "canceled":
                if expired:
                    self._save_orders_unlocked(orders)
                raise PaymentError("canceled payment order cannot be marked as paid")
            if not _money_equals(params.get("money"), order.get("money")):
                if expired:
                    self._save_orders_unlocked(orders)
                raise PaymentError("epay money mismatch")

            order, granted = self._mark_order_paid_unlocked(
                order,
                epay_trade_no=_clean(params.get("trade_no")),
                raw_notify=params,
                paid_source="epay",
            )
            orders[index] = order
            self._save_orders_unlocked(orders)
            return self._public_order(order), granted


payment_service = PaymentService()
