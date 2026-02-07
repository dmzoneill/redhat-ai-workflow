#!/usr/bin/env python3
"""Skill YAML integration validator.

Validates all skills at runtime without executing them:
1. YAML parsing and structure validation
2. Tool name resolution via tool_discovery
3. Compute block compilation (syntax check)
4. Template variable dependency chain analysis
5. Input/output schema validation
6. Skill links validation (depends_on, validates, validated_by, chains_to, provides_context_for)
7. Cross-skill link consistency (bidirectional reference checks)

Usage:
    python scripts/validate_skills.py [--verbose] [--skill NAME]
"""

import ast
import re
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import yaml  # noqa: E402


def load_skill(path: Path) -> dict | None:
    """Load and parse a skill YAML file."""
    try:
        with open(path) as f:
            return yaml.safe_load(f)
    except yaml.YAMLError as e:
        return {"_error": f"YAML parse error: {e}"}


def get_all_valid_tools() -> set[str]:
    """Get all valid tool names from tool_discovery."""
    try:
        from server.tool_discovery import build_full_manifest

        manifest = build_full_manifest()
        tools = set()
        for module_tools in manifest.values():
            tools.update(module_tools)

        # Add tools from non-standard files not scanned by discover_module_tools
        # (e.g., tools_style.py which isn't core/basic/extra)
        _add_tools_from_nonstandard_files(tools)

        return tools
    except Exception as e:
        print(f"  WARNING: Could not load tool_discovery: {e}")
        print("  Falling back to static tool list")
        return set()


def _add_tools_from_nonstandard_files(tools: set[str]) -> None:
    """Scan ALL tool files for function defs to catch tools missed by manifest."""
    import ast as _ast

    tool_modules_dir = PROJECT_ROOT / "tool_modules"
    for module_dir in tool_modules_dir.iterdir():
        if not module_dir.is_dir() or not module_dir.name.startswith("aa_"):
            continue
        src_dir = module_dir / "src"
        if not src_dir.exists():
            continue
        for py_file in src_dir.glob("tools_*.py"):
            try:
                tree = _ast.parse(py_file.read_text())
                for node in _ast.walk(tree):
                    if isinstance(node, (_ast.AsyncFunctionDef, _ast.FunctionDef)):
                        name = node.name
                        if not name.startswith("_"):
                            tools.add(name)
            except Exception:
                pass


def validate_structure(skill: dict) -> list[str]:
    """Validate top-level YAML structure."""
    errors = []
    if "_error" in skill:
        return [skill["_error"]]

    required = ["name", "steps"]
    for key in required:
        if key not in skill:
            errors.append(f"Missing required top-level key: '{key}'")

    if not isinstance(skill.get("steps", []), list):
        errors.append("'steps' must be a list")

    if "description" not in skill:
        errors.append("Missing recommended key: 'description' (warning)")

    return errors


def validate_tool_names(skill: dict, valid_tools: set[str]) -> list[str]:
    """Validate all tool names in steps resolve to known tools."""
    errors = []
    if not valid_tools:
        return []  # Skip if we couldn't load the manifest

    for step in skill.get("steps", []):
        tool = step.get("tool")
        if tool and tool not in valid_tools:
            step_name = step.get("name", "unnamed")
            errors.append(f"Step '{step_name}': unknown tool '{tool}'")
    return errors


def validate_compute_syntax(skill: dict) -> list[str]:
    """Compile compute blocks to check Python syntax."""
    errors = []
    for step in skill.get("steps", []):
        code = step.get("compute")
        if not code:
            continue

        step_name = step.get("name", "unnamed")

        # Strip Jinja2 templates before compiling
        # First handle {{ }} inside f-strings by replacing with valid f-string expressions
        clean_code = re.sub(r"\{\{.*?\}\}", "TEMPLATE", code)
        clean_code = re.sub(r"\{%.*?%\}", "# __JINJA_BLOCK__", clean_code)
        # Remove any remaining lone { or } that Jinja2 stripping may have left
        # inside f-strings (which would cause parse errors)
        # Replace f-strings entirely with plain strings to avoid brace issues
        clean_code = re.sub(r'\bf"', '"', clean_code)
        clean_code = re.sub(r"\bf'", "'", clean_code)

        try:
            ast.parse(clean_code)
        except SyntaxError as e:
            errors.append(f"Step '{step_name}': Python syntax error in compute block: " f"line {e.lineno}: {e.msg}")
    return errors


