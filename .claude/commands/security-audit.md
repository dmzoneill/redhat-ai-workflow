---
name: security-audit
description: "Run a comprehensive network and TLS security audit against a target."
arguments:
  - name: target
    required: true
  - name: environment
  - name: full_scan
  - name: check_certs
---
# Security Audit

Run a comprehensive network and TLS security audit against a target.

## Instructions

```text
skill_run("security_audit", '{"target": "$TARGET", "environment": "", "full_scan": "", "check_certs": ""}')
```

## What It Does

Run a comprehensive network and TLS security audit against a target.

This skill performs:
- Port scanning and service detection
- Vulnerability scanning with nmap scripts
- TLS/SSL certificate inspection
- Cipher suite analysis
- HTTP security header checks
- SSH host key fingerprinting

Uses: nmap_scan, nmap_quick_scan, nmap_service_scan, nmap_vuln_scan,
nmap_script, openssl_s_client, openssl_s_client_cert,
openssl_x509_info, openssl_x509_verify, openssl_ciphers,
curl_headers, curl_timing, ssh_keyscan

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `target` | Target host or IP to audit | Yes |
| `environment` | Environment (stage, production, ephemeral) (default: stage) | No |
| `full_scan` | Run full port scan (slower but thorough) | No |
| `check_certs` | Include TLS certificate checks (default: True) | No |
