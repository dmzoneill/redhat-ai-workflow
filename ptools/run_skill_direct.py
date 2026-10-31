"""Run the coffee skill directly through SkillExecutor (debug helper)."""

import asyncio
import importlib
import sys
from pathlib import Path

import yaml

# Repo root (this script lives in ptools/); added to sys.path first so the server package resolves
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Add tool_modules/aa_workflow/src to sys.path after root
WORKFLOW_SRC = PROJECT_ROOT / "tool_modules" / "aa_workflow" / "src"
if str(WORKFLOW_SRC) not in sys.path:
    sys.path.append(str(WORKFLOW_SRC))


async def run_coffee() -> None:
    """Load skills/coffee.yaml and execute it with debug output."""
    # Imported after sys.path setup above (skill_engine lives in tool_modules/aa_workflow/src).
    skill_engine = importlib.import_module("skill_engine")

    skill_file = PROJECT_ROOT / "skills" / "coffee.yaml"
    skill = yaml.safe_load(await asyncio.to_thread(skill_file.read_text, encoding="utf-8"))

    # Inputs for coffee skill
    inputs = {
        "full_email_scan": False,
        "auto_archive_email": False,
        "days_back": 1,
        "slack_format": False,
    }

    direct_config = skill_engine.SkillExecutorConfig(debug=True, emit_events=False)
    executor = skill_engine.SkillExecutor(
        skill=skill,
        inputs=inputs,
        config=direct_config,
        server=None,  # We'll let it load modules dynamically
    )

    print("Starting coffee skill...")
    result = await executor.execute()
    print("\n--- RESULT ---\n")
    print(result)


if __name__ == "__main__":
    asyncio.run(run_coffee())
