# Cert Check

Check TLS certificate health for one or more endpoints.

## Instructions

```text
skill_run("cert_check", '{"endpoints": "$ENDPOINTS", "warn_days": "", "environment": ""}')
```

## What It Does

Check TLS certificate health for one or more endpoints.

This skill performs:
- Certificate expiry monitoring
- Certificate chain verification
- TLS version and cipher inspection
- HTTP header validation
- Port-level TLS service detection
- InScope documentation lookup for cert management

Uses: openssl_s_client, openssl_s_client_cert, openssl_x509_info,
openssl_x509_verify, curl_headers, nmap_scan, nmap_script,
inscope_ask

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `endpoints` | Comma-separated list of host:port endpoints to check | Yes |
| `warn_days` | Warn if certificate expires within this many days (default: 30) | No |
| `environment` | Environment (stage, production, ephemeral) (default: stage) | No |
