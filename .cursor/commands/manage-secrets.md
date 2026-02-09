# Manage Secrets

Manage encrypted secrets using Ansible Vault and OpenSSL.

## Instructions

```text
skill_run("manage_secrets", '{"action": "$ACTION", "file_path": "", "variable_name": ""}')
```

## What It Does

Manage encrypted secrets using Ansible Vault and OpenSSL.

This skill handles:
- Viewing encrypted vault files
- Encrypting and decrypting files
- Encrypting individual strings
- Generating RSA keys
- Creating file digests

Uses: ansible_vault_encrypt, ansible_vault_decrypt, ansible_vault_view,
ansible_vault_encrypt_string, openssl_genrsa, openssl_dgst,
ssh_fingerprint

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `action` | Action to perform (view|encrypt|decrypt|rotate|generate) | Yes |
| `file_path` | Path to the secrets file | No |
| `variable_name` | Variable name for string encryption | No |
