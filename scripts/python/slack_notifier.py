"""
scripts/python/slack_notifier.py
Slack webhook notification helper — used by all Python automation scripts.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


class AlertLevel(str, Enum):
    INFO = "good"
    WARNING = "warning"
    CRITICAL = "danger"


@dataclass
class SlackMessage:
    title: str
    text: str
    level: AlertLevel = AlertLevel.INFO
    fields: list[dict[str, str]] = field(default_factory=list)
    footer: str = "AI Ops Toolkit"


class SlackNotifier:
    """Send structured Slack notifications via incoming webhooks."""

    def __init__(
        self,
        webhook_url: str | None = None,
        channel: str | None = None,
        username: str = "AI Ops Bot",
        icon_emoji: str = ":robot_face:",
    ) -> None:
        self.webhook_url = webhook_url or os.environ.get("SLACK_WEBHOOK_URL", "")
        self.channel = channel or os.environ.get("SLACK_CHANNEL", "#ops-alerts")
        self.username = username
        self.icon_emoji = icon_emoji

        if not self.webhook_url:
            logger.warning("SLACK_WEBHOOK_URL not set — notifications will be skipped.")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=False,
    )
    def send(self, message: SlackMessage) -> bool:
        """Send a formatted Slack notification. Returns True on success."""
        if not self.webhook_url:
            logger.debug("Slack webhook not configured, skipping send.")
            return False

        payload: dict[str, Any] = {
            "username": self.username,
            "icon_emoji": self.icon_emoji,
            "channel": self.channel,
            "attachments": [
                {
                    "color": message.level.value,
                    "title": message.title,
                    "text": message.text,
                    "footer": message.footer,
                    "ts": _unix_ts(),
                }
            ],
        }

        if message.fields:
            payload["attachments"][0]["fields"] = [
                {"title": f["title"], "value": f["value"], "short": f.get("short", True)}
                for f in message.fields
            ]

        resp = requests.post(self.webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
        logger.info("Slack notification sent: %s", message.title)
        return True

    def info(self, title: str, text: str, **kwargs: Any) -> bool:
        return self.send(SlackMessage(title=title, text=text, level=AlertLevel.INFO, **kwargs))

    def warning(self, title: str, text: str, **kwargs: Any) -> bool:
        return self.send(SlackMessage(title=title, text=text, level=AlertLevel.WARNING, **kwargs))

    def critical(self, title: str, text: str, **kwargs: Any) -> bool:
        return self.send(SlackMessage(title=title, text=text, level=AlertLevel.CRITICAL, **kwargs))


def _unix_ts() -> int:
    import time
    return int(time.time())


# ── Module-level convenience instance ────────────────────────────────────────
_default_notifier: SlackNotifier | None = None


def get_notifier() -> SlackNotifier:
    global _default_notifier
    if _default_notifier is None:
        _default_notifier = SlackNotifier()
    return _default_notifier
