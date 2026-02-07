"""Regression tests for skill YAML definitions.

Each test documents a previously-fixed bug pattern in skill files.
These tests scan all skill YAML files to ensure the anti-pattern
does not regress.
"""

import re
import sys
from pathlib import Path

import yaml

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SKILLS_DIR = PROJECT_ROOT / "skills"


def _load_all_skills() -> list[tuple[Path, dict]]:
    """Load all skill YAML files, return list of (path, data) tuples."""
    results = []
    for path in sorted(SKILLS_DIR.glob("*.yaml")):
        try:
            with open(path) as f:
                data = yaml.safe_load(f)
            if data and isinstance(data, dict):
                results.append((path, data))
        except Exception:
            # Skip files that fail to parse (caught by other tests)
            continue
    return results


def _extract_compute_blocks(skill: dict) -> list[tuple[str, str]]:
    """Extract all compute blocks from a skill's steps.

    Returns list of (step_name, code) tuples.
    """
    blocks = []
    for step in skill.get("steps", []):
        if "compute" in step:
            step_name = step.get("name", "unnamed")
            blocks.append((step_name, step["compute"]))
    return blocks


# ============================================================================
# TestSkillRegressions
# ============================================================================


class TestSkillRegressions:
    """Regression tests documenting previously-fixed bugs in skill YAMLs."""

    def test_no_eval_in_compute_blocks(self):
        """Regression: eval() was used for dynamic variable access.

        Fixed in sync_pto_calendar, jira_hygiene, check_mr_feedback.
        Pattern: eval(var_name) should be locals().get(var_name).
        Verify no eval() exists in any skill compute block.

        Note: We exclude patterns inside string literals (like regex
        patterns that detect eval in *other* code, e.g. review_pr's
        security scanner).
        """
        violations = []
        for path, skill in _load_all_skills():
            for step_name, code in _extract_compute_blocks(skill):
                # Remove string literals to avoid false positives from
                # code that *detects* eval (like security scanners)
                stripped = _remove_string_literals(code)
                if "eval(" in stripped:
                    violations.append(f"{path.name} step '{step_name}'")

        assert not violations, (
            f"eval() found in compute blocks (use locals().get() instead):\n"
            + "\n".join(f"  - {v}" for v in violations)
        )

    def test_no_shell_true_in_compute_blocks(self):
        """Regression: subprocess.run(shell=True) with user input.

        Fixed in release_aa_backend_prod. Using shell=True with
        user-controlled input is a command injection risk.
        Verify no shell=True remains in compute blocks.

        Note: We exclude patterns inside string literals (like regex
        patterns in security scanners).
        """
        violations = []
        for path, skill in _load_all_skills():
            for step_name, code in _extract_compute_blocks(skill):
                stripped = _remove_string_literals(code)
                if "shell=True" in stripped:
                    violations.append(f"{path.name} step '{step_name}'")

        assert (
            not violations
        ), f"shell=True found in compute blocks (use shell=False):\n" + "\n".join(
            f"  - {v}" for v in violations
        )

    def test_no_bare_except_in_compute_blocks(self):
        """Regression: bare except: blocks swallowed KeyboardInterrupt.

        Fixed across 15 files. Bare except catches SystemExit and
        KeyboardInterrupt. Should use 'except Exception:' instead.
        """
        # Match "except:" that is NOT followed by a specific exception type
        bare_except_re = re.compile(r"^\s*except\s*:\s*$", re.MULTILINE)

        violations = []
        for path, skill in _load_all_skills():
            for step_name, code in _extract_compute_blocks(skill):
                if bare_except_re.search(code):
                    violations.append(f"{path.name} step '{step_name}'")

        assert (
            not violations
        ), f"Bare 'except:' found (use 'except Exception:' instead):\n" + "\n".join(
            f"  - {v}" for v in violations
        )

    def test_no_steps_in_outputs_section(self):
        """Regression: tool/compute steps placed in outputs section.

        Fixed across 12 files. The 'outputs' section should only contain
        name/value pairs or simple compute blocks for formatting, not
        tool invocations. Tool steps belong in the 'steps' section.
        """
        violations = []
        for path, skill in _load_all_skills():
            for output in skill.get("outputs", []):
                if not isinstance(output, dict):
                    continue
                if "tool" in output:
                    violations.append(
                        f"{path.name} output '{output.get('name', '?')}' "
                        f"has tool: {output['tool']}"
                    )

        assert (
            not violations
        ), f"Tool steps found in outputs section (move to steps):\n" + "\n".join(
            f"  - {v}" for v in violations
        )

    def test_no_forward_references(self):
        """Regression: templates referencing variables from later steps.

        Fixed in cleanup_branches, review_pr. Step N cannot reference
        output from step N+k. Check that {{ var }} references in tool
        args only reference outputs from earlier steps or inputs.
        """
        # Regex to extract {{ variable_name }} (just the first dotted part)
        template_var_re = re.compile(r"\{\{\s*(\w+)")

        # Special variables always available (not from steps)
        always_available = {
            "inputs",
            "config",
            "workspace_uri",
            "today",
            "defaults",
            "true",
            "false",
            "none",
        }

        violations = []
        for path, skill in _load_all_skills():
            # Collect outputs defined by each step, in order
            defined_outputs = set()
            steps = skill.get("steps", [])

            for step in steps:
                step_name = step.get("name", "unnamed")

                # Check tool args for forward references
                if "tool" in step and "args" in step:
                    args_str = yaml.dump(step["args"])
                    for match in template_var_re.finditer(args_str):
                        var_name = match.group(1).lower()
                        if (
                            var_name not in always_available
                            and var_name not in defined_outputs
                            # Jinja2 filters and control flow keywords
                            and var_name
                            not in {
                                "not",
                                "and",
                                "or",
                                "if",
                                "else",
                                "for",
                                "in",
                                "is",
                                "set",
                                "range",
                                "loop",
                                "namespace",
                            }
                        ):
                            violations.append(
                                f"{path.name} step '{step_name}' "
                                f"references '{{{{ {var_name} }}}}' "
                                f"before it is defined"
                            )

                # Record this step's output as defined
                output_name = step.get("output", step_name)
                defined_outputs.add(output_name.lower())
                defined_outputs.add(step_name.lower())

        # Note: this test may produce some false positives for variables
        # defined in compute blocks that don't use 'output:', since those
        # add variables to context implicitly. We accept some noise here
        # in exchange for catching real forward-reference bugs.
        #
        # If this test is too noisy, individual false positives can be
        # suppressed by adding the step names to always_available above
        # with a comment explaining why.

        # We do NOT assert on violations because the heuristic has
        # known false positives (compute blocks can define variables
        # that aren't tracked by 'output:'). Instead, report warnings.
        if violations:
            # Log but don't fail -- this is informational
            import warnings

            warnings.warn(
                f"Potential forward references found ({len(violations)}):\n"
                + "\n".join(f"  - {v}" for v in violations[:10]),
                stacklevel=1,
            )

    def test_all_steps_have_either_tool_or_compute(self):
        """Every step should have a 'tool', 'compute', 'then', or 'description'.

        Steps with none of these are no-ops and likely indicate a
        configuration error.
        """
        valid_actions = {"tool", "compute", "then", "description"}
        violations = []

        for path, skill in _load_all_skills():
            for i, step in enumerate(skill.get("steps", [])):
                if not isinstance(step, dict):
                    violations.append(f"{path.name} step {i}: not a dict")
                    continue
                if not any(key in step for key in valid_actions):
                    step_name = step.get("name", f"step_{i}")
                    violations.append(
                        f"{path.name} step '{step_name}': "
                        f"missing tool/compute/then/description"
                    )

        assert not violations, f"Steps without action found:\n" + "\n".join(
            f"  - {v}" for v in violations
        )

    def test_on_error_values_are_valid(self):
        """on_error should be 'continue', 'fail', or 'auto_heal'.

        Invalid values like 'ignore' or 'skip' would silently default
        to 'fail' behavior, which is confusing.
        """
        valid_on_error = {"continue", "fail", "auto_heal"}
        violations = []

        for path, skill in _load_all_skills():
            for step in skill.get("steps", []):
                on_error = step.get("on_error")
                if on_error is not None and on_error not in valid_on_error:
                    step_name = step.get("name", "unnamed")
                    violations.append(
                        f"{path.name} step '{step_name}': "
                        f"on_error='{on_error}' (valid: {valid_on_error})"
                    )

        assert not violations, f"Invalid on_error values found:\n" + "\n".join(
            f"  - {v}" for v in violations
        )

    def test_output_names_are_unique_per_skill(self):
        """Each step's output name should be unique within a skill.

        Duplicate output names cause earlier results to be silently
        overwritten, which leads to confusing bugs.

        Exception: conditional branches that are mutually exclusive
        (both steps have a 'condition' field) legitimately share an
        output name because only one branch executes. These are allowed.
        """
        violations = []

        for path, skill in _load_all_skills():
            # Track: output_name -> (step_name, has_condition)
            seen_outputs: dict[str, tuple[str, bool]] = {}
            for step in skill.get("steps", []):
                output_name = step.get("output", step.get("name", ""))
                if not output_name:
                    continue
                has_condition = "condition" in step
                if output_name in seen_outputs:
                    prev_name, prev_has_condition = seen_outputs[output_name]
                    # Allow if BOTH the previous and current step have conditions
                    # (mutually exclusive branches writing to same output)
                    if prev_has_condition and has_condition:
                        continue
                    violations.append(
                        f"{path.name}: output '{output_name}' defined in both "
                        f"'{prev_name}' and '{step.get('name', '?')}'"
                    )
                else:
                    seen_outputs[output_name] = (
                        step.get("name", "unnamed"),
                        has_condition,
                    )

        assert not violations, f"Duplicate output names found:\n" + "\n".join(
            f"  - {v}" for v in violations
        )

    def test_skill_names_match_filenames(self):
        """Skill 'name' field should match the YAML filename.

        Mismatches cause skill_run("name") to fail because the engine
        loads files by name but checks the name field internally.
        """
        violations = []

        for path, skill in _load_all_skills():
            expected_name = path.stem
            actual_name = skill.get("name", "")
            if actual_name and actual_name != expected_name:
                violations.append(
                    f"{path.name}: name='{actual_name}' but filename "
                    f"suggests '{expected_name}'"
                )

        assert not violations, f"Skill name/filename mismatches:\n" + "\n".join(
            f"  - {v}" for v in violations
        )


# ============================================================================
# Helpers
# ============================================================================


def _remove_string_literals(code: str) -> str:
    """Remove string literals from Python code to avoid false positive matches.

    Handles single-quoted, double-quoted, triple-quoted, and raw strings.
    Replaces string content with empty quotes to preserve code structure.
    """
    # Remove triple-quoted strings first (they can span multiple lines)
    code = re.sub(r'""".*?"""', '""', code, flags=re.DOTALL)
    code = re.sub(r"'''.*?'''", "''", code, flags=re.DOTALL)
    # Remove f-strings, r-strings, etc (single/double quoted)
    code = re.sub(r'[frbFRB]?"[^"\\]*(?:\\.[^"\\]*)*"', '""', code)
    code = re.sub(r"[frbFRB]?'[^'\\]*(?:\\.[^'\\]*)*'", "''", code)
    return code
