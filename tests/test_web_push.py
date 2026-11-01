"""Tests for Web Push notifications and subscription lifecycle (Issue #208 / F11)."""

from __future__ import annotations

import base64
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from minime.api.app import app
from minime.domain.models import AuthorizedOperator
from minime.services.web_push_service import WebPushService


@pytest.fixture
def test_client(in_memory_uow: Any) -> TestClient:
    app.dependency_overrides = {}
    return TestClient(app)


def test_vapid_public_key_format(tmp_path: Any) -> None:
    key_file = tmp_path / "test_vapid.pem"
    svc = WebPushService(key_path=key_file)
    pub = svc.get_public_key_b64()
    assert isinstance(pub, str)
    # URL safe base64 of 65 bytes is ~87 characters
    assert len(pub) >= 80
    assert "=" not in pub
    # Reloading from file preserves the same key
    svc2 = WebPushService(key_path=key_file)
    assert svc2.get_public_key_b64() == pub


def test_send_to_subscription_respects_categories(tmp_path: Any) -> None:
    key_file = tmp_path / "test_vapid.pem"
    svc = WebPushService(key_path=key_file)

    class MockSub:
        endpoint = "https://fcm.googleapis.com/fcm/send/fake-endpoint"
        p256dh = "fake-p256dh"
        auth = "fake-auth"
        is_active = True
        category_human_required = False
        category_terminal_outcomes = True

    sub = MockSub()
    # Notification with category 'human_required' should be skipped because it is disabled
    with patch("minime.services.web_push_service.webpush") as mock_webpush:
        sent = svc.send_to_subscription(
            sub,
            title="Atención",
            body="Requiere aclaración",
            category="human_required",
        )
        assert sent is False
        mock_webpush.assert_not_called()

        # Notification with category 'terminal_outcomes' should call webpush
        sent = svc.send_to_subscription(
            sub,
            title="Finalizado",
            body="Run completado",
            category="terminal_outcomes",
        )
        assert sent is True
        mock_webpush.assert_called_once()


def test_send_to_subscription_deactivates_on_410_gone(tmp_path: Any) -> None:
    from pywebpush import WebPushException

    key_file = tmp_path / "test_vapid.pem"
    svc = WebPushService(key_path=key_file)

    class MockSub:
        endpoint = "https://fcm.googleapis.com/fcm/send/expired-endpoint"
        p256dh = "fake-p256dh"
        auth = "fake-auth"
        is_active = True
        last_error = None

    sub = MockSub()
    mock_resp = MagicMock()
    mock_resp.status_code = 410

    with patch("minime.services.web_push_service.webpush", side_effect=WebPushException("Gone", response=mock_resp)):
        sent = svc.send_to_subscription(
            sub,
            title="Prueba",
            body="Cuerpo",
        )
        assert sent is False
        assert sub.is_active is False
        assert "Endpoint expired" in (sub.last_error or "")


def test_push_api_endpoints_flow(in_memory_uow: Any) -> None:
    # Set up authorized operator and authentication bypass for test
    from minime.api.app import get_current_operator, get_uow

    operator = AuthorizedOperator(
        operator_id="op-1",
        email="operator@minime.test",
        display_name="Test Operator",
        is_active=True,
    )
    in_memory_uow.authorized_operators.save(operator)

    app.dependency_overrides[get_current_operator] = lambda: operator
    app.dependency_overrides[get_uow] = lambda: in_memory_uow

    try:
        client = TestClient(app)

        # 1. Get VAPID public key
        res = client.get("/api/v1/push/vapid-public-key")
        assert res.status_code == 200
        data = res.json()
        assert "public_key" in data
        assert len(data["public_key"]) > 50

        # 2. Register subscription
        sub_payload = {
            "endpoint": "https://push.services.mozilla.com/v1/abc123xyz",
            "keys": {
                "p256dh": "dummy-p256dh",
                "auth": "dummy-auth",
            },
            "device_label": "Firefox Test Mobile",
            "categories": {
                "stage_transitions": True,
                "human_required": True,
                "terminal_outcomes": True,
            },
        }
        res_sub = client.post("/api/v1/push/subscriptions", json=sub_payload)
        assert res_sub.status_code == 200
        assert res_sub.json()["status"] == "subscribed"

        # Check repository state
        sub_in_db = in_memory_uow.push_subscriptions.get_by_endpoint(sub_payload["endpoint"])
        assert sub_in_db is not None
        assert sub_in_db.operator_id == "operator@minime.test"
        assert sub_in_db.is_active is True

        # 3. Test push endpoint
        with patch("minime.services.web_push_service.webpush") as mock_wp:
            res_test = client.post("/api/v1/push/test", json={"title": "Test Title", "body": "Test Body"})
            assert res_test.status_code == 200
            assert res_test.json()["sent_count"] == 1
            mock_wp.assert_called_once()

        # 4. Deactivate subscription
        res_unsub = client.request(
            "DELETE",
            "/api/v1/push/subscriptions",
            json={"endpoint": sub_payload["endpoint"]},
        )
        assert res_unsub.status_code == 200
        assert res_unsub.json()["status"] == "unsubscribed"

        sub_in_db_after = in_memory_uow.push_subscriptions.get_by_endpoint(sub_payload["endpoint"])
        assert sub_in_db_after.is_active is False
    finally:
        app.dependency_overrides.clear()
