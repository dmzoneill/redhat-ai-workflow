"""Slack Web Client Session Manager.

Re-exports the module API so existing imports keep working.
"""

from tool_modules.aa_slack.src import slack_session as _impl

RateLimitState = _impl.RateLimitState
SlackSession = _impl.SlackSession
