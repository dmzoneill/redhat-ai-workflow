"""
Message processing components for the Slack daemon.

Contains:
- UserCategory / UserClassification / UserClassifier: User classification
- AlertDetector: Prometheus alert detection
- ResponseRules / ChannelPermissions: Channel-level response rules
"""

import logging
from dataclasses import dataclass
from enum import Enum

from scripts.common.config_loader import load_config

logger = logging.getLogger(__name__)


def _get_slack_config():
    """Get current slack config from config.json."""
    config = load_config()
    return config.get("slack", {})


# =============================================================================
# USER CLASSIFICATION
# =============================================================================


class UserCategory(Enum):
    """User classification categories."""

    SAFE = "safe"  # Teammates - respond freely
    CONCERNED = "concerned"  # Managers - respond carefully
    UNKNOWN = "unknown"  # Everyone else - professional default


@dataclass
class UserClassification:
    """Classification result for a user."""

    category: UserCategory
    response_style: str  # casual, formal, professional
    auto_respond: bool
    require_review: bool
    include_emojis: bool
    cc_notification: bool
    max_response_length: int | None


class UserClassifier:
    """Classifies users based on config.json lists."""

    def __init__(self, slack_config: dict | None = None):
        self._slack_config = slack_config or _get_slack_config()
        self.user_config = self._slack_config.get("user_classification", {})
        self._load_lists()

    def _load_lists(self):
        """Load user lists from config."""
        safe = self.user_config.get("safe_list", {})
        self.safe_user_ids = set(safe.get("user_ids", []))
        self.safe_user_names = set(u.lower() for u in safe.get("user_names", []))

        concerned = self.user_config.get("concerned_list", {})
        self.concerned_user_ids = set(concerned.get("user_ids", []))
        self.concerned_user_names = set(
            u.lower() for u in concerned.get("user_names", [])
        )

    def classify(self, user_id: str, user_name: str) -> UserClassification:
        """Classify a user and return response settings."""
        user_name_lower = user_name.lower()

        # Check concerned list first (takes priority)
        if (
            user_id in self.concerned_user_ids
            or user_name_lower in self.concerned_user_names
        ):
            concerned = self.user_config.get("concerned_list", {})
            return UserClassification(
                category=UserCategory.CONCERNED,
                response_style=concerned.get("response_style", "formal"),
                auto_respond=concerned.get("auto_respond", False),
                require_review=concerned.get("require_review", True),
                include_emojis=concerned.get("include_emojis", False),
                cc_notification=concerned.get("cc_notification", True),
                max_response_length=None,
            )

        # Check safe list
        if user_id in self.safe_user_ids or user_name_lower in self.safe_user_names:
            safe = self.user_config.get("safe_list", {})
            return UserClassification(
                category=UserCategory.SAFE,
                response_style=safe.get("response_style", "casual"),
                auto_respond=safe.get("auto_respond", True),
                require_review=False,
                include_emojis=safe.get("include_emojis", True),
                cc_notification=False,
                max_response_length=None,
            )

        # Default: unknown
        unknown = self.user_config.get("unknown_list", {})
        return UserClassification(
            category=UserCategory.UNKNOWN,
            response_style=unknown.get("response_style", "professional"),
            auto_respond=unknown.get("auto_respond", True),
            require_review=False,
            include_emojis=unknown.get("include_emojis", True),
            cc_notification=False,
            max_response_length=unknown.get("max_response_length", 500),
        )

    def reload(self):
        """Reload lists from config (for hot reload)."""
        self._slack_config = _get_slack_config()
        self.user_config = self._slack_config.get("user_classification", {})
        self._load_lists()


# =============================================================================
# ALERT DETECTION
# =============================================================================