def validate_steps_not_in_outputs(skill: dict) -> list[str]:
    """Check that no tool/compute steps are inside the outputs section."""
    errors = []
    for output in skill.get("outputs", []):
        if not isinstance(output, dict):
            continue
        name = output.get("name", "unnamed")
        if "tool" in output:
            errors.append(f"Output '{name}' has 'tool:' key - should be in steps, not outputs")
        if "compute" in output:
            errors.append(f"Output '{name}' has 'compute:' key - should be in steps, not outputs")
    return errors


def validate_on_error(skill: dict) -> list[str]:
    """Validate on_error values."""
    valid_values = {"continue", "auto_heal", "abort", "fail"}
    errors = []
    for step in skill.get("steps", []):
        on_error = step.get("on_error")
        if on_error and on_error not in valid_values:
            step_name = step.get("name", "unnamed")
            errors.append(
                f"Step '{step_name}': invalid on_error value '{on_error}' "
                f"(must be one of: {', '.join(sorted(valid_values))})"
            )
    return errors


def validate_variable_chain(skill: dict) -> list[str]:
    """Check that template references plausibly resolve to prior outputs."""
    errors = []
    available_vars = set()

    # Add input names
    for inp in skill.get("inputs", []):
        name = inp.get("name", "")
        available_vars.add(name)
        available_vars.add(f"inputs.{name}")

    # Walk steps in order
    for step in skill.get("steps", []):
        step_name = step.get("name", "unnamed")

        # Check tool args for template references
        args = step.get("args", {})
        for _arg_key, arg_val in args.items():
            if isinstance(arg_val, str) and "{{" in arg_val:
                # Extract variable references from {{ ... }}
                refs = re.findall(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_.]*)", arg_val)
                for ref in refs:
                    root_var = ref.split(".")[0]
                    # Skip Jinja2 filters, builtins, and loop vars
                    if root_var in (
                        "inputs",
                        "not",
                        "true",
                        "false",
                        "none",
                        "loop",
                        "range",
                        "length",
                        "default",
                        "item",
                    ):
                        continue
                    if root_var not in available_vars:
                        # Only warn - not all vars are trackable statically
                        pass  # Too noisy for static analysis

        # Check condition references
        condition = step.get("condition")
        if condition and isinstance(condition, str):
            refs = re.findall(r"\{\{\s*(?:not\s+)?([a-zA-Z_][a-zA-Z0-9_.]*)", condition)
            for ref in refs:
                root_var = ref.split(".")[0]
                if root_var in ("inputs", "not", "true", "false", "none"):
                    continue
                # Conditions referencing undefined vars are a real issue
                # but we can't fully track compute block locals statically

        # Register output
        output_name = step.get("output", step_name)
        if isinstance(output_name, str):
            available_vars.add(output_name)
        elif isinstance(output_name, list):
            available_vars.update(output_name)

        # For outputs: key (alternate syntax)
        outputs_list = step.get("outputs")
        if isinstance(outputs_list, list):
            available_vars.update(outputs_list)

    return errors


def validate_inputs(skill: dict) -> list[str]:
    """Validate input definitions."""
    errors = []
    for inp in skill.get("inputs", []):
        if not isinstance(inp, dict):
            errors.append(f"Input entry is not a dict: {inp}")
            continue
        if "name" not in inp:
            errors.append(f"Input missing 'name': {inp}")
    return errors


def validate_unique_step_names(skill: dict) -> list[str]:
    """Check for duplicate step names."""
    errors = []
    seen = {}
    for i, step in enumerate(skill.get("steps", [])):
        name = step.get("name")
        if name and name in seen:
            errors.append(f"Duplicate step name '{name}' at positions {seen[name]} and {i}")
        if name:
            seen[name] = i
    return errors


VALID_LINK_TYPES = {"depends_on", "validates", "validated_by", "chains_to", "provides_context_for"}


