# Ansible Tools

> aa_ansible module for automation and configuration management

## Diagram

```mermaid
classDiagram
    class PlaybookTools {
        +ansible_playbook_run(playbook, inventory): str
        +ansible_playbook_check(playbook): str
        +ansible_playbook_list_tasks(playbook): str
        +ansible_playbook_list_tags(playbook): str
    }

    class InventoryTools {
        +ansible_inventory_list(inventory): str
        +ansible_inventory_graph(inventory): str
        +ansible_inventory_host(host): str
    }

    class AdHocTools {
        +ansible_ping(hosts): str
        +ansible_command(hosts, cmd): str
        +ansible_shell(hosts, cmd): str
        +ansible_copy(src, dest, hosts): str
        +ansible_fetch(src, dest, hosts): str
        +ansible_setup(hosts): str
    }

    class GalaxyTools {
        +ansible_galaxy_install(name): str
        +ansible_galaxy_list(): str
        +ansible_galaxy_remove(name): str
        +ansible_galaxy_search(query): str
    }

    class VaultTools {
        +ansible_vault_encrypt(file): str
        +ansible_vault_decrypt(file): str
        +ansible_vault_view(file): str
        +ansible_vault_edit_string(string): str
    }
```

## Tool Categories

```mermaid
graph TB
    subgraph Playbook[Playbook Execution]
        RUN[ansible_playbook_run]
        CHECK[ansible_playbook_check]
        TASKS[ansible_playbook_list_tasks]
    end

    subgraph Inventory[Inventory Management]
        LIST[ansible_inventory_list]
        GRAPH[ansible_inventory_graph]
        HOST[ansible_inventory_host]
    end

    subgraph AdHoc[Ad-hoc Commands]
        PING[ansible_ping]
        CMD[ansible_command]
        SHELL[ansible_shell]
    end

    subgraph Galaxy[Galaxy Collections]
        INSTALL[ansible_galaxy_install]
        SEARCH[ansible_galaxy_search]
    end

    subgraph Vault[Vault Encryption]
        ENCRYPT[ansible_vault_encrypt]
        DECRYPT[ansible_vault_decrypt]
    end
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| tools_basic.py | `tool_modules/aa_ansible/src/` | All Ansible tools |

## Tool Summary

### Playbook Tools

| Tool | Description |
|------|-------------|
| `ansible_playbook_run` | Run an Ansible playbook |
| `ansible_playbook_check` | Dry-run a playbook (check mode) |
| `ansible_playbook_list_tasks` | List tasks in a playbook |
| `ansible_playbook_list_tags` | List tags in a playbook |

### Inventory Tools

| Tool | Description |
|------|-------------|
| `ansible_inventory_list` | List hosts in inventory |
| `ansible_inventory_graph` | Show inventory hierarchy |
| `ansible_inventory_host` | Get variables for a specific host |

### Ad-hoc Command Tools

| Tool | Description |
|------|-------------|
| `ansible_ping` | Ping hosts to check connectivity |
| `ansible_command` | Run ad-hoc command on hosts |
| `ansible_shell` | Run shell command on hosts |
| `ansible_copy` | Copy files to hosts |
| `ansible_fetch` | Fetch files from hosts |
| `ansible_setup` | Gather facts from hosts |

### Galaxy Tools

| Tool | Description |
|------|-------------|
| `ansible_galaxy_install` | Install roles/collections |
| `ansible_galaxy_list` | List installed roles/collections |
| `ansible_galaxy_remove` | Remove installed roles/collections |
| `ansible_galaxy_search` | Search Galaxy |

### Vault Tools

| Tool | Description |
|------|-------------|
| `ansible_vault_encrypt` | Encrypt a file |
| `ansible_vault_decrypt` | Decrypt a vault file |
| `ansible_vault_view` | View encrypted vault file |
| `ansible_vault_edit_string` | Encrypt a string for YAML |

## Usage Examples

```python
# Run a playbook
result = await ansible_playbook_run("site.yml", inventory="hosts.ini")

# Check mode (dry run)
result = await ansible_playbook_check("deploy.yml")

# Ping all hosts
result = await ansible_ping("all")

# Install a collection
result = await ansible_galaxy_install("community.general")

# Encrypt a file
result = await ansible_vault_encrypt("secrets.yml")
```

## Related Diagrams

- [SSH Tools](./ssh-tools.md)
- [Kubernetes Tools](./k8s-tools.md)
