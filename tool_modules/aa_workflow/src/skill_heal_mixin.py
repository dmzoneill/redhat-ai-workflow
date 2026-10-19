# pylint: disable=duplicate-code,cyclic-import
"""Split from skill_engine.py so the public module stays importable."""

import asyncio
import logging
from datetime import datetime
from typing import Any

import yaml

from .skill_paths import skills_dir

logger = logging.getLogger(__name__)


class SkillHealMixin:
    """SkillExecutor behavior split out of skill_engine."""

    # Declared for mixins that read sibling state.
    _debug: Any
    _exec_tool: Any
    _template_dict: Any
    event_emitter: Any

    def _find_matched_pattern(self, error_lower: str) -> tuple[dict | None, str | None]:
        """Find a matching pattern from memory based on error text.

        Returns:
            (matched_pattern, pattern_category) tuple or (None, None)
        """
        try:
            patterns_file = skills_dir().parent / "memory" / "learned" / "patterns.yaml"
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
        except Exception as e:  # pylint: disable=broad-exception-caught
            self._debug(f"Pattern lookup failed: {e}")

        return None, None

    def _determine_fix_type(  # pylint: disable=too-many-return-statements
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
        if any(p in error_lower for p in network_patterns):
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
        import asyncio  # pylint: disable=import-outside-toplevel,redefined-outer-name,reimported
        import os  # pylint: disable=import-outside-toplevel

        try:
            # Try to use the configured VPN script first (same as vpn_connect tool)
            from server.utils import (  # pylint: disable=import-outside-toplevel
                load_config,
            )

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
                        self._debug(f"  → VPN connect result: success with {vpn_name}")
                        await asyncio.sleep(2)
                        return True
                except asyncio.TimeoutError:
                    continue

            self._debug("  → All VPN connection attempts failed")
            return False

        except Exception as e:  # pylint: disable=broad-exception-caught
            self._debug(f"  → Auto-fix failed: {e}")
            return False

    async def _apply_auth_fix(self, error_lower: str) -> bool:
        """Apply kube login fix."""
        import asyncio  # pylint: disable=import-outside-toplevel,redefined-outer-name,reimported

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
        except Exception as e:  # pylint: disable=broad-exception-caught
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
            import fcntl  # pylint: disable=import-outside-toplevel

            patterns_file = skills_dir().parent / "memory" / "learned" / "patterns.yaml"
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

        except Exception as e:  # pylint: disable=broad-exception-caught
            self._debug(f"Failed to update pattern stats: {e}")

    def _check_error_patterns(self, error: str) -> str | None:
        """Check if error matches known patterns and return fix suggestion."""
        try:
            patterns_file = skills_dir().parent / "memory" / "learned" / "patterns.yaml"
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
        except Exception as e:  # pylint: disable=broad-exception-caught
            self._debug(f"Pattern lookup failed: {e}")
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
                    # pylint: disable-next=line-too-long
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
                    # pylint: disable-next=line-too-long
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

        except Exception as e:  # pylint: disable=broad-exception-caught
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
            from datetime import (  # pylint: disable=import-outside-toplevel,redefined-outer-name,reimported
                datetime,
            )

            import yaml  # pylint: disable=import-outside-toplevel,redefined-outer-name,reimported

            # Find memory directory
            memory_dir = skills_dir().parent / "memory" / "learned"
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

        except Exception as e:  # pylint: disable=broad-exception-caught
            self._debug(f"Failed to log auto-heal to memory: {e}")

    def find_matched_pattern(self, *args, **kwargs):
        """Return the learned pattern that matches this failure."""
        return self._find_matched_pattern(*args, **kwargs)

    def determine_fix_type(self, *args, **kwargs):
        """Classify which automatic fix applies to this failure."""
        return self._determine_fix_type(*args, **kwargs)

    def detect_auto_heal_type(self, *args, **kwargs):
        """Detect the auto-heal category for this failure."""
        return self._detect_auto_heal_type(*args, **kwargs)

    async def attempt_auto_heal(self, *args, **kwargs):
        """Try the automatic fix and return whether it succeeded."""
        return await self._attempt_auto_heal(*args, **kwargs)

    async def log_auto_heal_to_memory(self, *args, **kwargs):
        """Record an auto-heal attempt in skill memory."""
        return await self._log_auto_heal_to_memory(*args, **kwargs)

    def update_pattern_usage_stats(self, *args, **kwargs):
        """Update how often a learned fix pattern has been used."""
        return self._update_pattern_usage_stats(*args, **kwargs)

    async def try_auto_fix(self, *args, **kwargs):
        """Apply the selected automatic fix."""
        return await self._try_auto_fix(*args, **kwargs)

    async def apply_network_fix(self):
        """Retry the step after a transient network failure."""
        return await self._apply_network_fix()

    async def apply_auth_fix(self, *args, **kwargs):
        """Refresh credentials and retry the step."""
        return await self._apply_auth_fix(*args, **kwargs)
