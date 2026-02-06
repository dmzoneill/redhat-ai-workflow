# Pattern Miner

> Auto-discover error patterns from tool failures

## Diagram

```mermaid
graph TB
    subgraph Input[Input Files]
        FAILURES[tool_failures.yaml]
        PATTERNS[patterns.yaml]
    end

    subgraph Mining[Pattern Mining]
        LOAD[Load Failures]
        GROUP[Group by Similarity]
        FILTER[Filter Existing]
        SUGGEST[Suggest New Patterns]
    end

    subgraph Output[Output]
        REPORT[Suggested Patterns]
        COUNTS[Frequency Counts]
    end

    FAILURES --> LOAD
    PATTERNS --> FILTER
    LOAD --> GROUP --> FILTER --> SUGGEST
    SUGGEST --> REPORT
    SUGGEST --> COUNTS
```

## Mining Process

```mermaid
sequenceDiagram
    participant Failures as tool_failures.yaml
    participant Miner as Pattern Miner
    participant Patterns as patterns.yaml
    participant Output as Suggestions

    Miner->>Failures: Load last 500 failures
    Miner->>Patterns: Load existing patterns

    loop For each failure
        Miner->>Miner: Extract error snippet
        Miner->>Miner: Compare with groups (75% similarity)
        alt Similar group exists
            Miner->>Miner: Increment count
        else No match
            Miner->>Miner: Create new group
        end
    end

    Miner->>Miner: Filter groups < 5 occurrences
    Miner->>Miner: Filter already captured patterns
    Miner->>Output: Suggest new patterns
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| mine_patterns_from_failures | `scripts/pattern_miner.py` | Main mining function |

## Algorithm

1. **Load Failures**: Read last 500 entries from `tool_failures.yaml`
2. **Group by Similarity**: Use SequenceMatcher with 75% threshold
3. **Count Occurrences**: Track frequency of each error group
4. **Filter Threshold**: Only suggest patterns with 5+ occurrences
5. **Filter Existing**: Exclude errors already in `patterns.yaml`

## Usage

```bash
# Run pattern mining
python scripts/pattern_miner.py

# Scheduled via skill
/suggest-patterns
```

## Output Example

```yaml
suggested_patterns:
  - pattern: "manifest unknown"
    count: 12
    tool: bonfire_deploy
    examples:
      - "Error: manifest unknown: abc123"
      - "Error: manifest unknown: def456"
    suggested_fix: "Use full 40-char SHA instead of short SHA"

  - pattern: "connection refused"
    count: 8
    tool: k8s_get_pods
    examples:
      - "Error: connection refused to cluster"
    suggested_fix: "Run kube_login first"
```

## Integration with Layer 5

The pattern miner feeds into the Layer 5 usage pattern system:

```mermaid
graph LR
    FAILURES[Tool Failures] --> MINER[Pattern Miner]
    MINER --> PATTERNS[patterns.yaml]
    PATTERNS --> CHECKER[Usage Checker]
    CHECKER --> WARNINGS[Pre-call Warnings]
```

## Related Diagrams

- [Usage Pattern System](../01-server/usage-pattern-system.md)
- [Auto-Heal Decorator](../01-server/auto-heal-decorator.md)
- [Layer 5 Dashboard](./layer5-dashboard.md)
