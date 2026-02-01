"""OpenSSL tool definitions - Cryptography and certificate management.

Provides:
Certificate tools:
- openssl_x509_info: View certificate information
- openssl_x509_verify: Verify certificate chain
- openssl_req_new: Generate certificate signing request
- openssl_genrsa: Generate RSA private key
- openssl_genpkey: Generate private key (various algorithms)

Connection tools:
- openssl_s_client: Test SSL/TLS connection
- openssl_s_client_cert: Get server certificate

Encryption tools:
- openssl_enc_encrypt: Encrypt file
- openssl_enc_decrypt: Decrypt file
- openssl_dgst: Generate hash/digest

Utility tools:
- openssl_rand: Generate random data
- openssl_version: Show OpenSSL version
- openssl_ciphers: List available ciphers
"""

import logging

from fastmcp import FastMCP

from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT

from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry
from server.utils import run_cmd, truncate_output

logger = logging.getLogger(__name__)


@auto_heal()
async def _openssl_x509_info_impl(
    cert_file: str = "",
    cert_text: str = "",
    show_dates: bool = True,
    show_subject: bool = True,
    show_issuer: bool = True,
) -> str:
    """View certificate information."""
    if cert_file:
        cmd = ["openssl", "x509", "-in", cert_file, "-noout"]
    elif cert_text:
        cmd = ["openssl", "x509", "-noout"]
    else:
        return "❌ Provide either cert_file or cert_text"

    if show_dates:
        cmd.append("-dates")
    if show_subject:
        cmd.append("-subject")
    if show_issuer:
        cmd.append("-issuer")

    if cert_text:
        success, output = await run_cmd(cmd, timeout=30, input_data=cert_text)
    else:
        success, output = await run_cmd(cmd, timeout=30)

    if success:
        return f"## Certificate Info\n\n```\n{output}\n```"
    return f"❌ Failed to read certificate: {output}"


@auto_heal()
async def _openssl_x509_text_impl(cert_file: str) -> str:
    """View full certificate details."""
    cmd = ["openssl", "x509", "-in", cert_file, "-text", "-noout"]

    success, output = await run_cmd(cmd, timeout=30)
    if success:
        return f"## Certificate Details\n\n```\n{truncate_output(output, max_length=5000, mode='head')}\n```"
    return f"❌ Failed to read certificate: {output}"


@auto_heal()
async def _openssl_x509_verify_impl(
    cert_file: str,
    ca_file: str = "",
    ca_path: str = "",
) -> str:
    """Verify certificate chain."""
    cmd = ["openssl", "verify"]
    if ca_file:
        cmd.extend(["-CAfile", ca_file])
    if ca_path:
        cmd.extend(["-CApath", ca_path])
    cmd.append(cert_file)

    success, output = await run_cmd(cmd, timeout=30)
    if success and "OK" in output:
        return f"✅ Certificate verified: {output}"
    return f"❌ Verification failed: {output}"


@auto_heal()
async def _openssl_req_new_impl(
    key_file: str,
    out_file: str,
    subject: str,
    days: int = 365,
) -> str:
    """Generate certificate signing request."""
    cmd = [
        "openssl",
        "req",
        "-new",
        "-key",
        key_file,
        "-out",
        out_file,
        "-subj",
        subject,
        "-days",
        str(days),
    ]

    success, output = await run_cmd(cmd, timeout=30)
    if success:
        return f"✅ CSR generated: {out_file}"
    return f"❌ Failed to generate CSR: {output}"


@auto_heal()
async def _openssl_genrsa_impl(
    out_file: str,
    bits: int = 4096,
) -> str:
    """Generate RSA private key."""
    cmd = ["openssl", "genrsa", "-out", out_file, str(bits)]

    success, output = await run_cmd(cmd, timeout=60)
    if success:
        return f"✅ RSA key generated: {out_file} ({bits} bits)"
    return f"❌ Failed to generate key: {output}"


