"""Concur expense automation tools.

Provides flexible, AI-assisted expense submission workflow.
Uses semantic element descriptions and adaptive retry logic.
"""

import json
import logging
import os
import re
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent

# Setup project path for server imports
from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT

from server.tool_registry import ToolRegistry
from server.utils import get_section_config

logger = logging.getLogger(__name__)

# ==================== Configuration ====================

AA_CONCUR_DIR = Path.home() / "src" / "aa-concur"
DOWNLOADS_DIR = AA_CONCUR_DIR / "downloads"
GOMO_SCRIPT = AA_CONCUR_DIR / "scripts" / "gomo_to_concur.py"
TOKEN_CACHE_PATH = Path.home() / ".cache" / "redhatter" / "auth_token"


def load_concur_config() -> dict:
    """Load concur configuration from config.json."""
    return get_section_config(
        "concur",
        {
            "gomo": {
                "url": "https://my.gomo.ie/",
                "bills_url": "https://my.gomo.ie/bills",
                "bitwarden_item": "gomo.ie",
            },
            "concur": {
                "sso_url": "https://auth.redhat.com/auth/realms/EmployeeIDP/protocol/saml/clients/concursolutions",
                "home_url": "https://us2.concursolutions.com/home",
                "expense_type": "Remote Worker Expense",
                "payment_type": "Cash",
                "max_usd_amount": 40.00,
            },
            "downloads_dir": str(DOWNLOADS_DIR),
        },
    )


# ==================== Credential Helpers ====================


def _get_bitwarden_password(item_name: str, username: str | None = None) -> tuple[str, str]:
    """Get credentials from Bitwarden CLI.

    Returns:
        Tuple of (username, password)
    """
    bw_session = os.environ.get("BW_SESSION")
    if not bw_session:
        raise RuntimeError("BW_SESSION not set. Run: export BW_SESSION=$(bw unlock --raw)")

    try:
        result = subprocess.run(
            ["bw", "list", "items", "--search", item_name],
            capture_output=True,
            text=True,
            env={**os.environ, "BW_SESSION": bw_session},
            timeout=30,
        )

        if result.returncode != 0:
            raise RuntimeError(f"Bitwarden search failed: {result.stderr}")

        items = json.loads(result.stdout)

        for item in items:
            if item.get("name") == item_name:
                login = item.get("login", {})
                found_user = login.get("username", "")
                found_pass = login.get("password", "")

                if username and found_user != username:
                    continue

                if found_user and found_pass:
                    return found_user, found_pass

        raise RuntimeError(f"No matching credentials found for {item_name}")

    except subprocess.TimeoutExpired:
        raise RuntimeError("Bitwarden CLI timed out")
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse Bitwarden response: {e}")


