"""Ollama MCP Server - Local inference tools for NPU/GPU/CPU.

Provides tools for:
- Checking Ollama instance status
- Running inference on specific instances
- Classification tasks
- Tool pre-filtering (via HybridToolFilter)
"""

import logging

from fastmcp import FastMCP
from mcp.types import TextContent

# Setup project path for server imports (must be before server imports)
from tool_modules.common import PROJECT_ROOT  # Sets up sys.path

__project_root__ = PROJECT_ROOT  # Module initialization

from server.tool_registry import ToolRegistry

from .client import get_all_status, get_available_client, get_client
from .instances import get_instance_names

logger = logging.getLogger(__name__)


# ==================== Tool Registration ====================


# pylint: disable-next=too-many-statements
def register_tools(server: "FastMCP") -> int:
    """Register tools with the MCP server."""
    registry = ToolRegistry(server)

    @registry.tool()
    async def ollama_status() -> list[TextContent]:
        """
        Get status of all configured Ollama instances.

        Shows which instances are online, their models, latency, and power consumption.
        Useful for checking inference availability before running tasks.

        Returns:
            Status of all Ollama instances (NPU, iGPU, NVIDIA, CPU).
        """
        status = get_all_status()

        lines = [
            "## 🖥️ Ollama Instance Status",
            "",
        ]

        for name, info in status.items():
            # Status indicator
            if info["available"]:
                indicator = "🟢"
                status_text = "Online"
            else:
                indicator = "⚫"
                status_text = "Offline"

            lines.extend(
                [
                    f"### {indicator} {name.upper()}",
                    f"- **Status:** {status_text}",
                    f"- **Host:** `{info['host']}`",
                    f"- **Model:** `{info['model']}`",
                    f"- **Power:** {info['power_watts']}",
                ]
            )

            if info["available"] and info["samples"] > 0:
                lines.append(f"- **Avg Latency:** {info['avg_latency_ms']:.0f}ms")

            if info["best_for"]:
                lines.append(f"- **Best for:** {', '.join(info['best_for'])}")

            lines.append("")

        # Summary
        online_count = sum(1 for s in status.values() if s["available"])
        lines.extend(
            [
                "---",
                f"**Summary:** {online_count}/{len(status)} instances online",
            ]
        )

        return [TextContent(type="text", text="\n".join(lines))]

    @registry.tool()
    # pylint: disable-next=too-many-arguments,too-many-positional-arguments
    async def ollama_generate(
        prompt: str,
        instance: str = "npu",
        model: str = "",
        max_tokens: int = 100,
        temperature: float = 0.0,
        system: str = "",
    ) -> list[TextContent]:
        """
        Generate text using a local Ollama instance.

        Args:
            prompt: The prompt to complete
            instance: Which instance to use (npu, igpu, nvidia, cpu)
            model: Model to use (defaults to instance default)
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (0 = deterministic)
            system: Optional system prompt

        Returns:
            Generated text from the model.
        """
        if instance not in get_instance_names():
            return [
                TextContent(
                    type="text",
                    text=(
                        f"❌ Unknown instance: `{instance}`\n\n"
                        f"Available: {', '.join(get_instance_names())}"
                    ),
                )
            ]

        client = get_client(instance)

        if not client.is_available():
            return [
                TextContent(
                    type="text",
                    text=(
                        f"❌ Instance `{instance}` is offline\n\n"
                        "Try: `ollama_status` to see available instances"
                    ),
                )
            ]

        try:
            result = client.generate(
                prompt=prompt,
                model=model if model else None,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system if system else None,
            )

            lines = [
                f"## 🤖 Response from {instance.upper()}",
                "",
                result,
                "",
                "---",
                (
                    f"*Model: {model or client.default_model} | "
                    f"Latency: {client.last_latency_ms:.0f}ms*"
                ),
            ]

            return [TextContent(type="text", text="\n".join(lines))]

        # Intentional: convert the failure into an error result for the caller.
        except Exception as e:  # pylint: disable=broad-exception-caught
            return [TextContent(type="text", text=f"❌ Generation failed: {e}")]

    @registry.tool()
    async def ollama_classify(
        text: str,
        categories: str,
        instance: str = "npu",
    ) -> list[TextContent]:
        """
        Classify text into one of the given categories using local inference.

        Args:
            text: Text to classify
            categories: Comma-separated list of category names
            instance: Which instance to use (default: npu for low power)

        Returns:
            The matched category.
        """
        category_list = [c.strip() for c in categories.split(",") if c.strip()]

        if not category_list:
            return [TextContent(type="text", text="❌ No categories provided")]

        if len(category_list) < 2:
            return [TextContent(type="text", text="❌ Need at least 2 categories")]

        client = get_client(instance)

        if not client.is_available():
            # Try fallback
            fallback = get_available_client(instance)
            if fallback is None:
                return [
                    TextContent(
                        type="text",
                        text=(
                            "❌ No inference instances available\n\n"
                            "Start Ollama with: `ollama serve`"
                        ),
                    )
                ]
            client = fallback

        result = client.classify(text, category_list)

        if result:
            return [
                TextContent(
                    type="text",
                    text=(
                        f"**Category:** `{result}`\n\n"
                        f"*Classified by {client.name} in {client.last_latency_ms:.0f}ms*"
                    ),
                )
            ]
        return [
            TextContent(
                type="text", text="❌ Classification failed - no category matched"
            )
        ]

    @registry.tool()
    async def ollama_test(
        instance: str = "npu",
    ) -> list[TextContent]:
        """
        Quick test of an Ollama instance.

        Sends a simple prompt to verify the instance is working correctly.

        Args:
            instance: Which instance to test (npu, igpu, nvidia, cpu)

        Returns:
            Test result with latency.
        """
        if instance not in get_instance_names():
            return [
                TextContent(
                    type="text",
                    text=(
                        f"❌ Unknown instance: `{instance}`\n\n"
                        f"Available: {', '.join(get_instance_names())}"
                    ),
                )
            ]

        client = get_client(instance)

        if not client.is_available():
            return [
                TextContent(
                    type="text",
                    text=(
                        f"❌ Instance `{instance}` is offline\n\n"
                        f"**Host:** `{client.host}`\n\nStart with: `ollama serve`"
                    ),
                )
            ]

        try:
            # Simple test prompt
            result = client.generate(
                prompt="Say 'Hello' in exactly one word:",
                max_tokens=10,
                temperature=0,
            )

            return [
                TextContent(
                    type="text",
                    text=f"""## ✅ {instance.upper()} Test Passed

**Response:** {result.strip()}
**Model:** `{client.default_model}`
**Latency:** {client.last_latency_ms:.0f}ms
**Power:** {client.instance.power_watts}

Instance is ready for inference.""",
                )
            ]

        # Intentional: convert the failure into an error result for the caller.
        except Exception as e:  # pylint: disable=broad-exception-caught
            return [TextContent(type="text", text=f"❌ Test failed: {e}")]

    @registry.tool()
    async def inference_available() -> list[TextContent]:
        """
        Check if any local inference is available.

        Returns which instance would be used for tool filtering.

        Returns:
            Inference availability status.
        """
        client = get_available_client()

        if client:
            return [
                TextContent(
                    type="text",
                    text=f"""## ✅ Local Inference Available

**Active Instance:** {client.name.upper()}
**Model:** `{client.default_model}`
**Power:** {client.instance.power_watts}

Tool pre-filtering is enabled and will use this instance for classification.""",
                )
            ]
        return [
            TextContent(
                type="text",
                text="""## ⚠️ No Local Inference Available

All Ollama instances are offline. Tool filtering will use fallback strategy:
- Keyword matching (regex-based)
- Expanded baseline categories

To enable NPU inference:
1. Start Ollama: `ollama serve`
2. Pull model: `ollama pull qwen2.5:0.5b`
3. Verify: `ollama_status`""",
            )
        ]

    @registry.tool()
    async def inference_stats() -> list[TextContent]:
        """
        Get inference/tool filtering statistics.

        Returns statistics about tool filtering effectiveness including:
        - Total requests
        - Per-persona statistics (min, max, mean, median tools)
        - Latency distribution
        - Cache hit rate
        - Recent history

        Returns:
            Inference statistics for dashboard.
        """
        try:
            from .tool_filter import (  # pylint: disable=import-outside-toplevel
                get_filter,
            )

            filter_instance = get_filter()
            stats = filter_instance.get_stats()

            import json  # pylint: disable=import-outside-toplevel

            return [
                TextContent(
                    type="text",
                    text=json.dumps(stats, indent=2),
                )
            ]
        # Intentional: convert the failure into an error result for the caller.
        except Exception as e:  # pylint: disable=broad-exception-caught
            return [TextContent(type="text", text=f"❌ Failed to get stats: {e}")]

    @registry.tool()
    async def inference_test(
        message: str,
        persona: str = "developer",
        skill: str = "",
    ) -> list[TextContent]:
        """
        Test tool filtering with a specific message.

        Runs the 4-layer filter and returns detailed results showing:
        - Which layers were used
        - How many tools from each layer
        - Final tool list
        - Latency

        Args:
            message: Test message to filter tools for
            persona: Persona to use (developer, devops, incident, release)
            skill: Optional skill name (auto-detected if empty)

        Returns:
            Detailed filter results.
        """
        try:
            # pylint: disable-next=import-outside-toplevel
            from .tool_filter import filter_tools_detailed

            result = filter_tools_detailed(
                message=message,
                persona=persona,
                detected_skill=skill if skill else None,
            )

            import json  # pylint: disable=import-outside-toplevel

            return [
                TextContent(
                    type="text",
                    text=json.dumps(result, indent=2),
                )
            ]
        # Intentional: convert the failure into an error result for the caller.
        except Exception as e:  # pylint: disable=broad-exception-caught
            return [TextContent(type="text", text=f"❌ Inference test failed: {e}")]

    return registry.count
