# 🔄 Memory Initialize

Initialize or reset memory files to a clean state.

## Usage

**Reset state files only (preserves learned patterns):**
```text
skill_run("memory_init", '{"confirm": true}')
```

**Full reset (including learned memory):**
```text
skill_run("memory_init", '{"confirm": true, "reset_learned": true}')
```

**Full reset but keep patterns:**
```text
skill_run("memory_init", '{"confirm": true, "reset_learned": true, "preserve_patterns": true}')
```

## What Gets Reset

### State Files (always reset)
- `state/current_work.yaml` - Active issues, open MRs, follow-ups
- `state/environments.yaml` - Environment status, ephemeral namespaces

### Learned Files (only with reset_learned=true)
- `learned/runbooks.yaml` - Operational procedures
- `learned/teammate_preferences.yaml` - Review preferences
- `learned/service_quirks.yaml` - Service behaviors
- `learned/patterns.yaml` - Error patterns (preserved by default)

## When to Use

- Starting a new sprint or project
- After extended time away from the codebase
- Setting up on a new machine
- Clearing test data after experimentation