@auto_heal()
async def _openssl_genpkey_impl(
    out_file: str,
    algorithm: str = "RSA",
    bits: int = 4096,
) -> str:
    """Generate private key."""
    cmd = ["openssl", "genpkey", "-algorithm", algorithm, "-out", out_file]
    if algorithm.upper() == "RSA":
        cmd.extend(["-pkeyopt", f"rsa_keygen_bits:{bits}"])

    success, output = await run_cmd(cmd, timeout=60)
    if success:
        return f"✅ {algorithm} key generated: {out_file}"
    return f"❌ Failed to generate key: {output}"


@auto_heal()
async def _openssl_s_client_impl(
    host: str,
    port: int = 443,
    servername: str = "",
    show_certs: bool = False,
) -> str:
    """Test SSL/TLS connection."""
    cmd = ["openssl", "s_client", "-connect", f"{host}:{port}"]
    if servername:
        cmd.extend(["-servername", servername])
    elif host:
        cmd.extend(["-servername", host])
    if show_certs:
        cmd.append("-showcerts")

    # Send empty input to close connection
    success, output = await run_cmd(cmd, timeout=30, input_data="")
    if success:
        return f"## SSL Connection: {host}:{port}\n\n```\n{truncate_output(output, max_length=3000, mode='head')}\n```"
    return f"❌ Connection failed: {output}"


@auto_heal()
async def _openssl_s_client_cert_impl(
    host: str,
    port: int = 443,
) -> str:
    """Get server certificate."""
    cmd = [
        "openssl",
        "s_client",
        "-connect",
        f"{host}:{port}",
        "-servername",
        host,
    ]

    success, output = await run_cmd(cmd, timeout=30, input_data="")
    if not success:
        return f"❌ Connection failed: {output}"

    # Extract certificate
    lines = output.split("\n")
    cert_lines = []
    in_cert = False
    for line in lines:
        if "-----BEGIN CERTIFICATE-----" in line:
            in_cert = True
        if in_cert:
            cert_lines.append(line)
        if "-----END CERTIFICATE-----" in line:
            break

    if cert_lines:
        cert = "\n".join(cert_lines)
        return f"## Server Certificate: {host}\n\n```\n{cert}\n```"
    return "❌ No certificate found in response"


@auto_heal()
async def _openssl_enc_encrypt_impl(
    in_file: str,
    out_file: str,
    cipher: str = "aes-256-cbc",
    password: str = "",
) -> str:
    """Encrypt file."""
    cmd = ["openssl", "enc", f"-{cipher}", "-salt", "-in", in_file, "-out", out_file]
    if password:
        cmd.extend(["-pass", f"pass:{password}"])
    else:
        cmd.append("-pbkdf2")

    success, output = await run_cmd(cmd, timeout=60)
    if success:
        return f"✅ Encrypted {in_file} to {out_file}"
    return f"❌ Encryption failed: {output}"


@auto_heal()
async def _openssl_enc_decrypt_impl(
    in_file: str,
    out_file: str,
    cipher: str = "aes-256-cbc",
    password: str = "",
) -> str:
    """Decrypt file."""
    cmd = [
        "openssl",
        "enc",
        f"-{cipher}",
        "-d",
        "-in",
        in_file,
        "-out",
        out_file,
    ]
    if password:
        cmd.extend(["-pass", f"pass:{password}"])
    else:
        cmd.append("-pbkdf2")

    success, output = await run_cmd(cmd, timeout=60)
    if success:
        return f"✅ Decrypted {in_file} to {out_file}"
    return f"❌ Decryption failed: {output}"


@auto_heal()
async def _openssl_dgst_impl(
    file: str,
    algorithm: str = "sha256",
) -> str:
    """Generate hash/digest."""
    cmd = ["openssl", "dgst", f"-{algorithm}", file]

    success, output = await run_cmd(cmd, timeout=30)
    if success:
        return f"## {algorithm.upper()} Digest\n\n```\n{output}\n```"
    return f"❌ Failed to generate digest: {output}"