def _get_pass_password(pass_path: str) -> str:
    """Get password from GNU pass store."""
    try:
        result = subprocess.run(
            ["pass", "show", pass_path],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            raise RuntimeError(f"Pass failed: {result.stderr}")

        # First non-empty line is the password
        for line in result.stdout.splitlines():
            if line.strip():
                return line.strip()

        raise RuntimeError(f"Empty password in pass entry: {pass_path}")

    except subprocess.TimeoutExpired:
        raise RuntimeError("Pass command timed out")


def _get_redhatter_token() -> str:
    """Read the redhatter authentication token."""
    if not TOKEN_CACHE_PATH.exists():
        raise RuntimeError(
            f"Auth token not found at {TOKEN_CACHE_PATH}. " "Start the redhatter service to generate it."
        )

    token = TOKEN_CACHE_PATH.read_text(encoding="utf-8").strip()
    if not token:
        raise RuntimeError(f"Auth token at {TOKEN_CACHE_PATH} is empty")

    return token


def _fetch_concur_credentials(token: str, headless: bool = True) -> tuple[str, str]:
    """Fetch Concur credentials from local redhatter service."""
    import urllib.error
    import urllib.parse
    import urllib.request

    params = urllib.parse.urlencode({"context": "associate", "headless": str(headless).lower()})
    url = f"http://localhost:8009/get_creds?{params}"

    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Failed to get Concur credentials: {e}")

    # Parse response: "username,password"
    sanitized = payload.replace('"', "").replace("\n", "").strip()
    parts = sanitized.split(",")

    if len(parts) < 2:
        raise RuntimeError(f"Invalid credential response: {sanitized!r}")

    return parts[0].strip(), parts[1].strip()


# ==================== PDF Helpers ====================


def _extract_amount_from_text(text: str) -> str | None:
    """Extract billing amount from text.

    Looks for patterns like "bill for this month € XX.XX"
    """
    # Try "bill for this month" pattern first
    match = re.search(r"bill\s+for\s+this\s+month\s*€\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)", text, re.IGNORECASE)
    if match:
        return match.group(1).replace(",", "")

    # Find first non-zero € amount
    for match in re.finditer(r"€\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)", text):
        amount = match.group(1).replace(",", "")
        if amount != "0.00" and float(amount) > 0:
            return amount

    # Fallback: any decimal number
    match = re.search(r"\b([0-9]+\.[0-9]{2})\b", text)
    if match:
        return match.group(1)

    return None


def _extract_bill_details(pdf_path: Path) -> tuple[str, Path]:
    """Extract amount and first page from PDF.

    Returns:
        Tuple of (amount, first_page_path)
    """
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(str(pdf_path))
    if not reader.pages:
        raise RuntimeError(f"PDF has no pages: {pdf_path}")

    first_page = reader.pages[0]
    text = first_page.extract_text() or ""

    amount = _extract_amount_from_text(text)
    if not amount:
        raise RuntimeError(f"Could not extract amount from {pdf_path}")

    # Save first page
    first_page_path = pdf_path.with_name(f"{pdf_path.stem}_page1.pdf")
    writer = PdfWriter()
    writer.add_page(first_page)

    with first_page_path.open("wb") as f:
        writer.write(f)

    return amount, first_page_path


# ==================== Date Helpers ====================


def _previous_month_slug(today: date | None = None) -> str:
    """Return previous month in YYYY-MM format."""
    today = today or date.today()
    first_of_month = today.replace(day=1)
    last_month = first_of_month - timedelta(days=1)
    return last_month.strftime("%Y-%m")


def _report_name_for_month(month_slug: str) -> str:
    """Format Concur report name from month slug."""
    year, month = map(int, month_slug.split("-"))
    month_label = date(year, month, 1).strftime("%b")
    return f"Remote Worker Expense ({month_label})"


def _today_us_date(today: date | None = None) -> str:
    """Return today's date as MM/DD/YYYY."""
    return (today or date.today()).strftime("%m/%d/%Y")


# ==================== Tool Registration ====================


def register_tools(server: FastMCP) -> int:
    """Register concur tools with the MCP server."""
    registry = ToolRegistry(server)
    config = load_concur_config()

    @registry.tool()
    async def concur_get_gomo_credentials() -> list[TextContent]:
        """
        Get GOMO login credentials from Bitwarden or pass.

        Tries Bitwarden first (requires BW_SESSION), falls back to GNU pass.

        Returns:
            Username and masked password confirmation.
        """
        gomo_config = config.get("gomo", {})
        bw_item = gomo_config.get("bitwarden_item", "gomo.ie")
        pass_path = gomo_config.get("pass_path", "gomo.ie/dmz.oneill@gmail.com")

        try:
            # Try Bitwarden first
            username, password = _get_bitwarden_password(bw_item)
            return [
                TextContent(
                    type="text",
                    text=f"✅ GOMO credentials loaded from Bitwarden\n"
                    f"**Username:** {username}\n"
                    f"**Password:** {'*' * 8} (loaded)",
                )
            ]
        except Exception as bw_error:
            logger.warning(f"Bitwarden failed: {bw_error}")

            try:
                # Fallback to pass
                password = _get_pass_password(pass_path)
                username = pass_path.split("/")[-1] if "/" in pass_path else "unknown"
                return [
                    TextContent(
                        type="text",
                        text=f"✅ GOMO credentials loaded from pass\n"
                        f"**Username:** {username}\n"
                        f"**Password:** {'*' * 8} (loaded)",
                    )
                ]
            except Exception as pass_error:
                return [
                    TextContent(
                        type="text",
                        text=f"❌ Failed to load GOMO credentials\n\n"
                        f"**Bitwarden error:** {bw_error}\n"
                        f"**Pass error:** {pass_error}\n\n"
                        f"**Fix:** Run `export BW_SESSION=$(bw unlock --raw)` or ensure pass entry exists",
                    )
                ]

    @registry.tool()
    async def concur_get_sso_credentials() -> list[TextContent]:
        """
        Get Red Hat SSO credentials for Concur from redhatter service.

        Requires the redhatter service to be running on localhost:8009.

        Returns:
            Username and masked password confirmation.
        """
        try:
            token = _get_redhatter_token()
            username, password = _fetch_concur_credentials(token)

            return [
                TextContent(
                    type="text",
                    text=f"✅ Concur SSO credentials loaded\n"
                    f"**Username:** {username}\n"
                    f"**Password:** {'*' * 8} (loaded)",
                )
            ]
        except Exception as e:
            return [
                TextContent(
                    type="text",
                    text=f"❌ Failed to load Concur credentials\n\n"
                    f"**Error:** {e}\n\n"
                    f"**Fix:** Ensure redhatter service is running on localhost:8009",
                )
            ]

    @registry.tool()
    async def concur_get_expense_params(
        month: str = "",
    ) -> list[TextContent]:
        """
        Get expense parameters for the current or specified month.

        Args:
            month: Month in YYYY-MM format (default: previous month)

        Returns:
            Report name, date, and file paths for the expense.
        """
        month_slug = month or _previous_month_slug()
        report_name = _report_name_for_month(month_slug)
        report_date = _today_us_date()

        downloads_dir = Path(config.get("downloads_dir", str(DOWNLOADS_DIR)))
        full_pdf = downloads_dir / f"{month_slug}.pdf"
        first_page_pdf = downloads_dir / f"{month_slug}_page1.pdf"

        # Check if files exist
        full_exists = full_pdf.exists()
        first_exists = first_page_pdf.exists()

        amount = None
        if first_exists:
            try:
                from pypdf import PdfReader

                reader = PdfReader(str(first_page_pdf))
                if reader.pages:
                    text = reader.pages[0].extract_text() or ""
                    amount = _extract_amount_from_text(text)
            except Exception:
                pass

        return [
            TextContent(
                type="text",
                text=f"## Expense Parameters for {month_slug}\n\n"
                f"**Report Name:** {report_name}\n"
                f"**Report Date:** {report_date}\n"
                f"**Month:** {month_slug}\n\n"
                f"### Files\n"
                f"- **Full PDF:** `{full_pdf}` {'✅' if full_exists else '❌ not found'}\n"
                f"- **First Page:** `{first_page_pdf}` {'✅' if first_exists else '❌ not found'}\n"
                f"- **Amount:** €{amount or 'unknown'}\n\n"
                f"### Concur Settings\n"
                f"- **Expense Type:** {config.get('concur', {}).get('expense_type', 'Remote Worker Expense')}\n"
                f"- **Payment Type:** {config.get('concur', {}).get('payment_type', 'Cash')}\n"
                f"- **Max USD:** ${config.get('concur', {}).get('max_usd_amount', 40.00)}",
            )
        ]

    @registry.tool()
    async def concur_extract_bill_amount(
        pdf_path: str,
    ) -> list[TextContent]:
        """
        Extract the billing amount from a GOMO PDF bill.

        Args:
            pdf_path: Path to the PDF file

        Returns:
            Extracted amount and first page path.
        """
        pdf_file = Path(pdf_path)

        if not pdf_file.exists():
            return [TextContent(type="text", text=f"❌ PDF not found: {pdf_path}")]

        try:
            amount, first_page = _extract_bill_details(pdf_file)

            return [
                TextContent(
                    type="text",
                    text=f"✅ Bill details extracted\n\n" f"**Amount:** €{amount}\n" f"**First Page:** `{first_page}`",
                )
            ]
        except Exception as e:
            return [TextContent(type="text", text=f"❌ Failed to extract bill details\n\n" f"**Error:** {e}")]

    @registry.tool()
    async def concur_check_receipt_status(
        month: str = "",
    ) -> list[TextContent]:
        """
        Check if receipt files exist for the specified month.

        Args:
            month: Month in YYYY-MM format (default: previous month)

        Returns:
            Status of receipt files and whether download is needed.
        """
        month_slug = month or _previous_month_slug()
        downloads_dir = Path(config.get("downloads_dir", str(DOWNLOADS_DIR)))

        full_pdf = downloads_dir / f"{month_slug}.pdf"
        first_page_pdf = downloads_dir / f"{month_slug}_page1.pdf"

        full_exists = full_pdf.exists()
        first_exists = first_page_pdf.exists()

        if first_exists:
            # Try to read amount
            try:
                from pypdf import PdfReader

                reader = PdfReader(str(first_page_pdf))
                if reader.pages:
                    text = reader.pages[0].extract_text() or ""
                    amount = _extract_amount_from_text(text)

                    if amount:
                        return [
                            TextContent(
                                type="text",
                                text=f"✅ Receipt ready for {month_slug}\n\n"
                                f"**Amount:** €{amount}\n"
                                f"**File:** `{first_page_pdf}`\n\n"
                                f"*Ready to submit expense*",
                            )
                        ]
            except ImportError:
                # pypdf not installed - file exists but can't read amount
                return [
                    TextContent(
                        type="text",
                        text=f"✅ Receipt file exists for {month_slug}\n\n"
                        f"**File:** `{first_page_pdf}`\n"
                        f"**Amount:** *(install pypdf to extract)*\n\n"
                        f"*Receipt file ready, run `pip install pypdf` for amount extraction*",
                    )
                ]
            except Exception as e:
                logger.warning(f"Error reading PDF: {e}")

        return [
            TextContent(
                type="text",
                text=f"❌ Receipt not ready for {month_slug}\n\n"
                f"**Full PDF:** {'✅' if full_exists else '❌'} `{full_pdf}`\n"
                f"**First Page:** {'✅' if first_exists else '❌'} `{first_page_pdf}`\n\n"
                f"*Need to download bill from GOMO*",
            )
        ]

    @registry.tool()
    async def concur_download_gomo_bill(
        skip_concur: bool = True,
        headless: bool = True,
    ) -> list[TextContent]:
        """
        Download the latest GOMO bill using the automation script.

        This runs the gomo_to_concur.py script from ~/src/aa-concur to:
        1. Log into GOMO
        2. Download the latest bill PDF
        3. Extract the first page with billing amount

        Args:
            skip_concur: Skip Concur submission, just download bill (default: True)
            headless: Run browser in headless mode (default: True)

        Returns:
            Download result with file paths and amount.
        """
        if not GOMO_SCRIPT.exists():
            return [
                TextContent(
                    type="text",
                    text=f"❌ GOMO script not found at `{GOMO_SCRIPT}`\n\n"
                    f"Expected: `~/src/aa-concur/scripts/gomo_to_concur.py`",
                )
            ]

        # Build command
        cmd = [
            sys.executable,  # Use current Python interpreter
            str(GOMO_SCRIPT),
            "--download-dir",
            str(DOWNLOADS_DIR),
        ]

        if skip_concur:
            cmd.append("--skip-concur")

        if headless:
            pass  # Headless is default
        else:
            cmd.append("--headed")

        logger.info(f"Running GOMO download: {' '.join(cmd)}")

        try:
            # Run the script with pipenv, ignoring any active virtualenv
            env = os.environ.copy()
            env["PIPENV_IGNORE_VIRTUALENVS"] = "1"
            # Remove VIRTUAL_ENV to avoid pipenv confusion
            env.pop("VIRTUAL_ENV", None)

            cmd = ["pipenv", "run", "python", str(GOMO_SCRIPT), "--download-dir", str(DOWNLOADS_DIR)]
            if skip_concur:
                cmd.append("--skip-concur")
            if not headless:
                cmd.append("--headed")

            logger.info(f"Running: {' '.join(cmd)} in {AA_CONCUR_DIR}")

            result = subprocess.run(
                cmd,
                cwd=str(AA_CONCUR_DIR),
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
                env=env,
            )

            if result.returncode == 0:
                # Check what was downloaded
                month_slug = _previous_month_slug()
                full_pdf = DOWNLOADS_DIR / f"{month_slug}.pdf"
                first_page = DOWNLOADS_DIR / f"{month_slug}_page1.pdf"

                amount = None
                if first_page.exists():
                    try:
                        from pypdf import PdfReader

                        reader = PdfReader(str(first_page))
                        if reader.pages:
                            text = reader.pages[0].extract_text() or ""
                            amount = _extract_amount_from_text(text)
                    except Exception:
                        pass

                return [
                    TextContent(
                        type="text",
                        text=f"✅ GOMO bill downloaded successfully\n\n"
                        f"**Month:** {month_slug}\n"
                        f"**Amount:** €{amount or 'unknown'}\n"
                        f"**Full PDF:** `{full_pdf}`\n"
                        f"**First Page:** `{first_page}`\n\n"
                        f"```\n{result.stdout[-500:] if result.stdout else 'No output'}\n```",
                    )
                ]
            else:
                return [
                    TextContent(
                        type="text",
                        text=f"❌ GOMO download failed (exit code {result.returncode})\n\n"
                        f"**stdout:**\n```\n{result.stdout[-500:] if result.stdout else 'None'}\n```\n\n"
                        f"**stderr:**\n```\n{result.stderr[-500:] if result.stderr else 'None'}\n```",
                    )
                ]

        except subprocess.TimeoutExpired:
            return [
                TextContent(
                    type="text",
                    text="❌ GOMO download timed out after 5 minutes\n\n"
                    "Try running manually: `cd ~/src/aa-concur && make run-gomo`",
                )
            ]
        except Exception as e:
            return [
                TextContent(
                    type="text",
                    text=f"❌ GOMO download error: {e}\n\n"
                    f"Try running manually: `cd ~/src/aa-concur && make run-gomo-headless`",
                )
            ]

    @registry.tool()
    async def concur_run_full_automation(
        headless: bool = True,
    ) -> list[TextContent]:
        """
        Run the full GOMO + Concur automation script.

        This runs the complete workflow:
        1. Log into GOMO and download bill
        2. Log into Concur via Red Hat SSO
        3. Create expense report
        4. Upload receipt and submit

        Args:
            headless: Run browser in headless mode (default: True)

        Returns:
            Automation result.
        """
        if not GOMO_SCRIPT.exists():
            return [TextContent(type="text", text=f"❌ Script not found at `{GOMO_SCRIPT}`")]

        logger.info("Running full GOMO + Concur automation")

        try:
            # Build environment that forces pipenv to use its own venv
            env = os.environ.copy()
            env["PIPENV_IGNORE_VIRTUALENVS"] = "1"
            env.pop("VIRTUAL_ENV", None)

            cmd = ["pipenv", "run", "python", str(GOMO_SCRIPT), "--download-dir", str(DOWNLOADS_DIR)]

            if not headless:
                cmd.append("--headed")

            logger.info(f"Running: {' '.join(cmd)} in {AA_CONCUR_DIR}")

            result = subprocess.run(
                cmd,
                cwd=str(AA_CONCUR_DIR),
                capture_output=True,
                text=True,
                timeout=600,  # 10 minute timeout for full automation
                env=env,
            )

            if result.returncode == 0:
                return [
                    TextContent(
                        type="text",
                        text=f"✅ Full automation completed successfully!\n\n"
                        f"**Output:**\n```\n{result.stdout[-1000:] if result.stdout else 'No output'}\n```",
                    )
                ]
            else:
                return [
                    TextContent(
                        type="text",
                        text=f"❌ Automation failed (exit code {result.returncode})\n\n"
                        f"**stdout:**\n```\n{result.stdout[-500:] if result.stdout else 'None'}\n```\n\n"
                        f"**stderr:**\n```\n{result.stderr[-500:] if result.stderr else 'None'}\n```",
                    )
                ]

        except subprocess.TimeoutExpired:
            return [TextContent(type="text", text="❌ Automation timed out after 10 minutes")]
        except Exception as e:
            return [TextContent(type="text", text=f"❌ Automation error: {e}")]

    @registry.tool()
    async def concur_cleanup_unsubmitted(
        headless: bool = True,
    ) -> list[TextContent]:
        """
        Delete all unsubmitted expense reports from Concur.

        This cleans up failed/incomplete expense reports that were
        created during testing or failed automation runs.

        Args:
            headless: Run browser in headless mode (default: True)

        Returns:
            Cleanup result with number of reports deleted.
        """
        if not GOMO_SCRIPT.exists():
            return [TextContent(type="text", text=f"❌ Script not found at `{GOMO_SCRIPT}`")]

        logger.info("Running Concur cleanup - deleting unsubmitted expense reports")

        try:
            env = os.environ.copy()
            env["PIPENV_IGNORE_VIRTUALENVS"] = "1"
            env.pop("VIRTUAL_ENV", None)

            cmd = ["pipenv", "run", "python", str(GOMO_SCRIPT), "--cleanup"]

            if not headless:
                cmd.append("--headed")

            logger.info(f"Running: {' '.join(cmd)} in {AA_CONCUR_DIR}")

            result = subprocess.run(
                cmd,
                cwd=str(AA_CONCUR_DIR),
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
                env=env,
            )

            if result.returncode == 0:
                # Parse output to get deletion count
                output = result.stdout + result.stderr
                import re

                match = re.search(r"deleted (\d+) expense reports", output, re.I)
                count = match.group(1) if match else "unknown"

                return [
                    TextContent(
                        type="text",
                        text=f"✅ Cleanup completed\n\n"
                        f"**Deleted:** {count} unsubmitted expense reports\n\n"
                        f"**Output:**\n```\n{output[-500:] if output else 'No output'}\n```",
                    )
                ]
            else:
                return [
                    TextContent(
                        type="text",
                        text=f"❌ Cleanup failed (exit code {result.returncode})\n\n"
                        f"**stdout:**\n```\n{result.stdout[-500:] if result.stdout else 'None'}\n```\n\n"
                        f"**stderr:**\n```\n{result.stderr[-500:] if result.stderr else 'None'}\n```",
                    )
                ]

        except subprocess.TimeoutExpired:
            return [TextContent(type="text", text="❌ Cleanup timed out after 5 minutes")]
        except Exception as e:
            return [TextContent(type="text", text=f"❌ Cleanup error: {e}")]

    @registry.tool()
    async def concur_workflow_status() -> list[TextContent]:
        """
        Get the current status of the expense submission workflow.

        Checks:
        - Credential availability (GOMO, Concur SSO)
        - Receipt status for current month
        - Required services

        Returns:
            Comprehensive workflow status and next steps.
        """
        month_slug = _previous_month_slug()
        issues = []
        ready = []

        # Check GOMO credentials
        gomo_config = config.get("gomo", {})
        bw_item = gomo_config.get("bitwarden_item", "gomo.ie")
        try:
            _get_bitwarden_password(bw_item)
            ready.append("✅ GOMO credentials (Bitwarden)")
        except Exception:
            try:
                pass_path = gomo_config.get("pass_path", "gomo.ie/dmz.oneill@gmail.com")
                _get_pass_password(pass_path)
                ready.append("✅ GOMO credentials (pass)")
            except Exception:
                issues.append("❌ GOMO credentials not available")

        # Check Concur credentials
        try:
            token = _get_redhatter_token()
            _fetch_concur_credentials(token)
            ready.append("✅ Concur SSO credentials")
        except Exception as e:
            issues.append(f"❌ Concur credentials: {e}")

        # Check receipt
        downloads_dir = Path(config.get("downloads_dir", str(DOWNLOADS_DIR)))
        first_page_pdf = downloads_dir / f"{month_slug}_page1.pdf"

        if first_page_pdf.exists():
            try:
                from pypdf import PdfReader

                reader = PdfReader(str(first_page_pdf))
                if reader.pages:
                    text = reader.pages[0].extract_text() or ""
                    amount = _extract_amount_from_text(text)
                    ready.append(f"✅ Receipt for {month_slug} (€{amount})")
            except Exception:
                ready.append(f"✅ Receipt file exists for {month_slug}")
        else:
            issues.append(f"❌ Receipt not downloaded for {month_slug}")

        # Build status report
        status = "🟢 Ready" if not issues else "🟡 Issues Found"

        lines = [
            f"## Expense Workflow Status: {status}\n",
            f"**Month:** {month_slug}",
            f"**Report Name:** {_report_name_for_month(month_slug)}\n",
            "### Checklist\n",
        ]

        for item in ready:
            lines.append(item)
        for item in issues:
            lines.append(item)

        if issues:
            lines.append("\n### Next Steps\n")
            if "GOMO credentials" in str(issues):
                lines.append("1. Run: `export BW_SESSION=$(bw unlock --raw)`")
            if "Concur credentials" in str(issues):
                lines.append("2. Start redhatter service on localhost:8009")
            if "Receipt" in str(issues):
                lines.append("3. Download GOMO bill using browser automation")
        else:
            lines.append("\n### Ready to Submit\n")
            lines.append("Run: `skill_run('submit_expense')`")

        return [TextContent(type="text", text="\n".join(lines))]

    return registry.count


