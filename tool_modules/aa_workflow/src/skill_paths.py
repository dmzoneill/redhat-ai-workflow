# pylint: disable=duplicate-code,cyclic-import
"""Runtime lookups for names tests patch on skill_engine."""


def skills_dir():
    """Return the skills directory, honoring patches on skill_engine.SKILLS_DIR."""
    # Lazy import: skill_engine imports the modules that call this helper.
    from tool_modules.aa_workflow.src import (  # pylint: disable=import-outside-toplevel
        skill_engine as engine,  # pylint: disable=import-outside-toplevel
    )

    return engine.SKILLS_DIR


def tool_modules_dir():
    """Return tool module root, honoring patches on skill_engine.TOOL_MODULES_DIR."""
    from tool_modules.aa_workflow.src import (  # pylint: disable=import-outside-toplevel
        skill_engine as engine,  # pylint: disable=import-outside-toplevel
    )

    return engine.TOOL_MODULES_DIR
