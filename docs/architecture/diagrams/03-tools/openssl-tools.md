# OpenSSL Tools

> aa_openssl module for cryptography and certificate management

## Diagram

```mermaid
classDiagram
    class CertificateTools {
        +openssl_x509_info(cert): str
        +openssl_x509_verify(cert, ca): str
        +openssl_req_new(key, subject): str
        +openssl_genrsa(bits): str
        +openssl_genpkey(algorithm): str
    }

    class ConnectionTools {
        +openssl_s_client(host, port): str
        +openssl_s_client_cert(host): str
    }

    class EncryptionTools {
        +openssl_enc_encrypt(file, cipher): str
        +openssl_enc_decrypt(file, cipher): str
        +openssl_dgst(file, algorithm): str
    }

    class UtilityTools {
        +openssl_rand(bytes): str
        +openssl_version(): str
        +openssl_ciphers(): str
    }
```

## Tool Categories

```mermaid
graph TB
    subgraph Certs[Certificate Management]
        INFO[openssl_x509_info]
        VERIFY[openssl_x509_verify]
        CSR[openssl_req_new]
        GENKEY[openssl_genrsa]
    end

    subgraph TLS[TLS Testing]
        CLIENT[openssl_s_client]
        GET_CERT[openssl_s_client_cert]
    end

    subgraph Crypto[Encryption]
        ENCRYPT[openssl_enc_encrypt]
        DECRYPT[openssl_enc_decrypt]
        HASH[openssl_dgst]
    end
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| tools_basic.py | `tool_modules/aa_openssl/src/` | All OpenSSL tools |

## Tool Summary

### Certificate Tools

| Tool | Description |
|------|-------------|
| `openssl_x509_info` | View certificate information |
| `openssl_x509_verify` | Verify certificate chain |
| `openssl_req_new` | Generate certificate signing request |
| `openssl_genrsa` | Generate RSA private key |
| `openssl_genpkey` | Generate private key (various algorithms) |

### Connection Tools

| Tool | Description |
|------|-------------|
| `openssl_s_client` | Test SSL/TLS connection |
| `openssl_s_client_cert` | Get server certificate |

### Encryption Tools

| Tool | Description |
|------|-------------|
| `openssl_enc_encrypt` | Encrypt file |
| `openssl_enc_decrypt` | Decrypt file |
| `openssl_dgst` | Generate hash/digest |

### Utility Tools

| Tool | Description |
|------|-------------|
| `openssl_rand` | Generate random data |
| `openssl_version` | Show OpenSSL version |
| `openssl_ciphers` | List available ciphers |

## Usage Examples

```python
# View certificate info
result = await openssl_x509_info("/path/to/cert.pem")

# Test TLS connection
result = await openssl_s_client("example.com", 443)

# Generate RSA key
result = await openssl_genrsa(4096)

# Generate SHA256 hash
result = await openssl_dgst("file.txt", "sha256")
```

## Related Diagrams

- [SSH Tools](./ssh-tools.md)
- [Kubernetes Tools](./k8s-tools.md)
