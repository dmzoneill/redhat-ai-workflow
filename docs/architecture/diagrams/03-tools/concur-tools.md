# Concur Tools

> aa_concur module for SAP Concur expense automation

## Diagram

```mermaid
classDiagram
    class ConcurTools {
        +concur_submit_expense(amount, date, desc): str
        +concur_list_reports(): str
        +concur_check_status(report_id): str
    }

    class BrowserAutomation {
        +launch_browser(): Browser
        +navigate_to_concur()
        +fill_expense_form(data)
        +submit_form()
    }

    class SSOAuth {
        +authenticate_sso(): bool
        +get_session(): Session
    }

    ConcurTools --> BrowserAutomation : uses
    BrowserAutomation --> SSOAuth : requires
```

## Expense Submission Flow

```mermaid
sequenceDiagram
    participant Tool as Concur Tool
    participant SSO as SSO Authenticator
    participant Browser as Playwright
    participant Concur as SAP Concur

    Tool->>SSO: Authenticate
    SSO->>Browser: Launch with profile
    Browser->>Concur: Navigate to Concur
    Browser->>Concur: Fill expense form
    Browser->>Concur: Upload receipt
    Browser->>Concur: Submit
    Concur-->>Tool: Submission result
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| tools_basic.py | `tool_modules/aa_concur/src/` | Concur automation tools |

## Tool Summary

| Tool | Description |
|------|-------------|
| `concur_submit_expense` | Submit a new expense report |
| `concur_list_reports` | List existing expense reports |
| `concur_check_status` | Check status of a report |

## Remote Worker Expense

The primary use case is submitting Remote Worker Expenses:

```mermaid
flowchart TB
    subgraph Input[Expense Input]
        AMOUNT[Amount: $75.00]
        DATE[Date: 2026-02-04]
        DESC[Description: Internet/Phone]
    end

    subgraph Process[Automation]
        AUTH[SSO Authentication]
        NAVIGATE[Navigate to New Expense]
        FILL[Fill Form Fields]
        ATTACH[Attach Receipt]
        SUBMIT[Submit Report]
    end

    subgraph Result[Result]
        SUCCESS[Report ID returned]
    end

    Input --> AUTH
    AUTH --> NAVIGATE
    NAVIGATE --> FILL
    FILL --> ATTACH
    ATTACH --> SUBMIT
    SUBMIT --> SUCCESS
```

## Configuration

```yaml
# config.json
concur:
  expense_type: "Remote Worker Expense"
  default_amount: 75.00
  company_code: "RHAT"
```

## Prerequisites

- Red Hat SSO authentication configured
- Shared Chrome profile with session
- Valid Concur access

## Usage Examples

```python
# Submit a remote worker expense
result = await concur_submit_expense(
    amount=75.00,
    date="2026-02-04",
    description="Monthly Internet/Phone"
)

# List recent reports
result = await concur_list_reports()

# Check report status
result = await concur_check_status("RPT12345")
```

## Related Diagrams

- [SSO Tools](./sso-tools.md)
- [Auth Flows](../07-integrations/auth-flows.md)
