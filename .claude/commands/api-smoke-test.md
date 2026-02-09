---
name: api-smoke-test
description: "Run smoke tests against API endpoints to verify availability and performance."
arguments:
  - name: base_url
    required: true
  - name: environment
  - name: auth_token
  - name: fail_on_slow
---
# Api Smoke Test

Run smoke tests against API endpoints to verify availability and performance.

## Instructions

```text
skill_run("api_smoke_test", '{"base_url": "$BASE_URL", "environment": "", "auth_token": "", "fail_on_slow": ""}')
```

## What It Does

Run smoke tests against API endpoints to verify availability and performance.

This skill performs:
- GET/POST/PUT/DELETE endpoint checks
- Response time measurements
- HTTP header inspection
- TLS connection verification
- Slow endpoint detection

Uses: curl_get, curl_post, curl_put, curl_delete, curl_head,
curl_timing, curl_headers, openssl_s_client

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `base_url` | Base URL of the API to test (e.g., https://api.example.com) | Yes |
| `environment` | Environment (stage, production, ephemeral) (default: stage) | No |
| `auth_token` | Bearer token for authenticated endpoints | No |
| `fail_on_slow` | Fail if response time exceeds threshold | No |
