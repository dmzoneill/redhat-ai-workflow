"""Error recovery and auto-heal logic for skill execution."""

from __future__ import annotations

import asyncio
import fcntl
import logging
from datetime import datetime

import yaml

from .constants import SKILLS_DIR

logger = logging.getLogger(__name__)


class ErrorRecoveryMixin:
    """Mixin providing error handling and auto-heal for skill execution."""

    async def _learn_from_error(self, tool_name: str, params: dict, error_msg: str):
        """Send error to Layer 5 learning system (async).

        This is called when on_error: continue swallows an error.
        Layer 5 will:
        1. Classify the error (usage vs infrastructure)
        2. Extract patterns and prevention steps
        3. Merge with similar patterns
        4. Build confidence over time
        """
        if not self.usage_learner:
            return

        try:
            # Learn from this error asynchronously
            await self.usage_learner.learn_from_observation(  # type: ignore[attr-defined]
                tool_name=tool_name,
                params=params,
                error_message=error_msg,
                context={},
                success=False,
            )
            self._debug(f"Layer 5: Learned from error in {tool_name}")
        except Exception as e:
            # Don't let learning failure break the skill
            logger.warning(f"Layer 5 learning failed: {e}")

    def _find_matched_pattern(self, error_lower: str) -> tuple[dict | None, str | None]:
        """Find a matching pattern from memory based on error text.

        Returns:
            (matched_pattern, pattern_category) tuple or (None, None)
        """
        try:
            patterns_file = SKILLS_DIR.parent / "memory" / "learned" / "patterns.yaml"
            if not patterns_file.exists():
                return None, None

            with open(patterns_file, encoding="utf-8") as f:
                patterns_data = yaml.safe_load(f) or {}

            # Check each category for matches
            for cat in [
                "auth_patterns",
                "error_patterns",
                "bonfire_patterns",
                "pipeline_patterns",
            ]:
                for pattern in patterns_data.get(cat, []):
                    pattern_text = pattern.get("pattern", "").lower()
                    if pattern_text and pattern_text in error_lower:
                        # Track that pattern was matched
                        self._update_pattern_usage_stats(
                            cat, pattern_text, matched=True
                        )
                        return pattern, cat
        except Exception as e:
            self._debug(f"Pattern lookup failed: {e}")

        return None, None

    def _determine_fix_type(
        self, error_lower: str, matched_pattern: dict | None, matches: list
    ) -> str | None:
        """Determine which fix type to apply based on patterns.

        Returns:
            "network", "auth", or None
        """
        # Priority 1: Use matched pattern from learned memory
        if matched_pattern:
            commands = matched_pattern.get("commands", [])
            for cmd in commands:
                if "vpn" in cmd.lower() or "connect" in cmd.lower():
                    return "network"
                if (
                    "login" in cmd.lower()
                    or "auth" in cmd.lower()
                    or "kube" in cmd.lower()
                ):
                    return "auth"

        # Priority 2: Hardcoded patterns
        auth_patterns = ["unauthorized", "401", "403", "forbidden", "token expired"]
        network_patterns = ["no route to host", "connection refused", "timeout"]

        if any(p in error_lower for p in auth_patterns):
            return "auth"
        elif any(p in error_lower for p in network_patterns):
            return "network"

        # Priority 3: Check matches from known issues
        for match in matches:
            fix = match.get("fix", "").lower()
            if "vpn" in fix or "connect" in fix:
                return "network"
            if "login" in fix or "auth" in fix or "kube" in fix:
                return "auth"

        return None

    async def _apply_network_fix(self) -> bool:
        """Apply VPN connect fix using the configured VPN script or nmcli fallback."""
        import os

        try:
            # Try to use the configured VPN script first (same as vpn_connect tool)
            from server.utils import load_config

            config = load_config()
            paths = config.get("paths", {})
            vpn_script = paths.get("vpn_connect_script")

            if not vpn_script:
                vpn_script = os.path.expanduser(
                    "~/src/redhatter/src/redhatter_vpn/vpn-connect"
                )
            else:
                vpn_script = os.path.expanduser(vpn_script)

            if os.path.exists(vpn_script):
                self._debug(f"  → Using VPN script: {vpn_script}")
                proc = await asyncio.create_subprocess_exec(
                    vpn_script,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await asyncio.wait_for(proc.wait(), timeout=120)
                self._debug(f"  → VPN connect result: {proc.returncode}")
                await asyncio.sleep(2)  # Wait for VPN to establish
                return proc.returncode == 0
            else:
                # Fallback to nmcli with common VPN connection names
                self._debug("  → VPN script not found, trying nmcli fallback")
                vpn_names = [
                    "Red Hat Global VPN",
                    "Red Hat VPN",
                    "redhat-vpn",
                    "RH-VPN",
                ]
                for vpn_name in vpn_names:
                    proc = await asyncio.create_subprocess_shell(
                        f"nmcli connection up '{vpn_name}' 2>/dev/null",
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=30)
                        if proc.returncode == 0:
                            self._debug(
                                f"  → VPN connect result: success with {vpn_name}"
                            )
                            await asyncio.sleep(2)
                            return True
                    except asyncio.TimeoutError:
                        continue

                self._debug("  → All VPN connection attempts failed")
                return False

        except Exception as e:
            self._debug(f"  → Auto-fix failed: {e}")
            return False

    async def _apply_auth_fix(self, error_lower: str) -> bool:
        """Apply kube login fix."""
        try:
            # Guess cluster from error
            cluster = "stage"  # default
            if "ephemeral" in error_lower or "bonfire" in error_lower:
                cluster = "ephemeral"
            elif "konflux" in error_lower or "tekton" in error_lower:
                cluster = "konflux"
            elif "prod" in error_lower:
                cluster = "prod"

            # Call oc login using asyncio subprocess
            kubeconfig = f"~/.kube/config.{cluster[0]}"
            cluster_urls = {
                "stage": "api.c-rh-c-eph.8p0c.p1.openshiftapps.com:6443",
                "ephemeral": "api.c-rh-c-eph.8p0c.p1.openshiftapps.com:6443",
                "prod": "api.crcp01ue1.o9m8.p1.openshiftapps.com:6443",
                "konflux": "api.stone-prd-rh01.pg1f.p1.openshiftapps.com:6443",
            }
            url = cluster_urls.get(cluster, cluster_urls["stage"])

            proc = await asyncio.create_subprocess_exec(
                "oc",
                "login",
                f"--kubeconfig={kubeconfig}",
                f"https://{url}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.wait(), timeout=30)
            self._debug(f"  → Kube login result: {proc.returncode}")
            await asyncio.sleep(1)
            return proc.returncode == 0
        except Exception as e:
            self._debug(f"  → Auto-fix failed: {e}")
            return False

    async def _try_auto_fix(self, error_msg: str, matches: list) -> bool:
        """Try to auto-fix based on known patterns.

        Returns True if a fix was applied, False otherwise.
        """
        error_lower = error_msg.lower()

        # Find matching pattern from memory
        matched_pattern, pattern_category = self._find_matched_pattern(error_lower)

        # Determine which fix to apply
        fix_type = self._determine_fix_type(error_lower, matched_pattern, matches)

        if not fix_type:
            return False

        self._debug(f"  → Detected {fix_type} issue, applying auto-fix")

        # Apply the appropriate fix
        if fix_type == "network":
            fix_success = await self._apply_network_fix()
        elif fix_type == "auth":
            fix_success = await self._apply_auth_fix(error_lower)
        else:
            fix_success = False

        # Track fix success for matched pattern
        if fix_success and matched_pattern and pattern_category:
            pattern_text = matched_pattern.get("pattern", "")
            self._update_pattern_usage_stats(
                pattern_category, pattern_text, matched=False, fixed=True
            )

        return fix_success

    def _update_pattern_usage_stats(
        self,
        category: str,
        pattern_text: str,
        matched: bool = True,
        fixed: bool = False,
    ) -> None:
        """Update usage statistics for a pattern.

        Args:
            category: Pattern category (e.g., "auth_patterns", "error_patterns")
            pattern_text: The pattern text to find
            matched: Whether the pattern was matched (default: True)
            fixed: Whether the fix succeeded (default: False)
        """
        try:
            patterns_file = SKILLS_DIR.parent / "memory" / "learned" / "patterns.yaml"
            if not patterns_file.exists():
                return

            # Atomic read-modify-write with file locking
            with open(patterns_file, "r+", encoding="utf-8") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)

                try:
                    f.seek(0)
                    patterns_data = yaml.safe_load(f.read()) or {}

                    if category not in patterns_data:
                        return

                    # Find and update the pattern
                    for pattern in patterns_data[category]:
                        if pattern.get("pattern", "").lower() == pattern_text.lower():
                            # Initialize usage_stats if not present
                            if "usage_stats" not in pattern:
                                pattern["usage_stats"] = {
                                    "times_matched": 0,
                                    "times_fixed": 0,
                                    "success_rate": 0.0,
                                }

                            stats = pattern["usage_stats"]

                            # Update counters
                            if matched:
                                stats["times_matched"] = (
                                    stats.get("times_matched", 0) + 1
                                )
                                stats["last_matched"] = datetime.now().isoformat()

                            if fixed:
                                stats["times_fixed"] = stats.get("times_fixed", 0) + 1

                            # Recalculate success rate
                            if stats["times_matched"] > 0:
                                stats["success_rate"] = round(
                                    stats["times_fixed"] / stats["times_matched"], 2
                                )

                            # Write back
                            f.seek(0)
                            f.truncate()
                            yaml.dump(
                                patterns_data,
                                f,
                                default_flow_style=False,
                                sort_keys=False,
                            )
                            break

                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)

        except Exception as e:
            self._debug(f"Failed to update pattern stats: {e}")

    def _check_error_patterns(self, error: str) -> str | None:
        """Check if error matches known patterns and return fix suggestion."""
        try:
            patterns_file = SKILLS_DIR.parent / "memory" / "learned" / "patterns.yaml"
            if not patterns_file.exists():
                return None

            with open(patterns_file, encoding="utf-8") as f:
                patterns_data = yaml.safe_load(f) or {}

            error_patterns = patterns_data.get("error_patterns", [])
            error_lower = error.lower()

            for pattern in error_patterns:
                pattern_text = pattern.get("pattern", "").lower()
                if pattern_text and pattern_text in error_lower:
                    # Track pattern match
                    self._update_pattern_usage_stats(
                        "error_patterns", pattern_text, matched=True
                    )

                    fix = pattern.get("fix", "")
                    meaning = pattern.get("meaning", "")
                    commands = pattern.get("commands", [])

                    parts = [f"\n   💡 **Known pattern: {pattern.get('pattern')}**"]
                    if meaning:
                        parts.append(f"\n   *{meaning}*")
                    if fix:
                        parts.append(f"\n   **Fix:** {fix}")
                    if commands:
                        parts.append("\n   **Try:**")
                        parts.extend(f"\n   - `{cmd}`" for cmd in commands[:3])
                    return "".join(parts)

            return None
        except Exception as e:
            self._debug(f"Pattern lookup failed: {e}")
            return None

    def _handle_auto_fix_action(self, error_info: dict, step_name: str):
        """Handle auto_fix action for interactive recovery."""
        fix_code = error_info.get("fix_code")
        if not fix_code:
            self._debug("Auto-fix not available despite user selection")
            return None

        # Re-execute with fixed code
        try:
            self._debug("Retrying with fixed code...")
            fixed_result = self._exec_compute_internal(fix_code, step_name)

            # Log successful fix
            self.error_recovery.log_fix_attempt(
                error_info,
                action="auto_fix",
                success=not isinstance(fixed_result, str)
                or not fixed_result.startswith("<compute error:"),
                details=f"Auto-fixed {error_info.get('pattern_id')}",
            )

            return fixed_result
        except Exception as e:
            self._debug(f"Auto-fix failed: {e}")
            self.error_recovery.log_fix_attempt(
                error_info, action="auto_fix", success=False, details=str(e)
            )
            return None

    def _handle_edit_action(self, error_info: dict, error_msg: str, step_name: str):
        """Handle edit action for interactive recovery."""
        skill_name = self.skill.get("name", "unknown")
        skill_path = SKILLS_DIR / f"{skill_name}.yaml"

        logger.info(
            "\n🔧 Please edit the skill file: %s\n   Step: %s\n   Error: %s\n   Suggestion: %s\n",
            skill_path,
            step_name,
            error_msg,
            error_info.get("suggestion"),
        )
        input("Press Enter after saving your changes...")

        # Log manual edit
        self.error_recovery.log_fix_attempt(
            error_info,
            action="manual_edit",
            success=True,
            details="User manually edited skill",
        )

        # Return None to signal skill should be aborted and re-run
        return None

    def _handle_skip_action(self, error_info: dict, step_name: str):
        """Handle skip action for interactive recovery."""
        logger.info("\n⏭️  Skipping skill execution.\n   Error in step: %s\n", step_name)

        self.error_recovery.log_fix_attempt(
            error_info, action="skip", success=False, details="User chose to skip"
        )
        return None

    def _handle_abort_action(self, error_info: dict, error_msg: str, step_name: str):
        """Handle abort action for interactive recovery."""
        # Create GitHub issue if possible
        if self.create_issue_fn:
            try:
                issue_result = asyncio.get_event_loop().run_until_complete(
                    self.create_issue_fn(
                        tool="skill_compute",
                        error=error_msg,
                        context=f"Skill: {self.skill.get('name')}, Step: {step_name}",
                        skill=self.skill.get("name", "unknown"),
                    )
                )
                if issue_result.get("success"):
                    logger.info(
                        "\n🐛 GitHub issue created: %s", issue_result.get("issue_url")
                    )
            except Exception as e:
                self._debug(f"Could not create issue: {e}")

        self.error_recovery.log_fix_attempt(
            error_info,
            action="abort",
            success=False,
            details="User aborted with issue creation",
        )
        return None

    def _handle_continue_action(self, error_info: dict, error_msg: str):
        """Handle continue action for interactive recovery."""
        # Debug mode - let broken data propagate
        self.error_recovery.log_fix_attempt(
            error_info,
            action="continue",
            success=False,
            details="User chose to continue with error",
        )
        return f"<compute error: {error_msg}>"

    def _initialize_error_recovery(self):
        """Initialize error recovery system if not already loaded."""
        if self.error_recovery:
            return True

        try:
            from scripts.common.skill_error_recovery import SkillErrorRecovery

            # Pass memory helpers if available
            memory_helper = None
            try:
                from scripts.common import memory as memory_helpers

                memory_helper = memory_helpers
            except ImportError as exc:
                logger.debug("Optional import not available: %s", exc)

            self.error_recovery = SkillErrorRecovery(memory_helper=memory_helper)
            return True
        except ImportError as e:
            self._debug(f"Could not load error recovery: {e}")
            return False

    def _try_interactive_recovery(self, code: str, error_msg: str, step_name: str):
        """
        Attempt interactive recovery from compute error.

        Returns:
            The computed result if recovery successful, None if user chose to abort/skip
        """
        # Lazy import to avoid circular dependencies
        if not self._initialize_error_recovery():
            return None

        # Detect error pattern
        error_info = self.error_recovery.detect_error(code, error_msg, step_name)
        self._debug(f"Error detected: {error_info.get('pattern_id', 'unknown')}")

        # Show error to user and get action
        try:
            # Call ask_question_fn which is already async
            action_result = asyncio.get_event_loop().run_until_complete(
                self.error_recovery.prompt_user_for_action(
                    error_info, self.ask_question_fn
                )
            )
        except Exception as e:
            self._debug(f"Interactive prompt failed: {e}")
            return None

        action = action_result.get("action")
        self._debug(f"User chose: {action}")

        # Dispatch to action handlers
        if action == "auto_fix":
            return self._handle_auto_fix_action(error_info, step_name)
        elif action == "edit":
            return self._handle_edit_action(error_info, error_msg, step_name)
        elif action == "skip":
            return self._handle_skip_action(error_info, step_name)
        elif action == "abort":
            return self._handle_abort_action(error_info, error_msg, step_name)
        elif action == "continue":
            return self._handle_continue_action(error_info, error_msg)

        return None

    def _detect_auto_heal_type(self, error_msg: str) -> tuple[str | None, str]:
        """Detect if error is auto-healable and what type.

        Returns:
            (heal_type, cluster_hint) where heal_type is 'auth', 'network', or None
        """
        error_lower = error_msg.lower()

        # Auth patterns that can be fixed with kube_login
        auth_patterns = [
            "unauthorized",
            "401",
            "forbidden",
            "403",
            "token expired",
            "authentication required",
            "not authorized",
            "permission denied",
            "the server has asked for the client to provide credentials",
        ]

        # Network patterns that can be fixed with vpn_connect
        network_patterns = [
            "no route to host",
            "no such host",  # DNS resolution failure
            "connection refused",
            "network unreachable",
            "timeout",
            "dial tcp",
            "connection reset",
            "eof",
            "cannot connect",
            "name or service not known",  # Another DNS failure pattern
        ]

        # Determine cluster from error context
        cluster = "stage"  # default
        if "ephemeral" in error_lower or "bonfire" in error_lower:
            cluster = "ephemeral"
        elif "konflux" in error_lower:
            cluster = "konflux"
        elif "prod" in error_lower:
            cluster = "prod"

        if any(p in error_lower for p in auth_patterns):
            return "auth", cluster
        if any(p in error_lower for p in network_patterns):
            return "network", cluster

        return None, cluster

    async def _attempt_auto_heal(
        self,
        heal_type: str,
        cluster: str,
        tool: str,
        step: dict,
        output_lines: list[str],
    ) -> dict | None:
        """Attempt to auto-heal and retry the tool.

        Returns:
            Retry result dict if successful, None if heal failed
        """
        try:
            if heal_type == "auth":
                output_lines.append(
                    f"   🔧 Auto-healing: running kube_login({cluster})..."
                )
                self._debug(f"Auto-heal: kube_login({cluster})")

                # Emit remediation step event
                if self.event_emitter:
                    self.event_emitter.remediation_step(
                        self.event_emitter.current_step_index,
                        "kube_login",
                        f"Auth error on {tool}",
                    )

                # Call kube_login tool
                heal_result = await self._exec_tool("kube_login", {"cluster": cluster})
                if not heal_result.get("success"):
                    # Get error from either 'error' key or 'result' key (for tools that return error text)
                    error_msg = heal_result.get("error") or heal_result.get(
                        "result", "unknown"
                    )
                    # Truncate long error messages
                    if len(error_msg) > 200:
                        error_msg = error_msg[:200] + "..."
                    output_lines.append(f"   ⚠️ kube_login failed: {error_msg}")
                    return None
                output_lines.append("   ✅ kube_login successful")

            elif heal_type == "network":
                output_lines.append("   🔧 Auto-healing: running vpn_connect()...")
                self._debug("Auto-heal: vpn_connect()")

                # Emit remediation step event
                if self.event_emitter:
                    self.event_emitter.remediation_step(
                        self.event_emitter.current_step_index,
                        "vpn_connect",
                        f"Network error on {tool}",
                    )

                # Call vpn_connect tool
                heal_result = await self._exec_tool("vpn_connect", {})
                if not heal_result.get("success"):
                    # Get error from either 'error' key or 'result' key (for tools that return error text)
                    error_msg = heal_result.get("error") or heal_result.get(
                        "result", "unknown"
                    )
                    # Truncate long error messages
                    if len(error_msg) > 200:
                        error_msg = error_msg[:200] + "..."
                    output_lines.append(f"   ⚠️ vpn_connect failed: {error_msg}")
                    return None
                output_lines.append("   ✅ vpn_connect successful")

                # Wait for VPN connection to stabilize before retrying
                # Network routes need time to propagate after VPN connects
                output_lines.append("   ⏳ Waiting 3s for VPN to stabilize...")
                await asyncio.sleep(3)

            else:
                return None

            # Retry the original tool
            output_lines.append(f"   🔄 Retrying {tool}...")
            raw_args = step.get("args", {})
            args = self._template_dict(raw_args)
            retry_result = await self._exec_tool(tool, args)

            return retry_result

        except Exception as e:
            self._debug(f"Auto-heal failed: {e}")
            output_lines.append(f"   ⚠️ Auto-heal exception: {e}")
            return None

    async def _log_auto_heal_to_memory(
        self,
        tool: str,
        heal_type: str,
        error_snippet: str,
        success: bool,
    ) -> None:
        """Log auto-heal attempt to memory for learning."""
        try:
            # Find memory directory
            memory_dir = SKILLS_DIR.parent / "memory" / "learned"
            memory_dir.mkdir(parents=True, exist_ok=True)

            failures_file = memory_dir / "tool_failures.yaml"

            # Load or create
            if failures_file.exists():
                with open(failures_file, encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
            else:
                data = {
                    "failures": [],
                    "stats": {
                        "total_failures": 0,
                        "auto_fixed": 0,
                        "manual_required": 0,
                    },
                }

            if "failures" not in data:
                data["failures"] = []
            if "stats" not in data:
                data["stats"] = {
                    "total_failures": 0,
                    "auto_fixed": 0,
                    "manual_required": 0,
                }

            # Add entry
            entry = {
                "tool": tool,
                "error_type": heal_type,
                "error_snippet": error_snippet[:100],
                "fix_applied": "kube_login" if heal_type == "auth" else "vpn_connect",
                "success": success,
                "source": "skill_engine",
                "timestamp": datetime.now().isoformat(),
            }
            data["failures"].append(entry)

            # Update stats
            data["stats"]["total_failures"] = data["stats"].get("total_failures", 0) + 1
            if success:
                data["stats"]["auto_fixed"] = data["stats"].get("auto_fixed", 0) + 1
            else:
                data["stats"]["manual_required"] = (
                    data["stats"].get("manual_required", 0) + 1
                )

            # Keep only last 100 entries
            if len(data["failures"]) > 100:
                data["failures"] = data["failures"][-100:]

            # Write back
            with open(failures_file, "w", encoding="utf-8") as f:
                yaml.dump(data, f, default_flow_style=False)

            self._debug(f"Logged auto-heal for {tool} to memory (success={success})")

        except Exception as e:
            self._debug(f"Failed to log auto-heal to memory: {e}")

    async def _handle_tool_error(
        self,
        tool: str,
        step: dict,
        step_name: str,
        error_msg: str,
        output_lines: list[str],
    ) -> bool:
        """Handle tool execution error.

        Returns:
            True if processing should continue, False if skill should stop
        """
        output_lines.append(f"   ❌ Error: {error_msg}")

        # Check for known error patterns
        pattern_hint = self._check_error_patterns(error_msg)
        if pattern_hint:
            output_lines.append(pattern_hint)

        on_error = step.get("on_error", "fail")

        # Handle auto_heal mode - try to fix and retry before giving up
        if on_error == "auto_heal":
            heal_type, cluster = self._detect_auto_heal_type(error_msg)

            if heal_type:
                output_lines.append(
                    f"   🩹 Detected {heal_type} error, attempting auto-heal..."
                )

                # Emit auto-heal triggered event (WebSocket)
                if self.ws_server and self.ws_server.is_running:
                    # Get current step index from event_emitter or calculate it
                    step_idx = (
                        self.event_emitter.current_step_index
                        if self.event_emitter
                        else 0
                    )
                    asyncio.create_task(
                        self.ws_server.auto_heal_triggered(
                            skill_id=self.skill_id,
                            step_index=step_idx,
                            error_type=heal_type,
                            fix_action=(
                                f"kube_login({cluster})"
                                if heal_type == "auth"
                                else "vpn_connect()"
                            ),
                            error_snippet=error_msg[:200],
                        )
                    )

                # Emit toast notification for auto-heal triggered
                try:
                    from tool_modules.aa_workflow.src.notification_emitter import (
                        notify_auto_heal_triggered,
                    )

                    fix_action = (
                        f"kube_login({cluster})"
                        if heal_type == "auth"
                        else "vpn_connect()"
                    )
                    notify_auto_heal_triggered(step_name, heal_type, fix_action)
                except Exception as exc:
                    logger.debug("Suppressed error: %s", exc)

                retry_result = await self._attempt_auto_heal(
                    heal_type, cluster, tool, step, output_lines
                )

                if retry_result and retry_result.get("success"):
                    # Auto-heal worked! Store result and continue
                    output_lines.append("   ✅ Auto-heal successful!")
                    output_name = step.get("output", step_name)
                    self.context[output_name] = retry_result["result"]
                    self._parse_and_store_tool_result(
                        retry_result["result"], output_name
                    )

                    # Log success to memory
                    await self._log_auto_heal_to_memory(
                        tool, heal_type, error_msg[:100], success=True
                    )

                    # Emit auto-heal completed event (WebSocket)
                    if self.ws_server and self.ws_server.is_running:
                        step_idx = (
                            self.event_emitter.current_step_index
                            if self.event_emitter
                            else 0
                        )
                        asyncio.create_task(
                            self.ws_server.auto_heal_completed(
                                skill_id=self.skill_id,
                                step_index=step_idx,
                                fix_action=heal_type,
                                success=True,
                            )
                        )

                    # Emit toast notification for auto-heal success
                    try:
                        from tool_modules.aa_workflow.src.notification_emitter import (
                            notify_auto_heal_succeeded,
                        )

                        notify_auto_heal_succeeded(step_name, heal_type)
                    except Exception as exc:
                        logger.debug("Suppressed error: %s", exc)

                    self.step_results.append(
                        {
                            "step": step_name,
                            "tool": tool,
                            "success": True,
                            "auto_healed": True,
                            "heal_type": heal_type,
                        }
                    )
                    return True
                else:
                    # Auto-heal failed, log and continue
                    output_lines.append("   ⚠️ Auto-heal failed, continuing anyway...")
                    await self._log_auto_heal_to_memory(
                        tool, heal_type, error_msg[:100], success=False
                    )

                    # Emit auto-heal completed (failed) event (WebSocket)
                    if self.ws_server and self.ws_server.is_running:
                        step_idx = (
                            self.event_emitter.current_step_index
                            if self.event_emitter
                            else 0
                        )
                        asyncio.create_task(
                            self.ws_server.auto_heal_completed(
                                skill_id=self.skill_id,
                                step_index=step_idx,
                                fix_action=heal_type,
                                success=False,
                            )
                        )

                    # Emit toast notification for auto-heal failure
                    try:
                        from tool_modules.aa_workflow.src.notification_emitter import (
                            notify_auto_heal_failed,
                        )

                        notify_auto_heal_failed(step_name, error_msg[:100])
                    except Exception as exc:
                        logger.debug("Suppressed error: %s", exc)
            else:
                output_lines.append("   ℹ️ Error not auto-healable, continuing...")

            # Fall through to continue behavior
            output_lines.append("   *Continuing despite error (on_error: auto_heal)*\n")

            # Set output variable to None so downstream compute steps don't crash
            # with NameError when referencing this step's output
            output_name = step.get("output", step_name)
            if output_name not in self.context:
                self.context[output_name] = None

            # Layer 5: Learn from this error
            tool_params = {}
            if "args" in step:
                args_data = step["args"]
                if isinstance(args_data, dict):
                    tool_params = {
                        k: self._template(str(v)) for k, v in args_data.items()
                    }

            await self._learn_from_error(
                tool_name=tool, params=tool_params, error_msg=error_msg
            )

            self.step_results.append(
                {
                    "step": step_name,
                    "tool": tool,
                    "success": False,
                    "error": error_msg,
                    "auto_heal_attempted": heal_type is not None,
                }
            )
            return True

        if self.create_issue_fn:
            skill_name = self.skill.get("name", "unknown")
            context = f"Skill: {skill_name}, Step: {step_name}"

            try:
                issue_result = await self.create_issue_fn(
                    tool=tool,
                    error=error_msg,
                    context=context,
                    skill=skill_name,
                )

                if issue_result["success"]:
                    output_lines.append(
                        f"\n   🐛 **Issue created:** {issue_result['issue_url']}"
                    )
                elif issue_result.get("issue_url"):
                    output_lines.append("\n   💡 **Report this error:**")
                    output_lines.append(
                        f"   📝 [Create GitHub Issue]({issue_result['issue_url']})"
                    )
            except Exception as e:
                self._debug(f"Failed to create issue: {e}")

        if on_error == "continue":
            output_lines.append("   *Continuing despite error (on_error: continue)*\n")

            # Set output variable to None so downstream compute steps don't crash
            # with NameError when referencing this step's output
            output_name = step.get("output", step_name)
            if output_name not in self.context:
                self.context[output_name] = None

            # Log to Python logger for journalctl visibility
            skill_name = self.skill.get("name", "unknown")
            logger.warning(
                f"Skill '{skill_name}' step '{step_name}' failed with on_error=continue: "
                f"tool={tool}, error={error_msg[:200]}"
            )

            # Layer 5: Learn from this error
            tool_params = {}
            if "args" in step:
                args_data = step["args"]
                if isinstance(args_data, dict):
                    tool_params = {
                        k: self._template(str(v)) for k, v in args_data.items()
                    }

            await self._learn_from_error(
                tool_name=tool, params=tool_params, error_msg=error_msg
            )

            # Emit toast notification for continue-mode failures (helps visibility)
            try:
                from tool_modules.aa_workflow.src.notification_emitter import (
                    notify_step_failed,
                )

                notify_step_failed(skill_name, step_name, error_msg[:150])
            except Exception as exc:
                logger.debug("Suppressed error: %s", exc)

            self.step_results.append(
                {
                    "step": step_name,
                    "tool": tool,
                    "success": False,
                    "error": error_msg,
                }
            )
            return True
        else:
            return False

    def _detect_soft_failure(self, result_text: str) -> tuple[bool, str | None]:
        """Detect if a successful tool result actually contains an error (soft failure).

        Many tools return success=True but include error messages in the result text.
        This method detects those cases so auto-heal can be triggered.

        Returns:
            (is_soft_failure, error_message) - True if result contains error patterns
        """
        if not result_text:
            return False, None

        result_lower = result_text.lower()

        # Patterns that indicate a soft failure (tool returned success but result is an error)
        soft_failure_patterns = [
            # Explicit failure markers
            ("❌ failed", "Tool returned failure marker"),
            ("❌ error", "Tool returned error marker"),
            # Network/DNS errors
            ("no such host", "DNS resolution failed - VPN may be disconnected"),
            ("dial tcp", "TCP connection failed - network issue"),
            ("connection refused", "Connection refused - service may be down"),
            ("no route to host", "No route to host - VPN may be disconnected"),
            ("network unreachable", "Network unreachable - VPN may be disconnected"),
            # Auth errors
            ("unauthorized", "Authentication failed - token may be expired"),
            ("forbidden", "Access forbidden - permissions issue"),
            ("401", "HTTP 401 - authentication required"),
            ("403", "HTTP 403 - access forbidden"),
            ("token expired", "Token expired - need to re-authenticate"),
            # Cluster errors
            (
                "the server has asked for the client to provide credentials",
                "Kubernetes auth required",
            ),
            ("error from server", "Kubernetes API error"),
            # Bonfire/ephemeral errors
            ("traceback (most recent call last)", "Python exception in tool"),
        ]

        for pattern, error_desc in soft_failure_patterns:
            if pattern in result_lower:
                # Extract a snippet around the error for context
                idx = result_lower.find(pattern)
                start = max(0, idx - 50)
                end = min(len(result_text), idx + len(pattern) + 100)
                snippet = result_text[start:end].strip()
                return True, f"{error_desc}: ...{snippet}..."

        return False, None
