"""
Named Analysis Loops for Slop Bot.

Each loop focuses on ONE code smell type with clean context.
Ralph-style iteration: keep analyzing until "done" or max iterations.

Named Loops:
- LEAKY: Memory leaks, unbounded caches, global mutables
- ZOMBIE: Dead code, unused functions, stale imports
- RACER: Race conditions, async/await issues
- GHOST: Hallucinated imports, fake dependencies
- COPYCAT: Code duplication, similar functions
- SLOPPY: AI slop patterns (placeholders, buzzwords)
- TANGLED: Complexity, god classes, feature envy
- LEAKER: Security vulnerabilities
- SWALLOWER: Exception handling gaps
- DRIFTER: Verbosity, over-engineering

Usage:
    from services.slop.loops import AnalysisLoop, LOOP_CONFIGS, PRIORITY_ORDER

    loop = AnalysisLoop(
        name="leaky",
        config=LOOP_CONFIGS["leaky"],
        db=database,
        ai_router=router,
    )

    await loop.run()
    print(f"Found {loop.findings_count} issues")
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from services.base.ai_router import AIModelRouter
    from services.slop.database import SlopDatabase
    from services.slop.external_tools import ExternalTools

logger = logging.getLogger(__name__)


# Loop configurations - each focuses on ONE code smell type
# Each loop specifies its primary category and allowed sub-categories
LOOP_CONFIGS = {
    "leaky": {
        "name": "LEAKY",
        "task": "memory_leaks",
        "category": "memory_leaks",  # Primary category for this loop
        "allowed_categories": ["memory_leaks"],
        "description": "Memory leaks, unbounded caches, global mutables",
        "fast_tools": ["radon"],
        "max_iterations": 5,
        "prompt": """Find MEMORY LEAKS in this codebase:

Look for:
1. Unbounded caches that grow forever (dicts/lists without size limits)
2. Global mutable state that accumulates data
3. Missing cleanup in __del__ or context managers
4. Circular references preventing garbage collection
5. Event handlers that are never unregistered
6. File handles or connections that are never closed
7. Large objects held in closures unnecessarily

Focus ONLY on memory issues. Ignore other code smells.""",
    },
    "zombie": {
        "name": "ZOMBIE",
        "task": "dead_code",
        "category": "dead_code",  # Primary category
        "allowed_categories": [
            "dead_code",
            "unused_imports",
            "unused_variables",
            "unreachable_code",
        ],
        "description": "Dead code, unused functions, stale imports",
        "fast_tools": ["vulture"],
        "max_iterations": 3,
        "prompt": """Find DEAD CODE in this codebase:

Look for:
1. Functions that are never called → category: dead_code
2. Classes that are never instantiated → category: dead_code
3. Imports that are never used → category: unused_imports
4. Variables that are assigned but never read → category: unused_variables
5. Unreachable code after return/raise/break → category: unreachable_code
6. Commented-out code blocks → category: dead_code
7. Deprecated functions marked for removal → category: dead_code

Use the vulture hints provided. Focus ONLY on dead code.""",
    },
    "racer": {
        "name": "RACER",
        "task": "race_conditions",
        "category": "race_conditions",
        "allowed_categories": ["race_conditions"],
        "description": "Race conditions, async/await issues, concurrency bugs",
        "fast_tools": [],
        "max_iterations": 5,
        "prompt": """Find RACE CONDITIONS and CONCURRENCY BUGS in this codebase:

Look for:
1. Shared mutable state accessed from multiple async tasks
2. Missing locks/semaphores around critical sections
3. async/await without proper synchronization
4. Time-of-check to time-of-use (TOCTOU) bugs
5. Non-atomic read-modify-write operations
6. Deadlock potential from lock ordering
7. Missing thread safety in singleton patterns

