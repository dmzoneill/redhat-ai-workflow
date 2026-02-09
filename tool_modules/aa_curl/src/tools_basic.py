"""cURL tool definitions - HTTP client and API testing.

Provides:
Request tools:
- curl_get: HTTP GET request
- curl_post: HTTP POST request
- curl_put: HTTP PUT request
- curl_delete: HTTP DELETE request
- curl_patch: HTTP PATCH request
- curl_head: HTTP HEAD request

Utility tools:
- curl_download: Download file
- curl_upload: Upload file
- curl_headers: Get response headers only
- curl_follow: Follow redirects and show final URL

Debug tools:
- curl_verbose: Verbose request with timing
- curl_timing: Show request timing breakdown
"""

import json
import logging

from fastmcp import FastMCP

from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT

from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry
from server.utils import run_cmd, truncate_output

logger = logging.getLogger(__name__)


def _build_curl_cmd(
    url: str,
    method: str = "GET",
    headers: dict | None = None,
    data: str = "",
    json_data: str = "",
    auth: str = "",
    timeout_secs: int = 30,
    insecure: bool = False,
    follow_redirects: bool = True,
) -> list:
    """Build curl command."""
    cmd = ["curl", "-s", "-S"]

    if method != "GET":
        cmd.extend(["-X", method])

    if follow_redirects:
        cmd.append("-L")

    if insecure:
        cmd.append("-k")

    cmd.extend(["--max-time", str(timeout_secs)])

    if headers:
        for key, value in headers.items():
            cmd.extend(["-H", f"{key}: {value}"])

    if json_data:
        cmd.extend(["-H", "Content-Type: application/json"])
        cmd.extend(["-d", json_data])
    elif data:
        cmd.extend(["-d", data])

    if auth:
        cmd.extend(["-u", auth])

    cmd.append(url)
    return cmd


@auto_heal()
async def _curl_get_impl(
    url: str,
    headers: dict | None = None,
    auth: str = "",
    timeout_secs: int = 30,
    insecure: bool = False,
) -> str:
    """HTTP GET request."""
    cmd = _build_curl_cmd(url, "GET", headers, "", "", auth, timeout_secs, insecure)

    success, output = await run_cmd(cmd, timeout=timeout_secs + 10)
    if success:
        # Try to detect and format JSON
        try:
            parsed = json.loads(output)
            formatted = json.dumps(parsed, indent=2)
            return f"## GET {url}\n\n```json\n{truncate_output(formatted, max_length=5000, mode='head')}\n```"
        except json.JSONDecodeError:
            return f"## GET {url}\n\n```\n{truncate_output(output, max_length=5000, mode='head')}\n```"
    return f"❌ Request failed: {output}"


@auto_heal()
async def _curl_post_impl(
    url: str,
    data: str = "",
    json_data: str = "",
    headers: dict | None = None,
    auth: str = "",
    timeout_secs: int = 30,
    insecure: bool = False,
) -> str:
    """HTTP POST request."""
    cmd = _build_curl_cmd(
        url, "POST", headers, data, json_data, auth, timeout_secs, insecure
    )

    success, output = await run_cmd(cmd, timeout=timeout_secs + 10)
    if success:
        try:
            parsed = json.loads(output)
            formatted = json.dumps(parsed, indent=2)
            return f"## POST {url}\n\n```json\n{truncate_output(formatted, max_length=5000, mode='head')}\n```"
        except json.JSONDecodeError:
            return f"## POST {url}\n\n```\n{truncate_output(output, max_length=5000, mode='head')}\n```"
    return f"❌ Request failed: {output}"


@auto_heal()
async def _curl_put_impl(
    url: str,
    data: str = "",
    json_data: str = "",
    headers: dict | None = None,
    auth: str = "",
    timeout_secs: int = 30,
    insecure: bool = False,
) -> str:
    """HTTP PUT request."""
    cmd = _build_curl_cmd(
        url, "PUT", headers, data, json_data, auth, timeout_secs, insecure
    )

    success, output = await run_cmd(cmd, timeout=timeout_secs + 10)
    if success:
        try:
            parsed = json.loads(output)
            formatted = json.dumps(parsed, indent=2)
            return f"## PUT {url}\n\n```json\n{truncate_output(formatted, max_length=5000, mode='head')}\n```"
        except json.JSONDecodeError:
            return f"## PUT {url}\n\n```\n{truncate_output(output, max_length=5000, mode='head')}\n```"
    return f"❌ Request failed: {output}"


