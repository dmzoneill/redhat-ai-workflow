#!/usr/bin/env python3
"""InScope Auto-Login - Automatically authenticate with InScope using aa_sso module.

This script uses the aa_sso module (Playwright-based) to:
1. Navigate to InScope
2. Complete OIDC login if needed (using credentials from redhatter service)
3. Extract the JWT token and session cookie
4. Save them for use by the InScope adapter

Usage:
    python scripts/inscope_auto_login.py [--headless] [--check]

The script uses Playwright for browser automation, which properly triggers
JavaScript events required for SSO form validation.
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Cache directory for InScope credentials
INSCOPE_CACHE_DIR = Path.home() / ".cache" / "inscope"


def check_existing_token() -> bool:
    """Check if we have a valid cached token.

    Returns:
        True if token is valid, False otherwise
    """
    token_file = INSCOPE_CACHE_DIR / "token"
    if not token_file.exists():
        logger.warning("No token file found")
        return False

    try:
        content = token_file.read_text().strip()
        if content.startswith("{"):
            data = json.loads(content)
            token = data.get("token")
            expires_at = data.get("expires_at", 0)
        else:
            token = content
            import jwt

            claims = jwt.decode(token, options={"verify_signature": False})
            expires_at = claims.get("exp", 0)

        remaining = expires_at - time.time()
        if remaining > 0:
            logger.info(f"Token is valid, expires in {int(remaining)} seconds ({int(remaining/60)} minutes)")
            return True
        else:
            logger.warning(f"Token has expired ({int(-remaining)} seconds ago)")
            return False
    except Exception as e:
        logger.warning(f"Could not validate token: {e}")
        return False


async def login_to_inscope(headless: bool = True) -> bool:
    """Login to InScope using aa_sso module.

    Args:
        headless: Run browser in headless mode

    Returns:
        True if login successful, False otherwise
    """
    try:
        from tool_modules.aa_sso.src.tools_basic import SSOAuthenticator

        logger.info("Starting InScope authentication via aa_sso module...")

        auth = SSOAuthenticator(headless=headless)
        result = await auth.authenticate("inscope")

        if result.success:
            logger.info("✅ InScope authentication successful!")
            logger.info(f"Final URL: {result.final_url}")

            if result.jwt_token:
                logger.info("JWT token extracted and saved")
                if result.jwt_expires_at:
                    import datetime

                    exp_time = datetime.datetime.fromtimestamp(result.jwt_expires_at)
                    remaining = result.jwt_expires_at - time.time()
                    logger.info(f"Token expires at: {exp_time} ({int(remaining/60)} minutes)")

            if result.cookies:
                logger.info(f"Cookies extracted: {list(result.cookies.keys())}")

            return True
        else:
            logger.error(f"❌ InScope authentication failed: {result.error}")
            if result.screenshot_path:
                logger.error(f"Screenshot saved: {result.screenshot_path}")
            return False

    except ImportError as e:
        logger.error(f"Failed to import aa_sso module: {e}")
        logger.error("Make sure playwright is installed: pip install playwright && playwright install chromium")
        return False
    except Exception as e:
        logger.exception(f"Authentication failed: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Auto-login to InScope and extract authentication credentials")
    parser.add_argument("--headless", "-hl", action="store_true", help="Run browser in headless mode")
    parser.add_argument("--check", action="store_true", help="Only check current auth status, don't login")
    args = parser.parse_args()

    if args.check:
        # Just check if we have valid credentials
        if check_existing_token():
            return 0
        return 1

    logger.info("Starting InScope auto-login...")
    logger.info(f"Headless mode: {args.headless}")

    # Run the async login
    success = asyncio.run(login_to_inscope(headless=args.headless))

    if success:
        logger.info("✅ InScope credentials saved successfully!")
        return 0
    else:
        logger.error("❌ Failed to authenticate to InScope")
        logger.info("Try running without --headless to see the browser")
        return 1


if __name__ == "__main__":
    sys.exit(main())
