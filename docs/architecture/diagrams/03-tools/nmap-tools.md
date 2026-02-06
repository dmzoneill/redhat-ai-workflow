# Nmap Tools

> aa_nmap module for network scanning and security auditing

## Diagram

```mermaid
classDiagram
    class ScanTools {
        +nmap_scan(target, ports): str
        +nmap_quick_scan(target): str
        +nmap_full_scan(target): str
        +nmap_service_scan(target): str
        +nmap_os_scan(target): str
    }

    class DiscoveryTools {
        +nmap_ping_scan(target): str
        +nmap_list_scan(target): str
        +nmap_arp_scan(target): str
    }

    class ScriptTools {
        +nmap_vuln_scan(target): str
        +nmap_script(target, script): str
    }

    class OutputTools {
        +nmap_parse_output(file): str
    }
```

## Tool Categories

```mermaid
graph TB
    subgraph Scanning[Port Scanning]
        BASIC[nmap_scan]
        QUICK[nmap_quick_scan]
        FULL[nmap_full_scan]
        SERVICE[nmap_service_scan]
    end

    subgraph Discovery[Host Discovery]
        PING[nmap_ping_scan]
        LIST[nmap_list_scan]
        ARP[nmap_arp_scan]
    end

    subgraph Security[Security Scanning]
        VULN[nmap_vuln_scan]
        SCRIPT[nmap_script]
    end
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| tools_basic.py | `tool_modules/aa_nmap/src/` | All nmap tools |

## Tool Summary

### Scan Tools

| Tool | Description |
|------|-------------|
| `nmap_scan` | Basic port scan |
| `nmap_quick_scan` | Quick scan (top 100 ports) |
| `nmap_full_scan` | Full port scan (all 65535) |
| `nmap_service_scan` | Service/version detection |
| `nmap_os_scan` | OS detection |

### Discovery Tools

| Tool | Description |
|------|-------------|
| `nmap_ping_scan` | Host discovery (ping scan) |
| `nmap_list_scan` | List targets without scanning |
| `nmap_arp_scan` | ARP discovery (local network) |

### Script Tools

| Tool | Description |
|------|-------------|
| `nmap_vuln_scan` | Vulnerability scan |
| `nmap_script` | Run specific NSE script |

## Usage Examples

```python
# Quick port scan
result = await nmap_quick_scan("192.168.1.1")

# Service detection
result = await nmap_service_scan("example.com")

# Vulnerability scan
result = await nmap_vuln_scan("192.168.1.0/24")

# Run specific script
result = await nmap_script("example.com", "http-headers")
```

## Related Diagrams

- [SSH Tools](./ssh-tools.md)
- [OpenSSL Tools](./openssl-tools.md)