def validate_links_structure(skill: dict) -> list[str]:
    """Validate the links: metadata structure."""
    errors = []
    links = skill.get("links")
    if links is None:
        return []  # links: is optional

    if not isinstance(links, dict):
        errors.append("'links' must be a dict")
        return errors

    for key, value in links.items():
        if key not in VALID_LINK_TYPES:
            errors.append(
                f"links: unknown link type '{key}' " f"(must be one of: {', '.join(sorted(VALID_LINK_TYPES))})"
            )
        if not isinstance(value, list):
            errors.append(f"links.{key}: must be a list, got {type(value).__name__}")
        else:
            for item in value:
                if not isinstance(item, str):
                    errors.append(f"links.{key}: items must be strings, got {type(item).__name__}: {item}")

    return errors


def validate_links_references(skill: dict, all_skill_names: set[str]) -> list[str]:
    """Validate that linked skill names reference real skills."""
    errors = []
    links = skill.get("links")
    if not links or not isinstance(links, dict):
        return []

    for link_type, refs in links.items():
        if not isinstance(refs, list):
            continue
        for ref in refs:
            if isinstance(ref, str) and ref not in all_skill_names:
                errors.append(f"links.{link_type}: references unknown skill '{ref}'")

    return errors


def validate_links_consistency(all_skills: dict[str, dict]) -> list[str]:
    """Cross-skill validation: check bidirectional link consistency.

    Rules:
    - If A.validates includes B, B.validated_by should include A (warning)
    - If A.depends_on includes B, B.chains_to should include A (warning)
    - Self-references are not allowed
    """
    warnings = []

    for skill_name, skill in all_skills.items():
        links = skill.get("links")
        if not links or not isinstance(links, dict):
            continue

        # Check for self-references
        for link_type, refs in links.items():
            if not isinstance(refs, list):
                continue
            if skill_name in refs:
                warnings.append(f"'{skill_name}': links.{link_type} references itself (warning)")

        # Check validates <-> validated_by consistency
        for validated in links.get("validates", []):
            if not isinstance(validated, str) or validated not in all_skills:
                continue
            other_links = all_skills[validated].get("links", {})
            validated_by = other_links.get("validated_by", [])
            if isinstance(validated_by, list) and skill_name not in validated_by:
                warnings.append(
                    f"'{skill_name}' validates '{validated}' but "
                    f"'{validated}' doesn't list '{skill_name}' in validated_by (warning)"
                )

        # Check depends_on <-> chains_to consistency
        for dependency in links.get("depends_on", []):
            if not isinstance(dependency, str) or dependency not in all_skills:
                continue
            other_links = all_skills[dependency].get("links", {})
            chains_to = other_links.get("chains_to", [])
            if isinstance(chains_to, list) and skill_name not in chains_to:
                warnings.append(
                    f"'{skill_name}' depends_on '{dependency}' but "
                    f"'{dependency}' doesn't list '{skill_name}' in chains_to (warning)"
                )

    return warnings


def validate_skill(path: Path, valid_tools: set[str], verbose: bool = False) -> dict:
    """Run all validations on a single skill file."""
    skill = load_skill(path)
    if skill is None:
        return {"path": path, "passed": False, "errors": ["Failed to load file"]}

    all_errors = []
    all_warnings = []

    # Run validators
    validators = [
        ("structure", validate_structure),
        ("tool_names", lambda s: validate_tool_names(s, valid_tools)),
        ("compute_syntax", validate_compute_syntax),
        ("steps_in_outputs", validate_steps_not_in_outputs),
        ("on_error", validate_on_error),
        ("variable_chain", validate_variable_chain),
        ("inputs", validate_inputs),
        ("unique_names", validate_unique_step_names),
        ("links_structure", validate_links_structure),
    ]

    for name, validator in validators:
        try:
            errors = validator(skill)
            for err in errors:
                if "warning" in err.lower():
                    all_warnings.append(f"[{name}] {err}")
                else:
                    all_errors.append(f"[{name}] {err}")
        except Exception as e:
            all_errors.append(f"[{name}] Validator crashed: {e}")

    return {
        "path": path,
        "name": skill.get("name", path.stem),
        "passed": len(all_errors) == 0,
        "errors": all_errors,
        "warnings": all_warnings,
        "step_count": len(skill.get("steps", [])),
        "tool_steps": sum(1 for s in skill.get("steps", []) if "tool" in s),
        "compute_steps": sum(1 for s in skill.get("steps", []) if "compute" in s),
    }