@auto_heal()
async def _curl_delete_impl(
    url: str,
    headers: dict | None = None,
    auth: str = "",
    timeout_secs: int = 30,
    insecure: bool = False,
) -> str:
    """HTTP DELETE request."""
    cmd = _build_curl_cmd(url, "DELETE", headers, "", "", auth, timeout_secs, insecure)

    success, output = await run_cmd(cmd, timeout=timeout_secs + 10)
    if success:
        return f"✅ DELETE {url}\n\n```\n{output}\n```"
    return f"❌ Request failed: {output}"


@auto_heal()
async def _curl_patch_impl(
    url: str,
    data: str = "",
    json_data: str = "",
    headers: dict | None = None,
    auth: str = "",
    timeout_secs: int = 30,
    insecure: bool = False,
) -> str:
    """HTTP PATCH request."""
    cmd = _build_curl_cmd(
        url, "PATCH", headers, data, json_data, auth, timeout_secs, insecure
    )

    success, output = await run_cmd(cmd, timeout=timeout_secs + 10)
    if success:
        try:
            parsed = json.loads(output)
            formatted = json.dumps(parsed, indent=2)
            return f"## PATCH {url}\n\n```json\n{truncate_output(formatted, max_length=5000, mode='head')}\n```"
        except json.JSONDecodeError:
            return f"## PATCH {url}\n\n```\n{truncate_output(output, max_length=5000, mode='head')}\n```"
    return f"❌ Request failed: {output}"


@auto_heal()
async def _curl_head_impl(
    url: str,
    headers: dict | None = None,
    auth: str = "",
    timeout_secs: int = 30,
    insecure: bool = False,
) -> str:
    """HTTP HEAD request."""
    cmd = ["curl", "-s", "-S", "-I", "-L"]
    if insecure:
        cmd.append("-k")
    cmd.extend(["--max-time", str(timeout_secs)])
    if headers:
        for key, value in headers.items():
            cmd.extend(["-H", f"{key}: {value}"])
    if auth:
        cmd.extend(["-u", auth])
    cmd.append(url)

    success, output = await run_cmd(cmd, timeout=timeout_secs + 10)
    if success:
        return f"## HEAD {url}\n\n```\n{output}\n```"
    return f"❌ Request failed: {output}"


@auto_heal()
async def _curl_download_impl(
    url: str,
    output_file: str,
    auth: str = "",
    timeout_secs: int = 300,
    insecure: bool = False,
) -> str:
    """Download file."""
    cmd = ["curl", "-s", "-S", "-L", "-o", output_file]
    if insecure:
        cmd.append("-k")
    cmd.extend(["--max-time", str(timeout_secs)])
    if auth:
        cmd.extend(["-u", auth])
    cmd.append(url)

    success, output = await run_cmd(cmd, timeout=timeout_secs + 10)
    if success:
        return f"✅ Downloaded to {output_file}"
    return f"❌ Download failed: {output}"


@auto_heal()
async def _curl_upload_impl(
    url: str,
    file_path: str,
    field_name: str = "file",
    auth: str = "",
    timeout_secs: int = 300,
    insecure: bool = False,
) -> str:
    """Upload file."""
    cmd = ["curl", "-s", "-S", "-L", "-X", "POST"]
    cmd.extend(["-F", f"{field_name}=@{file_path}"])
    if insecure:
        cmd.append("-k")
    cmd.extend(["--max-time", str(timeout_secs)])
    if auth:
        cmd.extend(["-u", auth])
    cmd.append(url)

    success, output = await run_cmd(cmd, timeout=timeout_secs + 10)
    if success:
        return f"✅ Uploaded {file_path}\n\n```\n{output}\n```"
    return f"❌ Upload failed: {output}"


@auto_heal()
async def _curl_headers_impl(
    url: str,
    timeout_secs: int = 30,
    insecure: bool = False,
) -> str:
    """Get response headers only."""
    cmd = ["curl", "-s", "-S", "-I", "-L"]
    if insecure:
        cmd.append("-k")
    cmd.extend(["--max-time", str(timeout_secs)])
    cmd.append(url)

    success, output = await run_cmd(cmd, timeout=timeout_secs + 10)
    if success:
        return f"## Response Headers: {url}\n\n```\n{output}\n```"
    return f"❌ Request failed: {output}"


