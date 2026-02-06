# Usage Pattern System

> Learning and optimization from tool usage patterns

## Diagram

```mermaid
flowchart TB
    subgraph Input[Tool Execution]
        TOOL_CALL[Tool Call]
        RESULT[Tool Result]
        CONTEXT[Execution Context]
    end

    subgraph Extraction[Pattern Extraction]
        EXTRACTOR[usage_pattern_extractor.py]
        EXTRACT_PATTERN[Extract pattern from call]
    end

    subgraph Classification[Pattern Classification]
        CLASSIFIER[usage_pattern_classifier.py]
        CLASSIFY[Classify pattern type]
        CATEGORIES[success/failure/retry/timeout]
    end

    subgraph Checking[Pattern Checking]
        CHECKER[usage_pattern_checker.py]
        CHECK_SIMILAR[Find similar patterns]
        SUGGEST[Suggest improvements]
    end

    subgraph Learning[Pattern Learning]
        LEARNER[usage_pattern_learner.py]
        LEARN[Learn from outcome]
        UPDATE_WEIGHTS[Update pattern weights]
    end

    subgraph Storage[Pattern Storage]
        STORAGE[usage_pattern_storage.py]
        YAML_FILE[(patterns.yaml)]
    end

    subgraph Optimization[Pattern Optimization]
        OPTIMIZER[usage_pattern_optimizer.py]
        OPTIMIZE[Optimize tool selection]
        RANK[Rank alternatives]
    end

    subgraph Prevention[Prevention Tracking]
        PREVENTION[usage_prevention_tracker.py]
        TRACK_FAILURES[Track failure patterns]
        PREVENT[Prevent known failures]
    end

    TOOL_CALL --> EXTRACTOR
    RESULT --> EXTRACTOR
    CONTEXT --> EXTRACTOR

    EXTRACTOR --> CLASSIFIER
    CLASSIFIER --> CHECKER
    CHECKER --> LEARNER
    LEARNER --> STORAGE
    STORAGE --> YAML_FILE

    CHECKER --> OPTIMIZER
    OPTIMIZER --> PREVENTION

    YAML_FILE --> CHECKER
    YAML_FILE --> OPTIMIZER
    YAML_FILE --> PREVENTION
```

## Module Relationships

```mermaid
classDiagram
    class UsagePatternExtractor {
        +extract_pattern(tool, args, result): Pattern
        +extract_context(): Context
    }

    class UsagePatternClassifier {
        +classify(pattern): Classification
        +get_category(pattern): str
        +get_confidence(pattern): float
    }

    class UsagePatternChecker {
        +check_pattern(pattern): CheckResult
        +find_similar(pattern): list~Pattern~
        +suggest_improvements(pattern): list~str~
    }

    class UsagePatternLearner {
        +learn(pattern, outcome)
        +update_weights(pattern, success)
        +get_learned_patterns(): list~Pattern~
    }

    class UsagePatternStorage {
        +save(pattern)
        +load(): list~Pattern~
        +query(criteria): list~Pattern~
    }

    class UsagePatternOptimizer {
        +optimize(tool, context): Suggestion
        +rank_alternatives(tools): list~Tool~
    }

    class UsagePreventionTracker {
        +track_failure(tool, error)
        +should_prevent(tool, context): bool
        +get_prevention_rules(): list~Rule~
    }

    UsagePatternExtractor --> UsagePatternClassifier
    UsagePatternClassifier --> UsagePatternChecker
    UsagePatternChecker --> UsagePatternLearner
    UsagePatternLearner --> UsagePatternStorage
    UsagePatternChecker --> UsagePatternOptimizer
    UsagePatternOptimizer --> UsagePreventionTracker
```

## Pattern Flow

```mermaid
sequenceDiagram
    participant Tool as Tool Execution
    participant Extractor as Extractor
    participant Classifier as Classifier
    participant Checker as Checker
    participant Learner as Learner
    participant Storage as Storage

    Tool->>Extractor: Tool call + result
    Extractor->>Extractor: Extract pattern
    Extractor->>Classifier: Pattern data

    Classifier->>Classifier: Classify type
    Classifier->>Checker: Classified pattern

    Checker->>Storage: Query similar patterns
    Storage-->>Checker: Similar patterns
    Checker->>Checker: Compare and suggest

    alt Pattern is new/improved
        Checker->>Learner: Learn pattern
        Learner->>Learner: Update weights
        Learner->>Storage: Save pattern
    end

    Checker-->>Tool: Suggestions/warnings
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| UsagePatternExtractor | `server/usage_pattern_extractor.py` | Extract patterns from calls |
| UsagePatternClassifier | `server/usage_pattern_classifier.py` | Classify pattern types |
| UsagePatternChecker | `server/usage_pattern_checker.py` | Check against known patterns |
| UsagePatternLearner | `server/usage_pattern_learner.py` | Learn from outcomes |
| UsagePatternStorage | `server/usage_pattern_storage.py` | Persist patterns to YAML |
| UsagePatternOptimizer | `server/usage_pattern_optimizer.py` | Optimize tool selection |
| UsagePreventionTracker | `server/usage_prevention_tracker.py` | Track and prevent failures |
| UsageContextInjector | `server/usage_context_injector.py` | Inject context into calls |

## Pattern Categories

| Category | Description | Example |
|----------|-------------|---------|
| success | Tool completed successfully | `jira_view_issue` returned issue |
| failure | Tool failed with error | Auth error, timeout |
| retry | Tool succeeded after retry | Auto-heal fixed auth |
| timeout | Tool timed out | Network unreachable |
| prevented | Call prevented due to pattern | Known bad input |

## Related Diagrams

- [Auto-Heal Decorator](./auto-heal-decorator.md)
- [Memory Architecture](../06-memory/memory-architecture.md)
- [Tool Registry](./tool-registry.md)
