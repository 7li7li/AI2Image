from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import tempfile
import unittest

from services.auth_service import AuthService
from services.config import ConfigStore
from services.payment_service import PaymentError, PaymentService, PaymentSignatureError, epay_sign
from services.storage.json_storage import JSONStorageBackend


class PaymentServiceTest(unittest.TestCase):
    def _create_service(self, tmp_dir: str) -> tuple[PaymentService, AuthService, dict[str, object]]:
        root = Path(tmp_dir)
        config_path = root / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "auth-key": "test-auth",
                    "epay_enabled": True,
                    "epay_url": "https://pay.example.com",
                    "epay_pid": "1001",
                    "epay_key": "merchant-secret",
                    "epay_type": "",
                    "subscription_plans": [
                        {
                            "id": "starter",
                            "name": "基础套餐",
                            "quota": 100,
                            "valid_months": 1,
                            "concurrency": 4,
                            "price": "19.9",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        store = ConfigStore(config_path)
        auth = AuthService(JSONStorageBackend(root / "data"))
        user, _ = auth.create_user(email="user@example.com", password="secret123")
        return PaymentService(config_store=store, auth=auth, data_dir=root / "data"), auth, user

    def test_epay_sign_excludes_empty_sign_and_sign_type(self) -> None:
        expected = hashlib.md5("a=1&b=2merchant-secret".encode("utf-8")).hexdigest()

        self.assertEqual(
            epay_sign(
                {
                    "b": "2",
                    "empty": "",
                    "sign": "bad",
                    "sign_type": "MD5",
                    "a": "1",
                },
                "merchant-secret",
            ),
            expected,
        )

    def test_active_subscription_uses_highest_concurrency_and_renews_same_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            _service, auth, user = self._create_service(tmp_dir)
            user_id = str(user["id"])
            first = auth.grant_subscription(
                user_id,
                plan_id="starter",
                plan_name="Starter",
                order_id="order-1",
                quota=100,
                valid_months=1,
                concurrency=4,
            )
            first_expiry = str((first or {}).get("subscription", {}).get("expires_at"))  # type: ignore[union-attr]
            auth.grant_subscription(
                user_id,
                plan_id="basic",
                plan_name="Basic",
                order_id="order-2",
                quota=50,
                valid_months=1,
                concurrency=2,
            )
            renewed = auth.grant_subscription(
                user_id,
                plan_id="starter",
                plan_name="Starter",
                order_id="order-3",
                quota=100,
                valid_months=1,
                concurrency=4,
            )

            self.assertEqual(auth.task_concurrency(user_id, default=1), 4)
            self.assertEqual((renewed or {}).get("subscription_concurrency"), 4)
            self.assertGreater(str((renewed or {}).get("subscription", {}).get("expires_at")), first_expiry)  # type: ignore[union-attr]
            self.assertEqual((renewed or {}).get("quota"), 250)

    def test_legacy_paid_order_uses_current_plan_concurrency(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service, _auth, user = self._create_service(tmp_dir)
            order, _ = service.create_subscription_order(
                user=user,
                plan_id="starter",
                api_base_url="https://example.com",
            )
            orders = json.loads(service.path.read_text(encoding="utf-8"))
            orders[0].pop("concurrency", None)
            service.path.write_text(json.dumps(orders), encoding="utf-8")
            service.mark_order_paid(str(order["out_trade_no"]))

            self.assertEqual(
                service.active_subscription_concurrency(str(user["id"]), default=1),
                4,
            )

    def test_epay_callback_grants_quota_once(self) -> None:
        original_type = os.environ.get("YANAI_EPAY_TYPE")
        os.environ.pop("YANAI_EPAY_TYPE", None)
        with tempfile.TemporaryDirectory() as tmp_dir:
            try:
                service, auth, user = self._create_service(tmp_dir)

                order, pay_url = service.create_subscription_order(
                    user=user,
                    plan_id="starter",
                    api_base_url="https://example.com",
                    return_base_url="https://app.example.com",
                )
                parsed = urlparse(pay_url)
                pay_params = {key: values[0] for key, values in parse_qs(parsed.query).items()}

                self.assertEqual(f"{parsed.scheme}://{parsed.netloc}{parsed.path}", "https://pay.example.com/submit.php")
                self.assertEqual(pay_params["pid"], "1001")
                self.assertNotIn("type", pay_params)
                self.assertEqual(pay_params["money"], "19.90")
                self.assertEqual(pay_params["notify_url"], "https://example.com/api/payments/epay/notify")
                self.assertEqual(pay_params["return_url"], "https://example.com/api/payments/epay/return")
                self.assertEqual(pay_params["sign"], epay_sign(pay_params, "merchant-secret"))

                callback = {
                    "pid": "1001",
                    "trade_no": "EPAY202607090001",
                    "out_trade_no": str(order["out_trade_no"]),
                    "type": "alipay",
                    "name": "基础套餐",
                    "money": "19.90",
                    "trade_status": "TRADE_SUCCESS",
                    "param": str(order["out_trade_no"]),
                }
                callback["sign"] = epay_sign(callback, "merchant-secret")
                callback["sign_type"] = "MD5"

                paid_order, granted = service.handle_epay_callback(callback)
                self.assertTrue(granted)
                self.assertEqual(paid_order["status"], "paid")
                self.assertEqual(paid_order["concurrency"], 4)
                self.assertEqual(auth.get_user(str(user["id"]))["quota"], 100)  # type: ignore[index]
                self.assertEqual(auth.get_user(str(user["id"]))["subscription_concurrency"], 4)  # type: ignore[index]

                _, duplicate_granted = service.handle_epay_callback(callback)
                self.assertFalse(duplicate_granted)
                self.assertEqual(auth.get_user(str(user["id"]))["quota"], 100)  # type: ignore[index]

                invalid = dict(callback)
                invalid["sign"] = "invalid"
                with self.assertRaises(PaymentSignatureError):
                    service.handle_epay_callback(invalid)
            finally:
                if original_type is None:
                    os.environ.pop("YANAI_EPAY_TYPE", None)
                else:
                    os.environ["YANAI_EPAY_TYPE"] = original_type

    def test_lists_admin_and_user_orders(self) -> None:
        original_type = os.environ.get("YANAI_EPAY_TYPE")
        os.environ.pop("YANAI_EPAY_TYPE", None)
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                service, auth, user = self._create_service(tmp_dir)
                other_user, _ = auth.create_user(email="other@example.com", password="secret123")

                first_order, _ = service.create_subscription_order(
                    user=user,
                    plan_id="starter",
                    api_base_url="https://example.com",
                    return_base_url="https://app.example.com",
                )
                second_order, _ = service.create_subscription_order(
                    user=other_user,
                    plan_id="starter",
                    api_base_url="https://example.com",
                    return_base_url="https://app.example.com",
                )

                callback = {
                    "pid": "1001",
                    "trade_no": "EPAY202607090002",
                    "out_trade_no": str(first_order["out_trade_no"]),
                    "type": "alipay",
                    "name": "基础套餐",
                    "money": "19.90",
                    "trade_status": "TRADE_SUCCESS",
                    "param": str(first_order["out_trade_no"]),
                }
                callback["sign"] = epay_sign(callback, "merchant-secret")
                callback["sign_type"] = "MD5"
                service.handle_epay_callback(callback)

                self.assertEqual([item["out_trade_no"] for item in service.list_user_orders(str(user["id"]))], [first_order["out_trade_no"]])
                self.assertEqual([item["out_trade_no"] for item in service.list_user_orders(str(other_user["id"]))], [second_order["out_trade_no"]])

                paid_orders = service.list_orders(status="paid")
                self.assertEqual(len(paid_orders), 1)
                self.assertEqual(paid_orders[0]["out_trade_no"], first_order["out_trade_no"])
                self.assertEqual(paid_orders[0]["user_email"], "user@example.com")

                queried_orders = service.list_orders(query="other@example.com")
                self.assertEqual(len(queried_orders), 1)
                self.assertEqual(queried_orders[0]["out_trade_no"], second_order["out_trade_no"])
        finally:
            if original_type is None:
                os.environ.pop("YANAI_EPAY_TYPE", None)
            else:
                os.environ["YANAI_EPAY_TYPE"] = original_type

    def test_admin_can_mark_pending_order_paid_once(self) -> None:
        original_type = os.environ.get("YANAI_EPAY_TYPE")
        os.environ.pop("YANAI_EPAY_TYPE", None)
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                service, auth, user = self._create_service(tmp_dir)
                order, _ = service.create_subscription_order(
                    user=user,
                    plan_id="starter",
                    api_base_url="https://example.com",
                    return_base_url="https://app.example.com",
                )

                paid_order, granted = service.mark_order_paid(
                    str(order["out_trade_no"]),
                    actor={"id": "admin", "name": "Admin", "email": "admin@example.com", "role": "admin"},
                )
                self.assertTrue(granted)
                self.assertEqual(paid_order["status"], "paid")
                self.assertEqual(paid_order["paid_source"], "admin")
                self.assertEqual(paid_order["paid_by"]["email"], "admin@example.com")  # type: ignore[index]
                self.assertEqual(auth.get_user(str(user["id"]))["quota"], 100)  # type: ignore[index]

                duplicate_order, duplicate_granted = service.mark_order_paid(str(order["out_trade_no"]))
                self.assertFalse(duplicate_granted)
                self.assertEqual(duplicate_order["status"], "paid")
                self.assertEqual(auth.get_user(str(user["id"]))["quota"], 100)  # type: ignore[index]
        finally:
            if original_type is None:
                os.environ.pop("YANAI_EPAY_TYPE", None)
            else:
                os.environ["YANAI_EPAY_TYPE"] = original_type

    def test_user_can_repay_own_pending_order(self) -> None:
        original_type = os.environ.get("YANAI_EPAY_TYPE")
        os.environ.pop("YANAI_EPAY_TYPE", None)
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                service, auth, user = self._create_service(tmp_dir)
                other_user, _ = auth.create_user(email="other@example.com", password="secret123")
                order, _ = service.create_subscription_order(
                    user=user,
                    plan_id="starter",
                    api_base_url="https://example.com",
                    return_base_url="https://app.example.com",
                )

                repay_order, pay_url = service.create_order_pay_url(
                    user_id=str(user["id"]),
                    out_trade_no=str(order["out_trade_no"]),
                    api_base_url="https://api.example.com",
                    return_base_url="https://new-app.example.com",
                )
                parsed = urlparse(pay_url)
                pay_params = {key: values[0] for key, values in parse_qs(parsed.query).items()}

                self.assertEqual(repay_order["out_trade_no"], order["out_trade_no"])
                self.assertEqual(pay_params["out_trade_no"], order["out_trade_no"])
                self.assertEqual(pay_params["notify_url"], "https://api.example.com/api/payments/epay/notify")
                self.assertEqual(pay_params["return_url"], "https://api.example.com/api/payments/epay/return")
                self.assertEqual(pay_params["sign"], epay_sign(pay_params, "merchant-secret"))
                self.assertEqual(service.get_order(str(order["out_trade_no"]))["return_base_url"], "https://new-app.example.com")  # type: ignore[index]

                with self.assertRaisesRegex(PaymentError, "payment order not found"):
                    service.create_order_pay_url(
                        user_id=str(other_user["id"]),
                        out_trade_no=str(order["out_trade_no"]),
                        api_base_url="https://api.example.com",
                    )

                service.mark_order_paid(str(order["out_trade_no"]))
                with self.assertRaisesRegex(PaymentError, "payment order is not pending"):
                    service.create_order_pay_url(
                        user_id=str(user["id"]),
                        out_trade_no=str(order["out_trade_no"]),
                        api_base_url="https://api.example.com",
                    )
        finally:
            if original_type is None:
                os.environ.pop("YANAI_EPAY_TYPE", None)
            else:
                os.environ["YANAI_EPAY_TYPE"] = original_type

    def test_user_and_admin_can_cancel_pending_orders(self) -> None:
        original_type = os.environ.get("YANAI_EPAY_TYPE")
        os.environ.pop("YANAI_EPAY_TYPE", None)
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                service, auth, user = self._create_service(tmp_dir)
                order, _ = service.create_subscription_order(
                    user=user,
                    plan_id="starter",
                    api_base_url="https://example.com",
                    return_base_url="https://app.example.com",
                )

                canceled_order, canceled = service.cancel_order(
                    str(order["out_trade_no"]),
                    user_id=str(user["id"]),
                    actor=user,
                    reason="user",
                )
                self.assertTrue(canceled)
                self.assertEqual(canceled_order["status"], "canceled")
                self.assertEqual(canceled_order["cancel_reason"], "user")
                self.assertIsNotNone(canceled_order["canceled_at"])
                self.assertEqual(auth.get_user(str(user["id"]))["quota"], 0)  # type: ignore[index]

                duplicate_order, duplicate_canceled = service.cancel_order(
                    str(order["out_trade_no"]),
                    user_id=str(user["id"]),
                    reason="user",
                )
                self.assertFalse(duplicate_canceled)
                self.assertEqual(duplicate_order["status"], "canceled")

                with self.assertRaisesRegex(PaymentError, "payment order is not pending"):
                    service.create_order_pay_url(
                        user_id=str(user["id"]),
                        out_trade_no=str(order["out_trade_no"]),
                        api_base_url="https://api.example.com",
                    )
                with self.assertRaisesRegex(PaymentError, "canceled payment order cannot be marked as paid"):
                    service.mark_order_paid(str(order["out_trade_no"]))

                admin_order, _ = service.create_subscription_order(
                    user=user,
                    plan_id="starter",
                    api_base_url="https://example.com",
                    return_base_url="https://app.example.com",
                )
                admin_canceled_order, admin_canceled = service.cancel_order(
                    str(admin_order["out_trade_no"]),
                    actor={"id": "admin", "name": "Admin", "email": "admin@example.com", "role": "admin"},
                    reason="admin",
                    include_admin=True,
                )
                self.assertTrue(admin_canceled)
                self.assertEqual(admin_canceled_order["status"], "canceled")
                self.assertEqual(admin_canceled_order["cancel_reason"], "admin")
                self.assertEqual(admin_canceled_order["canceled_by"]["email"], "admin@example.com")  # type: ignore[index]

                canceled_orders = service.list_orders(status="canceled")
                self.assertEqual({item["out_trade_no"] for item in canceled_orders}, {order["out_trade_no"], admin_order["out_trade_no"]})
        finally:
            if original_type is None:
                os.environ.pop("YANAI_EPAY_TYPE", None)
            else:
                os.environ["YANAI_EPAY_TYPE"] = original_type

    def test_admin_can_delete_only_canceled_orders(self) -> None:
        original_type = os.environ.get("YANAI_EPAY_TYPE")
        os.environ.pop("YANAI_EPAY_TYPE", None)
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                service, _auth, user = self._create_service(tmp_dir)
                first_order, _ = service.create_subscription_order(
                    user=user,
                    plan_id="starter",
                    api_base_url="https://example.com",
                    return_base_url="https://app.example.com",
                )
                second_order, _ = service.create_subscription_order(
                    user=user,
                    plan_id="starter",
                    api_base_url="https://example.com",
                    return_base_url="https://app.example.com",
                )
                pending_order, _ = service.create_subscription_order(
                    user=user,
                    plan_id="starter",
                    api_base_url="https://example.com",
                    return_base_url="https://app.example.com",
                )

                service.cancel_order(str(first_order["out_trade_no"]), reason="admin")
                service.cancel_order(str(second_order["out_trade_no"]), reason="admin")

                with self.assertRaisesRegex(PaymentError, "only canceled payment orders can be deleted"):
                    service.delete_canceled_orders([str(first_order["out_trade_no"]), str(pending_order["out_trade_no"])])
                self.assertEqual(len(service.list_orders(status="canceled")), 2)

                result = service.delete_canceled_orders([str(first_order["out_trade_no"]), str(second_order["out_trade_no"])])
                self.assertEqual(result["removed"], 2)
                self.assertEqual(set(result["removed_ids"]), {first_order["out_trade_no"], second_order["out_trade_no"]})
                self.assertEqual(service.list_orders(status="canceled"), [])
                self.assertEqual(service.get_order(str(pending_order["out_trade_no"]))["status"], "pending")  # type: ignore[index]
        finally:
            if original_type is None:
                os.environ.pop("YANAI_EPAY_TYPE", None)
            else:
                os.environ["YANAI_EPAY_TYPE"] = original_type

    def test_pending_order_auto_cancels_after_timeout(self) -> None:
        original_type = os.environ.get("YANAI_EPAY_TYPE")
        os.environ.pop("YANAI_EPAY_TYPE", None)
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                service, auth, user = self._create_service(tmp_dir)
                order, _ = service.create_subscription_order(
                    user=user,
                    plan_id="starter",
                    api_base_url="https://example.com",
                    return_base_url="https://app.example.com",
                )
                self.assertEqual(order["status"], "pending")
                self.assertIsNotNone(order["expires_at"])

                orders = json.loads(service.path.read_text(encoding="utf-8"))
                orders[0]["expires_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
                service.path.write_text(json.dumps(orders), encoding="utf-8")

                user_orders = service.list_user_orders(str(user["id"]))
                self.assertEqual(user_orders[0]["status"], "canceled")
                self.assertEqual(user_orders[0]["cancel_reason"], "timeout")
                self.assertIsNotNone(user_orders[0]["canceled_at"])
                self.assertEqual(service.list_orders(status="pending"), [])
                self.assertEqual(service.list_orders(status="canceled")[0]["out_trade_no"], order["out_trade_no"])

                with self.assertRaisesRegex(PaymentError, "payment order is not pending"):
                    service.create_order_pay_url(
                        user_id=str(user["id"]),
                        out_trade_no=str(order["out_trade_no"]),
                        api_base_url="https://api.example.com",
                    )
                with self.assertRaisesRegex(PaymentError, "canceled payment order cannot be marked as paid"):
                    service.mark_order_paid(str(order["out_trade_no"]))

                callback = {
                    "pid": "1001",
                    "trade_no": "EPAY202607090003",
                    "out_trade_no": str(order["out_trade_no"]),
                    "type": "alipay",
                    "name": "基础套餐",
                    "money": "19.90",
                    "trade_status": "TRADE_SUCCESS",
                    "param": str(order["out_trade_no"]),
                }
                callback["sign"] = epay_sign(callback, "merchant-secret")
                callback["sign_type"] = "MD5"
                with self.assertRaisesRegex(PaymentError, "canceled payment order cannot be marked as paid"):
                    service.handle_epay_callback(callback)
                self.assertEqual(auth.get_user(str(user["id"]))["quota"], 0)  # type: ignore[index]
        finally:
            if original_type is None:
                os.environ.pop("YANAI_EPAY_TYPE", None)
            else:
                os.environ["YANAI_EPAY_TYPE"] = original_type


if __name__ == "__main__":
    unittest.main()
