"""Web Push notification service using pywebpush and VAPID.

Handles VAPID key lifecycle, subscription dispatching, error deactivation (404/410),
and integration with operator preferences and categories.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from pywebpush import Vapid, WebPushException, webpush

from minime.domain.models import utc_now

logger = logging.getLogger(__name__)

def _resolve_default_key_path() -> Path:
    env_path = os.environ.get("MINIME_VAPID_KEY_PATH")
    if env_path:
        return Path(env_path)
    opt_path = Path("/opt/minime/data/vapid_private.pem")
    try:
        opt_path.parent.mkdir(parents=True, exist_ok=True)
        if os.access(opt_path.parent, os.W_OK):
            return opt_path
    except Exception:
        pass
    home_dir = Path.home() / ".minime"
    return home_dir / "vapid_private.pem"


class WebPushService:
    def __init__(
        self,
        key_path: Path | None = None,
        vapid_claims: dict[str, Any] | None = None,
    ) -> None:
        self.key_path = key_path or _resolve_default_key_path()
        self.claims = vapid_claims or {
            "sub": os.environ.get("MINIME_VAPID_SUB", "mailto:operator@minime.local")
        }
        self._vapid: Vapid | None = None
        self._init_vapid_keys()

    def _init_vapid_keys(self) -> None:
        """Load or create persistent VAPID EC keypair."""
        # 1. Environment variable override
        private_pem_env = os.environ.get("MINIME_VAPID_PRIVATE_KEY")
        if private_pem_env:
            try:
                self._vapid = Vapid.from_pem(private_pem_env.encode("utf-8"))
                return
            except Exception as e:
                logger.warning("Failed to load VAPID key from MINIME_VAPID_PRIVATE_KEY: %s", e)

        # 2. File-based persistence
        if self.key_path.exists():
            try:
                pem_data = self.key_path.read_bytes()
                self._vapid = Vapid.from_pem(pem_data)
                return
            except Exception as e:
                logger.warning("Failed to read VAPID key file %s: %s", self.key_path, e)

        # 3. Generate fresh keypair and persist if possible
        v = Vapid()
        v.generate_keys()
        self._vapid = v
        try:
            self.key_path.parent.mkdir(parents=True, exist_ok=True)
            self.key_path.write_bytes(v.private_pem())
            os.chmod(self.key_path, 0o600)
            logger.info("Generated and saved new VAPID keys to %s", self.key_path)
        except Exception as e:
            logger.warning("Could not persist VAPID key to %s (in-memory only): %s", self.key_path, e)

    def get_public_key_b64(self) -> str:
        """Return URL-safe base64 uncompressed point of VAPID public key (for applicationServerKey)."""
        if not self._vapid:
            raise RuntimeError("VAPID keys not initialized")
        raw_pub = self._vapid.public_key.public_bytes(
            Encoding.X962, PublicFormat.UncompressedPoint
        )
        return base64.urlsafe_b64encode(raw_pub).rstrip(b"=").decode("ascii")

    def send_to_subscription(
        self,
        subscription: Any,
        title: str,
        body: str,
        data: dict[str, Any] | None = None,
        category: str | None = None,
    ) -> bool:
        """Send push notification to a specific PushSubscriptionModel or object."""
        if not getattr(subscription, "is_active", True):
            return False

        # Category filtering
        if category:
            cat_attr = f"category_{category}"
            if hasattr(subscription, cat_attr) and not getattr(subscription, cat_attr):
                logger.debug(
                    "Skipping notification for sub %s: category %s disabled",
                    getattr(subscription, "id", "unknown"),
                    category,
                )
                return False

        target_url = (data or {}).get("url", "/trabajo-actual")
        payload_obj = {
            "notification": {
                "title": title,
                "body": body,
                "icon": "/assets/icons/icon-192x192.png",
                "badge": "/assets/icons/icon-72x72.png",
                "vibrate": [100, 50, 100],
                "data": {
                    "url": target_url,
                    "onActionClick": {
                        "default": {"operation": "focusLastFocusedOrOpen", "url": target_url}
                    },
                    **(data or {}),
                },
            },
            # Flat attributes for custom handlers
            "title": title,
            "body": body,
            "data": data or {},
        }
        payload_data = json.dumps(payload_obj)

        subscription_info = {
            "endpoint": subscription.endpoint,
            "keys": {
                "p256dh": subscription.p256dh,
                "auth": subscription.auth,
            },
        }

        try:
            webpush(
                subscription_info=subscription_info,
                data=payload_data,
                vapid_private_key=self._vapid,
                vapid_claims=self.claims,
            )
            if hasattr(subscription, "last_success_at"):
                subscription.last_success_at = utc_now()
                subscription.last_error = None
            return True
        except WebPushException as ex:
            status_code = getattr(getattr(ex, "response", None), "status_code", None)
            logger.warning(
                "WebPushException sending to %s (HTTP %s): %s",
                subscription.endpoint,
                status_code,
                ex,
            )
            # Automatic deactivation on 404 or 410 (Gone)
            if status_code in (404, 410):
                if hasattr(subscription, "is_active"):
                    subscription.is_active = False
                    subscription.last_error = f"Endpoint expired (HTTP {status_code})"
                    subscription.updated_at = utc_now()
            else:
                if hasattr(subscription, "last_error"):
                    subscription.last_error = str(ex)
            return False
        except Exception as ex:
            logger.warning("Unexpected error sending web push to %s: %s", subscription.endpoint, ex)
            if hasattr(subscription, "last_error"):
                subscription.last_error = str(ex)
            return False

    def send_to_operator(
        self,
        uow: Any,
        operator_id: str,
        title: str,
        body: str,
        data: dict[str, Any] | None = None,
        category: str | None = None,
    ) -> int:
        """Send push notification to all active devices of an operator."""
        if not hasattr(uow, "push_subscriptions"):
            return 0
        subs = uow.push_subscriptions.list_by_operator(operator_id, active_only=True)
        sent_count = 0
        for sub in subs:
            success = self.send_to_subscription(
                subscription=sub,
                title=title,
                body=body,
                data=data,
                category=category,
            )
            if success:
                sent_count += 1
        return sent_count

    def broadcast_to_active_operators(
        self,
        uow: Any,
        title: str,
        body: str,
        data: dict[str, Any] | None = None,
        category: str | None = None,
    ) -> int:
        """Broadcast notification to all active push subscriptions across operators."""
        if not hasattr(uow, "push_subscriptions"):
            return 0
        # If uow repository has list_by_operator or direct query:
        repo = uow.push_subscriptions
        if hasattr(repo, "list_all_active"):
            subs = repo.list_all_active()
        elif hasattr(repo, "session"):
            from minime.db.models import PushSubscriptionModel
            from sqlalchemy import select

            stmt = select(PushSubscriptionModel).where(PushSubscriptionModel.is_active.is_(True))
            subs = list(repo.session.scalars(stmt).all())
        else:
            # Fallback for mock uow store
            store = getattr(repo, "_store", {})
            subs = [s for s in store.values() if getattr(s, "is_active", True)]

        sent_count = 0
        for sub in subs:
            success = self.send_to_subscription(
                subscription=sub,
                title=title,
                body=body,
                data=data,
                category=category,
            )
            if success:
                sent_count += 1
        return sent_count


web_push_service = WebPushService()