Focus ONLY on concurrency issues. This requires careful analysis.""",
    },
    "ghost": {
        "name": "GHOST",
        "task": "hallucinated_imports",
        "category": "hallucinated_imports",
        "allowed_categories": ["hallucinated_imports", "unused_imports"],
        "description": "Hallucinated imports, fake dependencies",
        "fast_tools": ["slop-detector"],
        "max_iterations": 2,
        "prompt": """Find HALLUCINATED IMPORTS in this codebase:

Look for:
1. Imports of packages that don't exist in PyPI/npm → category: hallucinated_imports
2. Imports from wrong package names (e.g., 'from react import useRouter') → category: hallucinated_imports
3. Purpose-specific imports that are never used (ML, HTTP, DB libraries) → category: unused_imports
4. Imports of internal modules that don't exist → category: hallucinated_imports
5. Version-specific imports that reference non-existent APIs → category: hallucinated_imports

Focus ONLY on import issues. Check if packages actually exist.""",
    },
    "copycat": {
        "name": "COPYCAT",
        "task": "code_duplication",
        "category": "code_duplication",
        "allowed_categories": ["code_duplication"],
        "description": "Code duplication, similar functions",
        "fast_tools": ["jscpd"],
        "max_iterations": 2,
        "prompt": """Find CODE DUPLICATION in this codebase:

Look for:
1. Copy-pasted code blocks (exact duplicates)
2. Similar functions with minor variations
3. Repeated patterns that could be abstracted
4. Duplicate logic across different modules
5. Similar error handling that could be centralized

Use the jscpd hints provided. Focus ONLY on duplication.""",
    },
    "sloppy": {
        "name": "SLOPPY",
        "task": "ai_slop",
        "category": "ai_slop",
        "allowed_categories": ["ai_slop", "placeholder_code", "docstring_inflation"],
        "description": "AI slop patterns (placeholders, buzzwords, fake docs)",
        "fast_tools": ["slop-detector"],
        "max_iterations": 3,
        "prompt": """Find AI SLOP PATTERNS in this codebase:

Look for:
1. Empty functions with only 'pass' or '...' → category: placeholder_code
2. NotImplementedError without actual implementation → category: placeholder_code
3. Buzzword claims without evidence ("production-ready", "enterprise-grade") → category: ai_slop
4. Docstring inflation (more docs than code) → category: docstring_inflation
5. Vibe coding comments ("might work", "should be fine") → category: ai_slop
6. Generic boilerplate that doesn't fit the domain → category: ai_slop
7. TODO/FIXME comments that were never addressed → category: placeholder_code

Focus ONLY on AI-generated slop patterns.""",
    },
    "tangled": {
        "name": "TANGLED",
        "task": "complexity",
        "category": "complexity",
        "allowed_categories": ["complexity"],
        "description": "Complexity, god classes, feature envy",
        "fast_tools": ["radon"],
        "max_iterations": 4,
        "prompt": """Find COMPLEXITY ISSUES in this codebase:

Look for:
1. God classes with too many responsibilities
2. Feature envy (methods that use other classes more than their own)
3. Long methods (> 50 lines)
4. Deep nesting (> 4 levels)
5. High cyclomatic complexity (use radon hints)
6. Primitive obsession (using primitives instead of objects)
7. Data clumps (groups of data that appear together)

Focus ONLY on complexity and design issues.""",
    },
    "leaker": {
        "name": "LEAKER",
        "task": "security",
        "category": "security",
        "allowed_categories": ["security"],
        "description": "Security vulnerabilities",
        "fast_tools": ["bandit"],
        "max_iterations": 3,
        "prompt": """Find SECURITY VULNERABILITIES in this codebase:

Look for:
1. Hardcoded secrets, passwords, API keys
2. SQL injection vulnerabilities
3. Command injection (shell=True, eval, exec)
4. Path traversal vulnerabilities
5. Insecure deserialization (pickle, yaml.load)
6. Missing input validation
7. Sensitive data in logs

