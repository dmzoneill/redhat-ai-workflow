# CRITICAL: Use MCP Tools Instead of Raw CLI

## The Rule

**NEVER run a CLI command via the Shell tool when an MCP tool exists for it.**

Blocked commands are **automatically rejected** by hooks across all AI tools:
- **Cursor**: `beforeShellExecution` hook (`.cursor/hooks.json`)
- **Claude Code**: `PreToolUse` hook (`.claude/settings.json`)
- **Gemini CLI**: `BeforeTool` hook (`.gemini/settings.json`)
- **GitHub Copilot**: `preToolUse` hook (`.github/hooks/hooks.json`)
- **OpenCode**: bash permission denials (`opencode.json`)
- **Codex**: approval policy + AGENTS.md rules (`.codex/config.toml`)

All hook-based tools share a single script: `.cursor/hooks/block-cli.sh`. The blocklist is defined in `config.json` -> `cli_to_mcp`.

MCP tools are superior because they:
- Handle **authentication** automatically (tokens, kubeconfig, API keys)
- Provide **error recovery** and auto-healing
- Log to **memory** for session context
- Are **auditable** and reproducible
- Return **structured, formatted** output

## Decision Tree

Before running any command:

```
1. Is there an MCP tool for this? → Check the table below
   ├─ YES → Is the right persona loaded?
   │        ├─ YES → Call the MCP tool directly
   │        └─ NO  → Load persona first: persona_load("...")
   └─ NO  → Is it in the allowed list? → Use shell()
            └─ Unknown → shell() will let it through
```

## CLI-to-MCP Tool Mapping

### Network / HTTP

| CLI Command | MCP Module | MCP Tools | Load Persona |
|-------------|-----------|-----------|--------------|
| `curl` | `aa_curl` | `curl_get()`, `curl_post()`, `curl_put()`, `curl_delete()`, `curl_patch()` | `developer` |
| `wget` | `aa_curl` | `curl_download()` | `developer` |

### Git / Version Control

| CLI Command | MCP Module | MCP Tools | Load Persona |
|-------------|-----------|-----------|--------------|
| `git` | `aa_git` | `git_status()`, `git_commit()`, `git_push()`, `git_diff()`, `git_log()` | `developer` |

### Kubernetes / OpenShift

| CLI Command | MCP Module | MCP Tools | Load Persona |
|-------------|-----------|-----------|--------------|
| `kubectl` | `aa_k8s` | `kubectl_get_pods()`, `kubectl_logs()`, `kubectl_get_deployments()`, `kubectl_describe_pod()` | `devops` |
| `oc` | `aa_k8s` | `kubectl_get_pods()`, `kubectl_logs()`, `kubectl_exec()` | `devops` |
| `bonfire` | `aa_bonfire` | `bonfire_deploy()`, `bonfire_namespace_list()`, `bonfire_namespace_reserve()` | `devops` |
| `helm` | `aa_k8s` | `kubectl_get()` | `devops` |

### GitHub / GitLab

| CLI Command | MCP Module | MCP Tools | Load Persona |
|-------------|-----------|-----------|--------------|
| `gh` | `aa_github` | `gh_pr_list()`, `gh_pr_view()`, `gh_run_list()`, `gh_run_view()`, `gh_issue_list()` | `github` |
| `glab` | `aa_gitlab` | `gitlab_mr_view()`, `gitlab_list_mrs()`, `gitlab_ci_status()`, `gitlab_ci_view()` | `developer` |

### Containers

| CLI Command | MCP Module | MCP Tools | Load Persona |
|-------------|-----------|-----------|--------------|
| `docker` | `aa_docker` | `docker_ps()`, `docker_compose_up()`, `docker_compose_down()`, `docker_logs()`, `docker_exec()` | `devops` |
| `docker-compose` | `aa_docker` | `docker_compose_up()`, `docker_compose_down()`, `docker_compose_status()` | `devops` |
| `podman` | `aa_podman` | `podman_ps()`, `podman_run()`, `podman_logs()`, `podman_exec()` | `devops` |

### System Administration

| CLI Command | MCP Module | MCP Tools | Load Persona |
|-------------|-----------|-----------|--------------|
| `ssh` / `sshpass` | `aa_ssh` | `ssh_command()`, `ssh_test()` | `security` |
| `systemctl` | `aa_systemd` | `systemctl_status()`, `systemctl_restart()`, `systemctl_start()`, `systemctl_stop()` | `infra` |
| `journalctl` | `aa_systemd` | `journalctl_unit()`, `journalctl_logs()`, `journalctl_boot()` | `infra` |
| `virsh` | `aa_libvirt` | `virsh_list()`, `virsh_start()`, `virsh_shutdown()`, `virsh_destroy()` | `infra` |
| `virt-install` | `aa_libvirt` | `virt_install()` | `infra` |

