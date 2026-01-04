# AA Git MCP Server

MCP server for Git repository operations.

## Tools (14)

| Tool | Description |
|------|-------------|
| `git_status` | Get current status of a repository |
| `git_branch_list` | List branches |
| `git_log` | Show commit history |
| `git_diff` | Show uncommitted changes |
| `git_branch_create` | Create a new branch |
| `git_checkout` | Switch branches |
| `git_add` | Stage files |
| `git_commit` | Commit changes |
| `git_push` | Push to remote |
| `git_pull` | Pull from remote |
| `git_fetch` | Fetch without merging |
| `git_stash` | Stash/restore changes |
| `git_reset` | Reset HEAD |
| `git_clean` | Remove untracked files |
| `git_remote_info` | Show remote info |

## Installation

```bash
cd mcp-servers/aa-git
pip install -e .
```

## Usage

### Cursor/MCP Config

```json
{
  "mcpServers": {
    "git": {
      "command": "aa-git"
    }
  }
}
```

### Standalone

```bash
aa-git
```

## Authentication

Uses system Git configuration (`~/.gitconfig`, SSH keys, credential helpers).
