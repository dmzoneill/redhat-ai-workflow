# Network Connectivity Check

Diagnose network connectivity issues to one or more targets.

## Instructions

```text
skill_run("network_connectivity_check", '{"targets": "$TARGETS", "check_vpn": "", "full_scan": ""}')
```

## What It Does

Diagnose network connectivity issues to one or more targets.

This skill performs:
- Ping sweep and host discovery
- Port scanning and service detection
- ARP scan for local network discovery
- HTTP connectivity and timing checks
- SSH connectivity testing
- TLS connection verification
- System hostname and network identity check

Uses: nmap_ping_scan, nmap_quick_scan, nmap_list_scan,
curl_timing, curl_headers, curl_get, ssh_test, ssh_keyscan,
openssl_s_client, hostnamectl_status

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `targets` | Comma-separated list of hosts or IPs to check | Yes |
| `check_vpn` | Check VPN connectivity for internal targets (default: True) | No |
| `full_scan` | Run full port scan (slower) | No |