class AlertDetector:
    """
    Detects Prometheus alert messages from app-sre-alerts bot.

    Alert messages come from the app-sre-alerts bot in specific channels
    (stage/prod alerts) and contain Prometheus alert information with
    links to Grafana, AlertManager, Runbook, etc.
    """

    def __init__(self, slack_config: dict | None = None):
        self._slack_config = slack_config or _get_slack_config()
        self.config = self._slack_config.get("listener", {})
        self.alert_channels = self.config.get("alert_channels", {})
        self.alert_bot_names = self.config.get(
            "alert_bot_names", ["app-sre-alerts", "alertmanager"]
        )

    def is_alert_message(
        self,
        channel_id: str,
        user_name: str,
        text: str,
        raw_message: dict | None = None,
    ) -> bool:
        """
        Check if this message is a Prometheus alert.

        An alert message is:
        1. In an alert channel (C01CPSKFG0P or C01L1K82AP5)
        2. From the app-sre-alerts bot
        3. Contains alert indicators (FIRING, Alert:, alertmanager URL)
        """
        # Check if it's an alert channel
        if channel_id not in self.alert_channels:
            return False

        # Check if from alert bot
        user_lower = (user_name or "").lower()

        # If user_name is missing, try to get it from raw_message
        if not user_lower and raw_message:
            user_lower = (
                raw_message.get("username") or raw_message.get("bot_id") or ""
            ).lower()

        is_from_alert_bot = any(bot in user_lower for bot in self.alert_bot_names)

        # Check for alert indicators in text
        text_lower = (text or "").lower()

        # If text is missing, try to get it from attachments in raw_message
        if not text_lower and raw_message and "attachments" in raw_message:
            att_texts = []
            for att in raw_message["attachments"]:
                if isinstance(att, dict):
                    att_texts.append(
                        (att.get("text") or att.get("fallback") or "").lower()
                    )
                    att_texts.append((att.get("title") or "").lower())
                elif isinstance(att, str):
                    att_texts.append(att.lower())
            text_lower = " ".join(att_texts)

        alert_indicators = self.config.get(
            "alert_indicators",
            [
                "firing",
                "resolved",
                "alert:",
                "alertmanager",
                "prometheus",
            ],
        )
        has_alert_indicator = any(ind in text_lower for ind in alert_indicators)

        is_alert = is_from_alert_bot or (
            channel_id in self.alert_channels and has_alert_indicator
        )

        if is_alert:
            logger.info(
                f"🚨 Alert detected: channel={channel_id}, user={user_name}, text={text[:100]}..."
            )

        return is_alert

    def get_alert_info(self, channel_id: str) -> dict:
        """Get the channel's alert configuration."""
        info = self.alert_channels.get(channel_id)
        if isinstance(info, dict):
            return info

        return self.config.get(
            "default_alert_info",
            {
                "environment": "unknown",
                "namespace": "unknown",
                "severity": "medium",
                "auto_investigate": False,
            },
        )

    def should_auto_investigate(self, channel_id: str) -> bool:
        """Check if this channel has auto-investigate enabled."""
        info = self.get_alert_info(channel_id)
        if isinstance(info, dict):
            return info.get("auto_investigate", False)
        return False


# =============================================================================
# CHANNEL PERMISSIONS / RESPONSE RULES
# =============================================================================


