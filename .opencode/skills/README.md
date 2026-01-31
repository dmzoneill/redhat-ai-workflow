# OpenCode Skills

This directory contains OpenCode-compatible skill definitions that tell the AI to invoke the MCP skill engine.

## What Are These?

These `SKILL.md` files are **instruction-based skills** for OpenCode/Claude Code. They tell the AI:
1. When to use each skill
2. What inputs are required
3. How to invoke the MCP skill engine

## How They Work

```
User: "Start work on AAP-12345"
  ↓
OpenCode AI reads: .opencode/skills/start-work/SKILL.md
  ↓
AI learns: "I should call skill_run('start_work', '{...}')"
  ↓
AI invokes: MCP skill engine
  ↓
MCP engine executes: skills/start_work.yaml (the actual workflow)
```

## Relationship to MCP Skills

| File Type | Location | Purpose |
|-----------|----------|---------|
| **YAML Skills** | `skills/*.yaml` | Executable workflows (Python + MCP tools) |
| **SKILL.md** | `.opencode/skills/*/SKILL.md` | Instructions for the AI |

The SKILL.md files are **generated from** the YAML skills - they're not manually edited.

## Regenerating Skills

When you add or modify a YAML skill in `skills/`, regenerate the OpenCode skills:

```bash
make sync-opencode-skills
```

Or run directly:

```bash
python scripts/convert_skills_to_opencode.py
```

This will:
1. Read all `skills/*.yaml` files
2. Generate `.opencode/skills/<name>/SKILL.md` (OpenCode format)
3. Generate `.claude/skills/<name>/SKILL.md` (Claude Code format)

## Validation

OpenCode requires:
- ✅ YAML frontmatter with `name` and `description`
- ✅ Skill names: lowercase, alphanumeric, hyphens (e.g., `start-work`)
- ✅ Description: 1-1024 characters
- ✅ File: `SKILL.md` (all caps)
- ✅ Directory: `.opencode/skills/<name>/SKILL.md`

All generated skills follow these rules automatically.

## File Structure

```
.opencode/
└── skills/
    ├── README.md (this file)
    ├── start-work/
    │   └── SKILL.md
    ├── coffee/
    │   └── SKILL.md
    └── ...
```

## OpenCode Discovery

OpenCode automatically discovers skills from:
1. `.opencode/skills/*/SKILL.md` (project-local)
2. `~/.config/opencode/skills/*/SKILL.md` (global)
3. `.claude/skills/*/SKILL.md` (Claude Code compatibility)

## Permissions

Control which skills OpenCode can access in `opencode.json`:

```json
{
  "permission": {
    "skill": {
      "*": "allow",           // Allow all by default
      "debug-*": "ask",       // Prompt for debug skills
      "dangerous-*": "deny"   // Block dangerous skills
    }
  }
}
```

## More Information

- [OpenCode Skills Documentation](https://opencode.ai/docs/skills/)
- [MCP Skill Engine](../../docs/architecture/skill-engine.md)
- [Skill Development Guide](../../docs/skills/README.md)
