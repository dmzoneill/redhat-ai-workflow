# cURL Tools

> aa_curl module for HTTP client and API testing

## Diagram

```mermaid
classDiagram
    class RequestTools {
        +curl_get(url, headers): str
        +curl_post(url, data, headers): str
        +curl_put(url, data, headers): str
        +curl_delete(url, headers): str
        +curl_patch(url, data, headers): str
        +curl_head(url): str
    }

    class UtilityTools {
        +curl_download(url, output): str
        +curl_upload(url, file): str
        +curl_headers(url): str
        +curl_follow(url): str
    }

    class DebugTools {
        +curl_verbose(url): str
        +curl_timing(url): str
    }
```

## Tool Categories

```mermaid
graph TB
    subgraph Requests[HTTP Requests]
        GET[curl_get]
        POST[curl_post]
        PUT[curl_put]
        DELETE[curl_delete]
        PATCH[curl_patch]
    end

    subgraph Utility[Utility]
        DOWNLOAD[curl_download]
        UPLOAD[curl_upload]
        HEADERS[curl_headers]
    end

    subgraph Debug[Debugging]
        VERBOSE[curl_verbose]
        TIMING[curl_timing]
    end
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| tools_basic.py | `tool_modules/aa_curl/src/` | All cURL tools |

## Tool Summary

### Request Tools

| Tool | Description |
|------|-------------|
| `curl_get` | HTTP GET request |
| `curl_post` | HTTP POST request |
| `curl_put` | HTTP PUT request |
| `curl_delete` | HTTP DELETE request |
| `curl_patch` | HTTP PATCH request |
| `curl_head` | HTTP HEAD request |

### Utility Tools

| Tool | Description |
|------|-------------|
| `curl_download` | Download file to disk |
| `curl_upload` | Upload file |
| `curl_headers` | Get response headers only |
| `curl_follow` | Follow redirects, show final URL |

### Debug Tools

| Tool | Description |
|------|-------------|
| `curl_verbose` | Verbose request with timing |
| `curl_timing` | Show request timing breakdown |

## Usage Examples

```python
# Simple GET request
result = await curl_get("https://api.example.com/users")

# POST with JSON
result = await curl_post(
    "https://api.example.com/users",
    data='{"name": "John"}',
    headers={"Content-Type": "application/json"}
)

# Download a file
result = await curl_download(
    "https://example.com/file.zip",
    output="/tmp/file.zip"
)

# Check timing
result = await curl_timing("https://example.com")
```

## Related Diagrams

- [HTTP Client](../01-server/http-client.md)
- [Auth Flows](../07-integrations/auth-flows.md)