class ResponseRules:
    """
    Controls when the agent should respond based on message context.

    Rules:
    1. DMs: Always respond (approval required for concerned users)
    2. Channels: Only respond when mentioned (@username or @group)
    3. Unmentioned channel messages: Ignore
    """

    def __init__(self, slack_config: dict | None = None):
        self._slack_config = slack_config or _get_slack_config()
        self.config = self._slack_config.get("response_rules", {})
        self._load_config()

    def _load_config(self):
        """Load response rules from config."""
        # DM settings
        dm_config = self.config.get("direct_messages", {})
        self.dm_enabled = dm_config.get("enabled", True)

        # Channel mention settings
        mention_config = self.config.get("channel_mentions", {})
        self.mention_enabled = mention_config.get("enabled", True)
        self.trigger_mentions = set(mention_config.get("trigger_mentions", []))
        self.trigger_user_ids = set(mention_config.get("trigger_user_ids", []))
        self.trigger_group_ids = set(mention_config.get("trigger_group_ids", []))

        # Keyword settings (optional)
        keyword_config = self.config.get("channel_keywords", {})
        self.keyword_enabled = keyword_config.get("enabled", False)
        self.trigger_keywords = set(keyword_config.get("keywords", []))

        # General settings
        self.ignore_unmentioned = self.config.get("ignore_unmentioned", True)
        self.blocked_channels = set(self.config.get("blocked_channels", []))

    def _check_user_mentions(self, mentioned_users: list[str]) -> tuple[bool, str]:
        """Check if any trigger users are mentioned."""
        for user_id in mentioned_users:
            if user_id in self.trigger_user_ids:
                return True, f"Trigger user {user_id} mentioned"
        return False, ""

    def _check_group_mentions(self, mentioned_groups: list[str]) -> tuple[bool, str]:
        """Check if any trigger groups are mentioned."""
        for group_id in mentioned_groups:
            if group_id in self.trigger_group_ids:
                return True, f"Trigger group {group_id} mentioned"
        return False, ""

    def _check_text_mentions(self, message_text: str) -> tuple[bool, str]:
        """Check if any trigger mentions appear in text."""
        text_lower = message_text.lower()
        for mention in self.trigger_mentions:
            if mention.lower() in text_lower:
                return True, f"Trigger mention '{mention}' found"
        return False, ""

    def _check_keywords(self, message_text: str) -> tuple[bool, str]:
        """Check if any trigger keywords appear in text."""
        text_lower = message_text.lower()
        for keyword in self.trigger_keywords:
            if keyword.lower() in text_lower:
                return True, f"Trigger keyword '{keyword}' found"
        return False, ""

    def should_respond(
        self,
        channel_id: str,
        message_text: str,
        is_dm: bool = False,
        is_mention: bool = False,
        mentioned_users: list[str] | None = None,
        mentioned_groups: list[str] | None = None,
    ) -> tuple[bool, str]:
        """
        Determine if the agent should respond to this message.

        Args:
            channel_id: The channel ID
            message_text: The message text
            is_dm: Whether this is a direct message
            is_mention: Whether the bot was mentioned (from Slack API)
            mentioned_users: List of user IDs mentioned in the message
            mentioned_groups: List of group IDs mentioned in the message

        Returns:
            tuple of (should_respond, reason)
        """
        mentioned_users = mentioned_users or []
        mentioned_groups = mentioned_groups or []

        # Check blocked list first
        if channel_id in self.blocked_channels:
            return False, "Channel is blocked"

        # Rule 1: DMs - always respond if enabled
        if is_dm:
            if self.dm_enabled:
                return True, "DM response enabled"
            return False, "DM responses disabled"

        # Rule 2: Channel mentions - check if we're mentioned
        if self.mention_enabled:
            # Check if bot was directly mentioned (from Slack API)
            if is_mention:
                return True, "Bot was @mentioned"

            # Check trigger user IDs
            should_respond, reason = self._check_user_mentions(mentioned_users)
            if should_respond:
                return True, reason

            # Check trigger group IDs
            should_respond, reason = self._check_group_mentions(mentioned_groups)
            if should_respond:
                return True, reason

            # Check trigger mentions in text
            should_respond, reason = self._check_text_mentions(message_text)
            if should_respond:
                return True, reason

        # Rule 3: Keywords (if enabled)
        if self.keyword_enabled:
            should_respond, reason = self._check_keywords(message_text)
            if should_respond:
                return True, reason

        # Default: ignore unmentioned channel messages
        if self.ignore_unmentioned:
            return False, "Not mentioned in channel"

        return True, "Default allow"

    def reload(self):
        """Reload config (for hot reload)."""
        self._slack_config = _get_slack_config()
        self.config = self._slack_config.get("response_rules", {})
        self._load_config()


# Keep ChannelPermissions as alias for backwards compatibility
ChannelPermissions = ResponseRules
