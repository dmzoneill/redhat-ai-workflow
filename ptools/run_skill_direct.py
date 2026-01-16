import asyncio
import json
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

from skill_engine import SkillExecutor
import yaml

async def run_coffee():
    skill_file = PROJECT_ROOT / "skills" / "coffee.yaml"
    with open(skill_file) as f:
        skill = yaml.safe_load(f)
    
    # Inputs for coffee skill
    inputs = {
        "full_email_scan": False,
        "auto_archive_email": False,
        "days_back": 1,
        "slack_format": False
    }
    
    executor = SkillExecutor(
        skill=skill,
        inputs=inputs,
        debug=True,
        server=None, # We'll let it load modules dynamically
        emit_events=False
    )
    
    print("Starting coffee skill...")
    result = await executor.execute()
    print("\n--- RESULT ---\n")
    print(result)

if __name__ == "__main__":
    asyncio.run(run_coffee())
