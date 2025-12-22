# Skills

Skills are reusable workflows that combine multiple MCP tools with decision logic.
They can be invoked by agents or directly by the user.

## Quick Reference

| Skill | Purpose | Agent |
|-------|---------|-------|
| [`start_work`](#start_work) | Begin work on a Jira issue | developer |
| [`create_mr`](#create_mr) | Create MR with proper format | developer |
| [`close_issue`](#close_issue) | Close issue with commit summary | developer |
| [`review_pr`](#review_pr) | Review colleague's PR | developer |
| [`test_mr_ephemeral`](#test_mr_ephemeral) | Test in ephemeral namespace | developer |
| [`jira_hygiene`](#jira_hygiene) | Validate/fix Jira quality | developer |
| [`investigate_alert`](#investigate_alert) | Investigate firing alerts | devops, incident |
| [`debug_prod`](#debug_prod) | Debug production issues | devops, incident |
| [`release_aa_backend_prod`](#release_aa_backend_prod) | Release to production | release |

---

## Skill Details

### start_work

Begin work on a Jira issue - creates branch, sets up context, or resumes existing work.

```
skill_run("start_work", '{"issue_key": "AAP-12345"}')
```

**Inputs:**
| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `issue_key` | Yes | - | Jira issue key (e.g., AAP-12345) |
| `repo` | No | `.` | Repository path |

```mermaid
flowchart TD
    A[Start] --> B[Get Jira Issue]
    B --> C{Branch Exists?}
    C -->|Yes| D[Checkout Branch]
    D --> E[Git Pull]
    E --> F{Open MR?}
    F -->|Yes| G[Get MR Feedback]
    F -->|No| H[Check Jira Updates]
    G --> I[Present Context]
    H --> I
    C -->|No| J[Create Branch]
    J --> K[AAP-12345-summary]
    K --> L[Ready to Work]
    I --> L
```

---

### create_mr

Create a Merge Request with proper formatting, linked to Jira.

```
skill_run("create_mr", '{"issue_key": "AAP-12345"}')
```

**Inputs:**
| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `issue_key` | Yes | - | Jira issue key |
| `repo` | No | `.` | Repository path |
| `draft` | No | `false` | Create as draft MR |

```mermaid
flowchart TD
    A[Start] --> B[Get Jira Issue]
    B --> C[Get Current Branch]
    C --> D[Get Commits]
    D --> E[Build MR Title]
    E --> F["AAP-12345 - type: summary"]
    F --> G[Build MR Description]
    G --> H[Link to Jira]
    H --> I[Push Branch]
    I --> J[Create GitLab MR]
    J --> K[Add MR Link to Jira]
    K --> L[Done]
```

---

### close_issue

Close a Jira issue with a summary of completed work from commits.

```
skill_run("close_issue", '{"issue_key": "AAP-12345"}')
```

**Inputs:**
| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `issue_key` | Yes | - | Jira issue key |
| `repo` | No | `.` | Repository path |
| `add_comment` | No | `true` | Add closing comment |

```mermaid
flowchart TD
    A[Start] --> B{Already Done?}
    B -->|Yes| C[Skip]
    B -->|No| D[Find Branch]
    D --> E[Get Commits]
    E --> F[Get MR Info]
    F --> G[Build Comment]
    G --> H["✅ Branch, MR, Commits Table"]
    H --> I[Add Comment to Jira]
    I --> J[Transition to Done]
    J --> K[Verify Status]
```

---

### review_pr

Review a colleague's PR with static analysis and local testing.

```
skill_run("review_pr", '{"mr_id": 123}')
```

**Inputs:**
| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `mr_id` | Yes | - | GitLab MR ID |
| `skip_tests` | No | `false` | Skip local tests |

```mermaid
flowchart TD
    A[Start] --> B[Get MR Details]
    B --> C[Extract Jira Key]
    C --> D[Get Jira Context]
    D --> E[Check Konflux Pipeline]
    E --> F[Validate Commit Titles]
    F --> G[Static Analysis]
    G --> H["Security, Memory, Race Conditions"]
    H --> I{Skip Tests?}
    I -->|No| J[Checkout Branch]
    J --> K[Run Migrations]
    K --> L[Run Pytest]
    L --> M[Collect Results]
    I -->|Yes| M
    M --> N[Build Feedback]
    N --> O{User Approves?}
    O -->|Yes| P[Post to GitLab]
    O -->|No| Q[Revise Feedback]
```

---

### test_mr_ephemeral

Test an MR image in an ephemeral Kubernetes namespace.

```
skill_run("test_mr_ephemeral", '{"mr_id": 123}')
skill_run("test_mr_ephemeral", '{"commit_sha": "abc123"}')
```

**Inputs:**
| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `mr_id` | No* | - | GitLab MR ID |
| `commit_sha` | No* | - | Commit SHA to test |
| `duration` | No | `2h` | Namespace duration |
| `billing` | No | `false` | Include billing component |

*One of `mr_id` or `commit_sha` required

```mermaid
flowchart TD
    A[Start] --> B{MR or SHA?}
    B -->|MR| C[Get MR Details]
    B -->|SHA| D[Use SHA Directly]
    C --> E[Extract SHA from MR]
    D --> E
    E --> F[Verify Image in Quay]
    F --> G{Image Exists?}
    G -->|No| H[Error: Build First]
    G -->|Yes| I[Reserve Namespace]
    I --> J[bonfire deploy]
    J --> K[Wait for Pods Ready]
    K --> L[Get DB Credentials]
    L --> M["Host/Port from Service"]
    M --> N["User/Pass from Secret"]
    N --> O[Run Tests]
    O --> P[Collect Results]
    P --> Q[Present Summary]
```

---

### jira_hygiene

Validate and fix Jira issue quality - descriptions, acceptance criteria, links.

```
skill_run("jira_hygiene", '{"issue_key": "AAP-12345"}')
skill_run("jira_hygiene", '{"issue_key": "AAP-12345", "auto_fix": true}')
```

**Inputs:**
| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `issue_key` | Yes | - | Jira issue key |
| `auto_fix` | No | `false` | Auto-fix issues |
| `auto_transition` | No | `false` | Auto-transition New→Refinement |

```mermaid
flowchart TD
    A[Start] --> B[Get Issue]
    B --> C[Check Description]
    C --> D[Check Acceptance Criteria]
    D --> E[Check Priority]
    E --> F[Check Labels/Components]
    F --> G{Story?}
    G -->|Yes| H[Check Epic Link]
    G -->|No| I[Skip Epic Check]
    H --> I
    I --> J[Check Fix Version]
    J --> K{In Progress?}
    K -->|Yes| L[Check Story Points]
    K -->|No| M[Skip Points Check]
    L --> M
    M --> N[Check Markup]
    N --> O[Compile Issues]
    O --> P{Auto-fix?}
    P -->|Yes| Q[Fix Issues]
    P -->|No| R[Report Only]
    Q --> S{New + Complete?}
    R --> S
    S -->|Yes| T[Transition to Refinement]
    S -->|No| U[Done]
    T --> U
```

**Checks Performed:**
- ✅ Has description (not empty)
- ✅ Has acceptance criteria
- ✅ Priority is set
- ✅ Has labels/components
- ✅ Linked to epic (stories only)
- ✅ Has fix version
- ✅ Story points (if In Progress)
- ✅ Proper Jira markup

---

### investigate_alert

Investigate a firing Prometheus alert.

```
skill_run("investigate_alert", '{"environment": "production"}')
skill_run("investigate_alert", '{"environment": "stage", "alert_name": "HighErrorRate"}')
```

**Inputs:**
| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `environment` | Yes | - | `production` or `stage` |
| `alert_name` | No | - | Specific alert to investigate |

```mermaid
flowchart TD
    A[Start] --> B[Get Firing Alerts]
    B --> C[Get Pod Status]
    C --> D[Check Recent Deployments]
    D --> E[Query Prometheus]
    E --> F[Search Kibana Logs]
    F --> G[Correlate Events]
    G --> H[Suggest Causes]
    H --> I[Recommend Actions]
```

---

### debug_prod

Comprehensive production debugging with memory-backed pattern matching.

```
skill_run("debug_prod", '{"namespace": "main"}')
skill_run("debug_prod", '{"namespace": "billing", "alert_name": "HighLatency"}')
```

**Inputs:**
| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `namespace` | No | asks | `main` or `billing` |
| `alert_name` | No | - | Prometheus alert name |
| `pod_filter` | No | - | Filter pods by name |
| `time_range` | No | `1h` | How far back (15m, 1h, 6h, 24h) |

```mermaid
flowchart TD
    A[Start] --> B{Namespace?}
    B -->|Not Set| C[Ask User]
    B -->|Set| D[Load Patterns from Memory]
    C --> D
    D --> E[Check Pod Status]
    E --> F[Get K8s Events]
    F --> G[Get Error Logs]
    G --> H["grep error/warning, max 3 pods"]
    H --> I[Get Firing Alerts]
    I --> J{Alert Name?}
    J -->|Yes| K[Lookup Alert Definition]
    J -->|No| L[Continue]
    K --> L
    L --> M[Get Deployed SHA]
    M --> N["From app-interface CICD"]
    N --> O[Check Recent Deployments]
    O --> P[Match Against Patterns]
    P --> Q[Build Report]
    Q --> R[Suggest Next Steps]
    R --> S["Update Memory if Fix Works"]
```

**Locations Checked:**
- Pod status: CrashLoopBackOff, OOMKilled, restarts
- Events: warnings, errors
- Logs: filtered for errors (truncated)
- Alert definitions: `app-interface/resources/insights-prod/`
- CICD config: `app-interface/data/services/insights/tower-analytics/cicd/`
- Namespace config: `app-interface/data/services/insights/tower-analytics/namespaces/`

---

### release_aa_backend_prod

Release Automation Analytics backend to production via app-interface.

```
skill_run("release_aa_backend_prod", '{"commit_sha": "abc123def456"}')
```

**Inputs:**
| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `commit_sha` | Yes | - | Commit SHA to release |
| `release_date` | No | today | Release date for Jira |
| `include_billing` | No | `false` | Also update billing namespace |

```mermaid
flowchart TD
    A[Start] --> B[Verify Commit Exists]
    B --> C[Verify Image in Quay]
    C --> D{Image Ready?}
    D -->|No| E[Error: Build First]
    D -->|Yes| F[Get Current Prod SHA]
    F --> G[Generate Release Summary]
    G --> H["Commits since last release"]
    H --> I[Create Jira Issue]
    I --> J["YYYY-MM-DD Analytics HCC Service Release"]
    J --> K[Checkout app-interface]
    K --> L[Create Release Branch]
    L --> M[Update deploy-clowder.yml]
    M --> N["tower-analytics-prod.yml ref: NEW_SHA"]
    N --> O{Include Billing?}
    O -->|Yes| P[Update billing ref too]
    O -->|No| Q[Skip billing]
    P --> Q
    Q --> R[Commit Changes]
    R --> S[Push Branch]
    S --> T[Create GitLab MR]
    T --> U[Link MR to Jira]
    U --> V[Await Team Approval]
```

**Files Modified:**
```
app-interface/data/services/insights/tower-analytics/cicd/deploy-clowder.yml
```

---

## How Skills Work

1. **Skill Definition** - YAML file describing inputs, steps, and outputs
2. **Tool Composition** - Combines multiple MCP tools in sequence
3. **Decision Points** - Conditional logic based on tool outputs
4. **Compute Blocks** - Python code for data transformation
5. **Memory Integration** - Learn from past runs

## Skill Format

```yaml
name: skill_name
description: What this skill does
version: "1.0"

inputs:
  - name: input_name
    type: string
    required: true
    description: "What this input is for"

constants:
  some_value: "constant data"

steps:
  - name: step_one
    tool: tool_name
    args:
      param: "{{ inputs.input_name }}"
    output: step1_result

  - name: step_two
    condition: "{{ step1_result.success }}"
    compute: |
      # Python code here
      result = {"processed": step1_result.data}
    output: step2_result

  - name: step_three
    condition: "{{ not step2_result.processed }}"
    tool: fallback_tool
    on_error: continue

outputs:
  - name: summary
    value: |
      ## Results
      {{ step2_result | json }}
```

## Usage

**In chat:**
```
Run skill: start_work with issue AAP-12345
```

**Via tool:**
```
skill_run("start_work", '{"issue_key": "AAP-12345"}')
```

**From agent:**
```
Use the investigate_alert skill to check what's happening in production
```