### Linting / Testing

| CLI Command | MCP Module | MCP Tools | Load Persona |
|-------------|-----------|-----------|--------------|
| `flake8` / `mypy` / `black` / `isort` / `ruff` | `aa_lint` | `lint_python()` | `developer` |
| `pytest` | `aa_lint` | `test_run()`, `test_coverage()` | `developer` |
| `make` | `aa_make` | `make_target()` | `code` |

### Security

| CLI Command | MCP Module | MCP Tools | Load Persona |
|-------------|-----------|-----------|--------------|
| `openssl` | `aa_openssl` | `openssl_s_client()`, `openssl_x509_info()`, `openssl_x509_verify()` | `security` |
| `nmap` | `aa_nmap` | `nmap_scan()`, `nmap_quick_scan()`, `nmap_vuln_scan()` | `security` |

### Databases

| CLI Command | MCP Module | MCP Tools | Load Persona |
|-------------|-----------|-----------|--------------|
| `psql` | `aa_postgres` | `psql_query()`, `psql_tables()`, `psql_describe()` | `database` |
| `mysql` | `aa_mysql` | `mysql_query()`, `mysql_tables()`, `mysql_describe()` | `database` |
| `sqlite3` | `aa_sqlite` | `sqlite_query()`, `sqlite_tables()`, `sqlite_schema()` | `database` |

### Cloud / Infrastructure

| CLI Command | MCP Module | MCP Tools | Load Persona |
|-------------|-----------|-----------|--------------|
| `aws` | `aa_aws` | `aws_s3_ls()`, `aws_s3_cp()`, `aws_ec2_describe_instances()` | `infra` |
| `gcloud` | `aa_gcloud` | `gcloud_compute_instances_list()`, `gcloud_storage_ls()`, `gcloud_config_list()` | `infra` |
| `ansible` / `ansible-playbook` | `aa_ansible` | `ansible_playbook_run()`, `ansible_ping()`, `ansible_command()` | `infra` |

### CI/CD / Releases

| CLI Command | MCP Module | MCP Tools | Load Persona |
|-------------|-----------|-----------|--------------|
| `tkn` | `aa_konflux` | `tkn_pipelinerun_list()`, `tkn_pipelinerun_logs()`, `tkn_pipelinerun_describe()` | `release` |
| `skopeo` | `aa_quay` | `skopeo_get_digest()`, `quay_list_tags()` | `release` |

### Project Management

| CLI Command | MCP Module | MCP Tools | Load Persona |
|-------------|-----------|-----------|--------------|
| `rh-issue` | `aa_jira` | `jira_view_issue()`, `jira_search()`, `jira_my_issues()` | `developer` |

## Allowed Commands (OK to use via shell)

These commands are explicitly allowed through `shell()` because they are basic utilities without MCP equivalents:

- **File operations:** `ls`, `cat`, `head`, `tail`, `grep`, `rg`, `find`, `wc`, `file`, `stat`
- **Output:** `echo`, `printf`, `date`, `whoami`, `hostname`, `uname`, `id`
- **File management:** `cd`, `pwd`, `mkdir`, `cp`, `mv`, `rm`, `touch`, `chmod`, `chown`, `ln`
- **Language runtimes:** `python`, `python3`, `node`, `npm`, `pip`, `pipenv`, `uv`
- **Data processing:** `jq`, `yq`, `sed`, `awk`, `sort`, `uniq`, `tr`, `cut`, `paste`, `column`
- **Process control:** `sleep`, `timeout`, `kill`, `pkill`, `ps`, `top`, `df`, `du`, `free`
- **Archives:** `tar`, `gzip`, `gunzip`, `zip`, `unzip`
- **Shell builtins:** `env`, `export`, `source`, `which`, `type`, `command`, `test`, `set`

## Quick Persona Reference

| Domain | Persona | Key Modules |
|--------|---------|-------------|
| Coding, PRs, linting | `developer` | git, gitlab, jira, lint, curl |
| Kubernetes, containers, ephemeral | `devops` | k8s, bonfire, docker, podman, quay |
| Alerts, incidents, logs | `incident` | k8s, prometheus, kibana, alertmanager |
| Releases, pipelines | `release` | konflux, quay, git, appinterface |
| GitHub workflows | `github` | github, git, jira |
| Security scanning | `security` | nmap, openssl, ssh |
| Databases | `database` | postgres, mysql, sqlite, ssh |
| Infrastructure, cloud | `infra` | ansible, aws, gcloud, systemd, ssh, libvirt |