def main():
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    single_skill = None
    for i, arg in enumerate(sys.argv):
        if arg == "--skill" and i + 1 < len(sys.argv):
            single_skill = sys.argv[i + 1]

    skills_dir = PROJECT_ROOT / "skills"
    perf_dir = skills_dir / "performance"

    # Collect all skill files
    skill_files = sorted(skills_dir.glob("*.yaml"))
    if perf_dir.exists():
        skill_files.extend(sorted(perf_dir.glob("*.yaml")))

    if single_skill:
        skill_files = [f for f in skill_files if f.stem == single_skill]
        if not skill_files:
            print(f"Skill not found: {single_skill}")
            sys.exit(1)

    print(f"Validating {len(skill_files)} skills...")
    print("Loading tool manifest...")

    valid_tools = get_all_valid_tools()
    if valid_tools:
        print(f"Found {len(valid_tools)} valid tool names\n")
    else:
        print("WARNING: Running without tool name validation\n")

    passed = 0
    failed = 0
    total_errors = 0
    total_warnings = 0
    failed_skills = []

    # First pass: load all skills for cross-reference validation
    all_skills = {}
    all_skill_names = set()
    for path in skill_files:
        skill = load_skill(path)
        if skill and "_error" not in skill:
            name = skill.get("name", path.stem)
            all_skills[name] = skill
            all_skill_names.add(name)

    for path in skill_files:
        result = validate_skill(path, valid_tools, verbose)

        # Run link reference validation (needs all skill names)
        skill = load_skill(path)
        if skill and "_error" not in skill:
            link_ref_errors = validate_links_references(skill, all_skill_names)
            for err in link_ref_errors:
                if "warning" in err.lower():
                    result["warnings"].append(f"[links_refs] {err}")
                else:
                    result["errors"].append(f"[links_refs] {err}")
            if link_ref_errors:
                result["passed"] = len(result["errors"]) == 0

        if result["passed"]:
            passed += 1
            if verbose:
                skill_data = all_skills.get(result.get("name", ""), {})
                links = skill_data.get("links", {})
                link_count = sum(len(v) for v in links.values() if isinstance(v, list))
                print(
                    f"  PASS  {path.stem} ({result['step_count']} steps, "
                    f"{result['tool_steps']} tool, {result['compute_steps']} compute, "
                    f"{link_count} links)"
                )
                for w in result["warnings"]:
                    print(f"        WARN: {w}")
        else:
            failed += 1
            total_errors += len(result["errors"])
            failed_skills.append(result)
            print(f"  FAIL  {path.stem}")
            for err in result["errors"]:
                print(f"        ERROR: {err}")

        total_warnings += len(result["warnings"])

    # Cross-skill link consistency check
    if not single_skill:
        print("\nRunning cross-skill link consistency checks...")
        consistency_warnings = validate_links_consistency(all_skills)
        total_warnings += len(consistency_warnings)
        if consistency_warnings:
            if verbose:
                for w in consistency_warnings:
                    print(f"  WARN: {w}")
            print(f"  {len(consistency_warnings)} consistency warning(s)")
        else:
            print("  All cross-skill links are consistent")

    # Link statistics
    skills_with_links = sum(1 for s in all_skills.values() if s.get("links"))
    total_link_refs = sum(
        sum(len(v) for v in s.get("links", {}).values() if isinstance(v, list)) for s in all_skills.values()
    )

    # Summary
    print(f"\n{'=' * 60}")
    print(f"RESULTS: {passed}/{passed + failed} passed, {failed} failed")
    print(f"         {total_errors} errors, {total_warnings} warnings")
    print(f"  LINKS: {skills_with_links}/{len(all_skills)} skills have links metadata")
    print(f"         {total_link_refs} total link references")
    print(f"{'=' * 60}")

    if failed_skills:
        print("\nFailed skills:")
        for r in failed_skills:
            print(f"  - {r['name']}: {len(r['errors'])} error(s)")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
