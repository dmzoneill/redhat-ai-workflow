"""Channel, author, and text fields shared by Slack history records."""

from dataclasses import dataclass


@dataclass
class SlackMessageFields:  # pylint: disable=too-few-public-methods
    """Identity fields present on every stored Slack message.

    Subclasses add their own fields. Callers construct records with keywords,
    so the inherited field order does not change those call sites.
    """

    channel_id: str
    channel_name: str
    user_id: str
    user_name: str
    text: str

    def identity_dict(self) -> dict[str, str]:
        """Return the shared channel, author, and text fields."""
        return {
            "channel_id": self.channel_id,
            "channel_name": self.channel_name,
            "user_id": self.user_id,
            "user_name": self.user_name,
            "text": self.text,
        }
