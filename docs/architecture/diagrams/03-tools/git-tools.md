# Git Tools

> aa_git module for local Git operations

## Diagram

```mermaid
classDiagram
    class GitBasic {
        +git_status(): str
        +git_log(n): str
        +git_diff(file): str
        +git_branch_list(): list
        +git_show(ref): str
        +git_blame(file): str
    }

    class GitCore {
        +git_commit(message): str
        +git_push(remote, branch): str
        +git_pull(remote, branch): str
        +git_checkout(branch): str
        +git_create_branch(name): str
        +git_merge(branch): str
        +git_stash(action): str
    }

    class GitExtra {
        +git_rebase(branch): str
        +git_cherry_pick(sha): str
        +git_reset(mode, ref): str
        +git_clean(force): str
        +git_bisect(action): str
        +git_reflog(): str
    }

    GitBasic <|-- GitCore
    GitCore <|-- GitExtra
```

## Command Execution

```mermaid
sequenceDiagram
    participant Tool as Git Tool
    participant Runner as Command Runner
    participant Git as Git CLI
    participant Repo as Repository

    Tool->>Runner: Build command
    Runner->>Runner: Validate args
    Runner->>Git: Execute command
    Git->>Repo: Perform operation
    Repo-->>Git: Result
    Git-->>Runner: Output
    Runner-->>Tool: Parsed output

    Tool-->>Tool: Format for Claude
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| tools_basic.py | `tool_modules/aa_git/src/` | Read operations |
| tools_core.py | `tool_modules/aa_git/src/` | Write operations |
| tools_extra.py | `tool_modules/aa_git/src/` | Advanced operations |

## Tool Summary

| Tool | Tier | Description |
|------|------|-------------|
| `git_status` | basic | Show working tree status |
| `git_log` | basic | Show commit history |
| `git_diff` | basic | Show changes |
| `git_branch_list` | basic | List branches |
| `git_commit` | core | Create commit |
| `git_push` | core | Push to remote |
| `git_pull` | core | Pull from remote |
| `git_checkout` | core | Switch branches |
| `git_rebase` | extra | Rebase branch |
| `git_cherry_pick` | extra | Cherry-pick commit |

## Safety Rules

```mermaid
flowchart TB
    subgraph Safe[Safe Operations]
        STATUS[git_status]
        LOG[git_log]
        DIFF[git_diff]
        BRANCH[git_branch_list]
    end

    subgraph Caution[Require Caution]
        COMMIT[git_commit]
        PUSH[git_push]
        MERGE[git_merge]
    end

    subgraph Dangerous[Require Permission]
        RESET[git_reset --hard]
        CLEAN[git_clean -fd]
        FORCE[git_push --force]
        CHECKOUT_FILE[git_checkout -- file]
    end

    Safe --> |"Always allowed"| OK[Execute]
    Caution --> |"Check status first"| OK
    Dangerous --> |"Ask user first"| CONFIRM{User confirms?}
    CONFIRM -->|Yes| OK
    CONFIRM -->|No| ABORT[Abort]
```

## Branch Naming

```mermaid
flowchart LR
    ISSUE[Issue Key] --> PATTERN[Branch Pattern]
    PATTERN --> NAME[aap-12345-short-description]
    
    subgraph Convention[Naming Convention]
        PREFIX[issue-key]
        SEP[-]
        DESC[short-description]
    end
```

## Commit Message Format

```
{issue_key} - {type}({scope}): {description}

Examples:
AAP-12345 - feat(api): add new endpoint
AAP-12345 - fix(auth): resolve token refresh
AAP-12345 - docs(readme): update installation
```

## Related Diagrams

- [Tool Module Structure](./tool-module-structure.md)
- [GitLab Tools](./gitlab-tools.md)
- [Git Safety Rules](../../ai-rules/30-git-safety.md)