Use the bandit hints provided. Focus ONLY on security issues.""",
    },
    "swallower": {
        "name": "SWALLOWER",
        "task": "exception_handling",
        "category": "exception_handling",
        "allowed_categories": ["exception_handling", "bare_except", "empty_except"],
        "description": "Exception handling gaps",
        "fast_tools": ["ruff"],
        "max_iterations": 3,
        "prompt": """Find EXCEPTION HANDLING ISSUES in this codebase:

Look for:
1. Bare except clauses (except:) → category: bare_except
2. Empty except blocks (except: pass) → category: empty_except
3. Catching too broad exceptions (except Exception) → category: exception_handling
4. Missing error handling for I/O operations → category: exception_handling
5. Swallowed exceptions that should be logged → category: empty_except
6. Missing finally blocks for cleanup → category: exception_handling
7. Re-raising without preserving stack trace → category: exception_handling

Focus ONLY on exception handling issues.""",
    },
    "drifter": {
        "name": "DRIFTER",
        "task": "verbosity",
        "category": "verbosity",
        "allowed_categories": ["verbosity", "style_issues"],
        "description": "Verbosity, over-engineering",
        "fast_tools": [],
        "max_iterations": 3,
        "prompt": """Find VERBOSITY and OVER-ENGINEERING in this codebase:

Look for:
1. Unnecessary abstraction layers → category: verbosity
2. Over-complicated solutions for simple problems → category: verbosity
3. Excessive defensive programming → category: verbosity
4. Redundant validation that's already done elsewhere → category: verbosity
5. Verbose code that could be simplified → category: style_issues
6. Design patterns used inappropriately → category: verbosity
7. Configuration for things that never change → category: verbosity