@auto_heal()
async def _openssl_rand_impl(
    num_bytes: int,
    hex_output: bool = True,
    base64_output: bool = False,
) -> str:
    """Generate random data."""
    cmd = ["openssl", "rand"]
    if hex_output:
        cmd.append("-hex")
    elif base64_output:
        cmd.append("-base64")
    cmd.append(str(num_bytes))

    success, output = await run_cmd(cmd, timeout=30)
    if success:
        return f"## Random Data ({num_bytes} bytes)\n\n```\n{output}\n```"
    return f"❌ Failed to generate random data: {output}"


@auto_heal()
async def _openssl_version_impl() -> str:
    """Show OpenSSL version."""
    cmd = ["openssl", "version", "-a"]

    success, output = await run_cmd(cmd, timeout=30)
    if success:
        return f"## OpenSSL Version\n\n```\n{output}\n```"
    return f"❌ Failed to get version: {output}"


@auto_heal()
async def _openssl_ciphers_impl(filter_str: str = "HIGH") -> str:
    """List available ciphers."""
    cmd = ["openssl", "ciphers", "-v", filter_str]

    success, output = await run_cmd(cmd, timeout=30)
    if success:
        truncated = truncate_output(output, max_length=3000, mode="head")
        return f"## Available Ciphers ({filter_str})\n\n```\n{truncated}\n```"
    return f"❌ Failed to list ciphers: {output}"


def register_tools(server: FastMCP) -> int:
    """Register OpenSSL tools with the MCP server."""
    registry = ToolRegistry(server)

    @auto_heal()
    @registry.tool()
    async def openssl_x509_info(cert_file: str) -> str:
        """View certificate information.

        Args:
            cert_file: Path to certificate file
        """
        return await _openssl_x509_info_impl(cert_file)

    @auto_heal()
    @registry.tool()
    async def openssl_x509_text(cert_file: str) -> str:
        """View full certificate details.

        Args:
            cert_file: Path to certificate file
        """
        return await _openssl_x509_text_impl(cert_file)

    @auto_heal()
    @registry.tool()
    async def openssl_x509_verify(
        cert_file: str,
        ca_file: str = "",
    ) -> str:
        """Verify certificate chain.

        Args:
            cert_file: Certificate to verify
            ca_file: CA certificate file
        """
        return await _openssl_x509_verify_impl(cert_file, ca_file)

    @auto_heal()
    @registry.tool()
    async def openssl_genrsa(out_file: str, bits: int = 4096) -> str:
        """Generate RSA private key.

        Args:
            out_file: Output file path
            bits: Key size in bits
        """
        return await _openssl_genrsa_impl(out_file, bits)

    @auto_heal()
    @registry.tool()
    async def openssl_s_client(
        host: str,
        port: int = 443,
        show_certs: bool = False,
    ) -> str:
        """Test SSL/TLS connection.

        Args:
            host: Hostname to connect to
            port: Port number
            show_certs: Show full certificate chain
        """
        return await _openssl_s_client_impl(host, port, "", show_certs)

    @auto_heal()
    @registry.tool()
    async def openssl_s_client_cert(host: str, port: int = 443) -> str:
        """Get server certificate.

        Args:
            host: Hostname
            port: Port number
        """
        return await _openssl_s_client_cert_impl(host, port)

    @auto_heal()
    @registry.tool()
    async def openssl_dgst(file: str, algorithm: str = "sha256") -> str:
        """Generate hash/digest.

        Args:
            file: File to hash
            algorithm: Hash algorithm (sha256, sha512, md5, etc.)
        """
        return await _openssl_dgst_impl(file, algorithm)

    @auto_heal()
    @registry.tool()
    async def openssl_rand(num_bytes: int, hex_output: bool = True) -> str:
        """Generate random data.

        Args:
            num_bytes: Number of bytes to generate
            hex_output: Output as hex string
        """
        return await _openssl_rand_impl(num_bytes, hex_output)

    @auto_heal()
    @registry.tool()
    async def openssl_version() -> str:
        """Show OpenSSL version."""
        return await _openssl_version_impl()

    @auto_heal()
    @registry.tool()
    async def openssl_ciphers(filter_str: str = "HIGH") -> str:
        """List available ciphers.

        Args:
            filter_str: Cipher filter (HIGH, MEDIUM, etc.)
        """
        return await _openssl_ciphers_impl(filter_str)

    return registry.count
