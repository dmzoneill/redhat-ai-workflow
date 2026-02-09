"""Path setup for Slack daemon - must be imported first."""

import os
import sys

# Add project paths for imports
_service_dir = os.path.dirname(os.path.abspath(__file__))
_services_dir = os.path.dirname(_service_dir)  # services/
PROJECT_ROOT = os.path.dirname(_services_dir)  # project root
sys.path.insert(0, PROJECT_ROOT)  # For server.utils import
sys.path.insert(0, os.path.join(PROJECT_ROOT, "tool_modules", "aa_git"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "tool_modules", "aa_gitlab"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "tool_modules", "aa_jira"))
sys.path.insert(
    0, os.path.join(PROJECT_ROOT, "tool_modules", "aa_slack")
)  # Must be first