Focus ONLY on verbosity and over-engineering.""",
    },
}

# Priority order - run high-impact loops first
PRIORITY_ORDER = [
    # Critical - Security & Correctness
    "leaker",  # Security vulnerabilities (bandit pre-filter)
    "ghost",  # Hallucinated imports (slop-detector pre-filter)
    "racer",  # Race conditions (LLM-only)
    # High - Code Quality
    "leaky",  # Memory leaks
    "swallower",  # Exception handling gaps
    "zombie",  # Dead code (vulture pre-filter)
    # Medium - Maintainability
    "tangled",  # Complexity (radon pre-filter)
    "copycat",  # Code duplication (jscpd pre-filter)
    "sloppy",  # AI slop patterns (slop-detector pre-filter)
    # Low - Style
    "drifter",  # Verbosity, over-engineering
]


@dataclass
class LoopResult:
    """Result of an analysis loop run."""

    loop_name: str
    status: str  # idle, running, done, stopped, error
    iterations: int
    max_iterations: int
    findings_count: int
    duration_ms: int
    error: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "loop_name": self.loop_name,
            "status": self.status,
            "iterations": self.iterations,
            "max_iterations": self.max_iterations,
            "findings_count": self.findings_count,
            "duration_ms": self.duration_ms,
            "error": self.error,
        }


class AnalysisLoop:
    """
    A named analysis loop that focuses on one code smell type.

    Ralph-style iteration: keeps analyzing until LLM says "done"
    or max iterations reached.
    """

    def __init__(
        self,
        name: str,
        config: dict,
        db: "SlopDatabase",
        ai_router: "AIModelRouter",
        external_tools: Optional["ExternalTools"] = None,
    ):
        """
        Initialize an analysis loop.

        Args:
            name: Loop name (e.g., "leaky", "zombie")
            config: Loop configuration from LOOP_CONFIGS
            db: Database for storing findings
            ai_router: AI router for LLM analysis
            external_tools: External tools wrapper for fast pre-filtering
        """
        self.name = name
        self.display_name = config.get("name", name.upper())
        self.task = config.get("task", name)
        self.description = config.get("description", "")
        self.prompt_template = config.get("prompt", "")
        self.fast_tools = config.get("fast_tools", [])
        self.max_iterations = config.get("max_iterations", 5)

        # Category configuration
        self.primary_category = config.get("category", "unknown")
        self.allowed_categories = config.get(
            "allowed_categories", [self.primary_category]
        )

        self._db = db
        self._ai_router = ai_router
        self._external_tools = external_tools

        # State
        self._status = "idle"
        self._current_iteration = 0
        self._findings: list[dict] = []
        self._stop_requested = False
        self._start_time: Optional[datetime] = None

    @property
    def status(self) -> str:
        """Current loop status."""
        return self._status

    @property
    def current_iteration(self) -> int:
        """Current iteration number."""
        return self._current_iteration

    @property
    def findings_count(self) -> int:
        """Number of findings so far."""
        return len(self._findings)

    def get_status_dict(self) -> dict:
        """Get status as dictionary for D-Bus/UI."""
        return {
            "name": self.name,
            "display_name": self.display_name,
            "status": self._status,
            "iteration": self._current_iteration,
            "max_iterations": self.max_iterations,
            "findings_count": len(self._findings),
            "description": self.description,
        }

    async def stop(self):
        """Request the loop to stop."""
        logger.info(f"Stop requested for loop {self.name}")
        self._stop_requested = True

    async def run(
        self, files: Optional[list[str]] = None, codebase_path: Optional[str] = None
    ) -> LoopResult:
        """
        Run the analysis loop until done or max iterations.

        Args:
            files: List of files to analyze (or None for whole codebase)
            codebase_path: Path to codebase root

        Returns:
            LoopResult with summary
        """
        self._status = "running"
        self._current_iteration = 0
        self._findings = []
        self._stop_requested = False
        self._start_time = datetime.now()

        logger.info(f"Starting loop {self.name}: {self.description}")

        try:
            # 1. Get files to analyze
            if files is None:
                files = await self._get_relevant_files(codebase_path)

            if not files:
                logger.warning(f"No files to analyze for loop {self.name}")
                self._status = "done"
                return self._create_result()

            # 2. Run fast tools first (if any)
            fast_hints = []
            if self.fast_tools and self._external_tools:
                fast_hints = await self._run_fast_tools(files, codebase_path)
                logger.info(f"Fast tools found {len(fast_hints)} hints for {self.name}")

            # 3. Ralph-style iteration
            while (
                self._current_iteration < self.max_iterations
                and not self._stop_requested
            ):
                self._current_iteration += 1
                logger.info(
                    f"Loop {self.name} iteration {self._current_iteration}/{self.max_iterations}"
                )

                # Build focused prompt
                prompt = self._build_prompt(files, fast_hints)

                # Call LLM
                response = await self._ai_router.analyze(prompt, task=self.task)

                if not response.success:
                    logger.error(
                        f"LLM analysis failed for {self.name}: {response.error}"
                    )
                    # Continue to next iteration, might recover
                    continue

                # Process findings
                new_findings = response.findings
                if new_findings:
                    logger.info(
                        f"Loop {self.name} found {len(new_findings)} new issues"
                    )
                    for finding in new_findings:
                        finding["loop"] = self.name
                        # Validate and default category
                        finding_category = finding.get("category", "")
                        if finding_category not in self.allowed_categories:
                            # Default to primary category if invalid/missing
                            logger.debug(
                                f"Finding category '{finding_category}' not in allowed "
                                f"{self.allowed_categories}, defaulting to '{self.primary_category}'"
                            )
                            finding["category"] = self.primary_category
                        self._findings.append(finding)

                # Check if done
                if response.done:
                    logger.info(
                        f"Loop {self.name} reports done after {self._current_iteration} iterations"
                    )
                    break

            # 4. Store findings in database
            for finding in self._findings:
                await self._db.add_finding(finding)

            self._status = "done" if not self._stop_requested else "stopped"

        except Exception as e:
            logger.exception(f"Loop {self.name} error: {e}")
            self._status = "error"

        result = self._create_result()
        logger.info(
            f"Loop {self.name} completed: {result.findings_count} findings in {result.duration_ms}ms"
        )
        return result

    def _create_result(self) -> LoopResult:
        """Create a LoopResult from current state."""
        duration_ms = 0
        if self._start_time:
            duration_ms = int(
                (datetime.now() - self._start_time).total_seconds() * 1000
            )

        return LoopResult(
            loop_name=self.name,
            status=self._status,
            iterations=self._current_iteration,
            max_iterations=self.max_iterations,
            findings_count=len(self._findings),
            duration_ms=duration_ms,
            error=None if self._status != "error" else "Analysis error",
        )

    async def _get_relevant_files(
        self, codebase_path: Optional[str] = None
    ) -> list[str]:
        """Get list of files to analyze."""
        if not codebase_path:
            codebase_path = "."

        path = Path(codebase_path)
        files = []

        # Get Python files (primary focus)
        for pattern in ["**/*.py"]:
            for file_path in path.glob(pattern):
                # Skip common exclusions
                str_path = str(file_path)
                if any(
                    excl in str_path
                    for excl in [
                        "__pycache__",
                        ".git",
                        "node_modules",
                        ".venv",
                        "venv",
                        ".tox",
                        "dist",
                        "build",
                        ".egg",
                    ]
                ):
                    continue
                files.append(str(file_path))

        return files[:100]  # Limit to 100 files per loop

    async def _run_fast_tools(
        self, files: list[str], codebase_path: Optional[str]
    ) -> list[dict]:
        """Run fast tools for pre-filtering."""
        if not self._external_tools:
            return []

        hints = []
        target = codebase_path or "."

        for tool in self.fast_tools:
            try:
                findings = await self._external_tools.run_tool(tool, target)
                for finding in findings:
                    hints.append(finding.to_dict())
            except Exception as e:
                logger.warning(f"Fast tool {tool} failed: {e}")

        return hints

    def _build_prompt(self, files: list[str], fast_hints: list[dict]) -> str:
        """Build focused prompt for this specific task."""
        # Format files list (truncate if too long)
        files_text = "\n".join(files[:50])
        if len(files) > 50:
            files_text += f"\n... and {len(files) - 50} more files"

        # Format hints
        hints_text = "None"
        if fast_hints:
            hints_text = json.dumps(fast_hints[:20], indent=2)
            if len(fast_hints) > 20:
                hints_text += f"\n... and {len(fast_hints) - 20} more hints"

        # Format previous findings
        prev_findings_text = "None"
        if self._findings:
            prev_findings_text = json.dumps(self._findings[-10:], indent=2)
            if len(self._findings) > 10:
                prev_findings_text = (
                    f"... {len(self._findings) - 10} earlier findings ...\n"
                    + prev_findings_text
                )

        # Format allowed categories
        allowed_cats = ", ".join(self.allowed_categories)

        return f"""## Analysis Task: {self.display_name}

{self.prompt_template}

## Scope

Analyze the ENTIRE codebase for this ONE issue type.
Iteration: {self._current_iteration}/{self.max_iterations}

## Files to Analyze

{files_text}

## Fast Tool Hints (pre-filtered)

{hints_text}

## Previous Findings This Pass

{prev_findings_text}

## Instructions

1. Focus ONLY on {self.task} - ignore other code smells
2. Analyze across ALL files, not just one at a time
3. Return JSON: {{"findings": [...], "done": true/false}}
4. Set done=true when you've found all issues or confirmed none exist
5. Each finding MUST include: file, line, category, description, severity, suggestion
6. CATEGORY must be one of: {allowed_cats}
7. SUGGESTION must be actionable (e.g., "Remove import 'os' on line 42" not "Consider removing...")
8. Don't repeat findings from previous iterations
"""
