# Smoke Test Skills

Run the skill test runner to validate all skills work correctly.

```bash
cd /home/daoneill/src/redhat-ai-workflow && source ~/bonfire_venv/bin/activate && python scripts/skill_test_runner.py
```

This will:
1. Parse all skill YAML files
2. Execute tool steps with safe test parameters
3. Skip excluded/production-impacting skills
4. Report pass/fail for each skill

Expected: 15 skills tested, 15 passed, 9 excluded
