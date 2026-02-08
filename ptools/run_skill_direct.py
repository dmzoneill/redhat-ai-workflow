import asyncio
import sys
from pathlib import Path

# Add project root to sys.path first to ensure 'server' package is found correctly
PROJECT_ROOT = Path(__file__).parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Add tool_modules/aa_workflow/src to sys.path after root
WORKFLOW_SRC = PROJECT_ROOT / "tool_modules" / "aa_workflow" / "src"
if str(WORKFLOW_SRC) not in sys.path:
    sys.path.append(str(WORKFLOW_SRC))

import yaml  # noqa: E402
from skill_engine import SkillExecutor, SkillExecutorConfig  # noqa: E402


async def run_coffee():
    skill_file = PROJECT_ROOT / "skills" / "coffee.yaml"
    with open(skill_file) as f:
        skill = yaml.safe_load(f)

    # Inputs for coffee skill
    inputs = {
        "full_email_scan": False,
        "auto_archive_email": False,
        "days_back": 1,
        "slack_format": False,
    }

    direct_config = SkillExecutorConfig(debug=True, emit_events=False)
    executor = SkillExecutor(
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