@auto_heal()
async def _curl_timing_impl(
    url: str,
    timeout_secs: int = 30,
    insecure: bool = False,
) -> str:
    """Show request timing breakdown."""
    timing_format = (
        "DNS Lookup: %{time_namelookup}s\\n"
        "TCP Connect: %{time_connect}s\\n"
        "TLS Handshake: %{time_appconnect}s\\n"
        "Time to First Byte: %{time_starttransfer}s\\n"
        "Total Time: %{time_total}s\\n"
        "Download Size: %{size_download} bytes\\n"
        "HTTP Code: %{http_code}"
    )
    cmd = ["curl", "-s", "-S", "-o", "/dev/null", "-w", timing_format]
    if insecure:
        cmd.append("-k")
    cmd.extend(["--max-time", str(timeout_secs)])
    cmd.append(url)

    success, output = await run_cmd(cmd, timeout=timeout_secs + 10)
    if success:
        return f"## Request Timing: {url}\n\n```\n{output}\n```"
    return f"❌ Request failed: {output}"


def register_tools(server: FastMCP) -> int:
    """Register curl tools with the MCP server."""
    registry = ToolRegistry(server)

    @auto_heal()
    @registry.tool()
    async def curl_get(
        url: str,
        auth: str = "",
        insecure: bool = False,
    ) -> str:
        """HTTP GET request.

        Args:
            url: Request URL
            auth: Basic auth (user:password)
            insecure: Skip SSL verification
        """
        return await _curl_get_impl(url, None, auth, 30, insecure)

    @auto_heal()
    @registry.tool()
    async def curl_post(
        url: str,
        json_data: str = "",
        data: str = "",
        auth: str = "",
        insecure: bool = False,
    ) -> str:
        """HTTP POST request.

        Args:
            url: Request URL
            json_data: JSON body
            data: Form data
            auth: Basic auth (user:password)
            insecure: Skip SSL verification
        """
        return await _curl_post_impl(url, data, json_data, None, auth, 30, insecure)

    @auto_heal()
    @registry.tool()
    async def curl_put(
        url: str,
        json_data: str = "",
        data: str = "",
        auth: str = "",
        insecure: bool = False,
    ) -> str:
        """HTTP PUT request.

        Args:
            url: Request URL
            json_data: JSON body
            data: Form data
            auth: Basic auth (user:password)
            insecure: Skip SSL verification
        """
        return await _curl_put_impl(url, data, json_data, None, auth, 30, insecure)

    @auto_heal()
    @registry.tool()
    async def curl_delete(
        url: str,
        auth: str = "",
        insecure: bool = False,
    ) -> str:
        """HTTP DELETE request.

        Args:
            url: Request URL
            auth: Basic auth (user:password)
            insecure: Skip SSL verification
        """
        return await _curl_delete_impl(url, None, auth, 30, insecure)

    @auto_heal()
    @registry.tool()
    async def curl_patch(
        url: str,
        json_data: str = "",
        data: str = "",
        auth: str = "",
        insecure: bool = False,
    ) -> str:
        """HTTP PATCH request.

        Args:
            url: Request URL
            json_data: JSON body
            data: Form data
            auth: Basic auth (user:password)
            insecure: Skip SSL verification
        """
        return await _curl_patch_impl(url, data, json_data, None, auth, 30, insecure)

    @auto_heal()
    @registry.tool()
    async def curl_head(url: str, insecure: bool = False) -> str:
        """HTTP HEAD request.

        Args:
            url: Request URL
            insecure: Skip SSL verification
        """
        return await _curl_head_impl(url, None, "", 30, insecure)

    @auto_heal()
    @registry.tool()
    async def curl_download(
        url: str,
        output_file: str,
        auth: str = "",
        insecure: bool = False,
    ) -> str:
        """Download file.

        Args:
            url: File URL
            output_file: Output file path
            auth: Basic auth (user:password)
            insecure: Skip SSL verification
        """
        return await _curl_download_impl(url, output_file, auth, 300, insecure)

    @auto_heal()
    @registry.tool()
    async def curl_upload(
        url: str,
        file_path: str,
        field_name: str = "file",
        auth: str = "",
        insecure: bool = False,
    ) -> str:
        """Upload file.

        Args:
            url: Upload URL
            file_path: File to upload
            field_name: Form field name
            auth: Basic auth (user:password)
            insecure: Skip SSL verification
        """
        return await _curl_upload_impl(url, file_path, field_name, auth, 300, insecure)

    @auto_heal()
    @registry.tool()
    async def curl_headers(url: str, insecure: bool = False) -> str:
        """Get response headers only.

        Args:
            url: Request URL
            insecure: Skip SSL verification
        """
        return await _curl_headers_impl(url, 30, insecure)

    @auto_heal()
    @registry.tool()
    async def curl_timing(url: str, insecure: bool = False) -> str:
        """Show request timing breakdown.

        Args:
            url: Request URL
            insecure: Skip SSL verification
        """
        return await _curl_timing_impl(url, 30, insecure)

    return registry.count
