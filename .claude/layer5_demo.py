#!/usr/bin/env python3
"""
Demonstration of Layer 5: Usage Pattern Learning

This script shows the complete flow:
1. Classify a usage error
2. Extract the pattern
3. Store it
4. Load and display

Run: python .claude/layer5_demo.py
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from server.usage_pattern_classifier import classify_error_type, is_learnable_error
from server.usage_pattern_extractor import extract_usage_pattern
from server.usage_pattern_storage import UsagePatternStorage


def demo_example_1():
    """Example 1: Wrong namespace (INCORRECT_PARAMETER)"""
    print("\n" + "=" * 70)
    print("EXAMPLE 1: Wrong namespace parameter")
    print("=" * 70)

    # Simulate Claude calling bonfire_namespace_release with wrong namespace
    tool_name = "bonfire_namespace_release"
    params = {"namespace": "ephemeral-abc-123"}
    error_message = "❌ Error: Namespace 'ephemeral-abc-123' not owned by you. Cannot release."

    print(f"\nTool: {tool_name}")
    print(f"Params: {params}")
    print(f"Error: {error_message}")

    # Step 1: Classify
    print("\n--- Step 1: Classify Error ---")
    classification = classify_error_type(tool_name, params, error_message)

    print(f"  Is usage error: {classification['is_usage_error']}")
    print(f"  Category: {classification['error_category']}")
    print(f"  Confidence: {classification['confidence']:.0%}")
    print(f"  Learnable: {is_learnable_error(classification)}")

    if not classification["is_usage_error"]:
        print("  Not a usage error, skipping...")
        return

    # Step 2: Extract pattern
    print("\n--- Step 2: Extract Pattern ---")
    pattern = extract_usage_pattern(tool_name, params, error_message, classification)

    print(f"  Pattern ID: {pattern['id']}")
    print(f"  Root cause: {pattern['root_cause']}")
    print("  Prevention steps:")
    for i, step in enumerate(pattern["prevention_steps"], 1):
        print(f"    {i}. {step['action']}: {step.get('reason', 'N/A')}")

    # Step 3: Store pattern
    print("\n--- Step 3: Store Pattern ---")
    storage = UsagePatternStorage()
    success = storage.add_pattern(pattern)
    print(f"  Stored: {success}")

    return pattern["id"]


def demo_example_2():
    """Example 2: Short SHA (PARAMETER_FORMAT)"""
    print("\n" + "=" * 70)
    print("EXAMPLE 2: Short SHA format error")
    print("=" * 70)

    tool_name = "bonfire_deploy"
    params = {"namespace": "ephemeral-def-456", "image_tag": "74ec56e"}
    error_message = "❌ Error: manifest unknown: manifest unknown"

    print(f"\nTool: {tool_name}")
    print(f"Params: {params}")
    print(f"Error: {error_message}")

    # Classify
    print("\n--- Step 1: Classify Error ---")
    classification = classify_error_type(tool_name, params, error_message)

    print(f"  Is usage error: {classification['is_usage_error']}")
    print(f"  Category: {classification['error_category']}")
    print(f"  Confidence: {classification['confidence']:.0%}")
    print(f"  Evidence: image_tag='{params['image_tag']}' (length: {len(params['image_tag'])})")

    # Extract
    print("\n--- Step 2: Extract Pattern ---")
    pattern = extract_usage_pattern(tool_name, params, error_message, classification)

    print(f"  Pattern ID: {pattern['id']}")
    print(f"  Root cause: {pattern['root_cause']}")
    print(f"  Expected format: {pattern['mistake_pattern'].get('validation', {}).get('expected')}")
    print("  Prevention steps:")
    for i, step in enumerate(pattern["prevention_steps"], 1):
        print(f"    {i}. {step['action']}: {step.get('reason', 'N/A')}")

    # Store
    print("\n--- Step 3: Store Pattern ---")
    storage = UsagePatternStorage()
    success = storage.add_pattern(pattern)
    print(f"  Stored: {success}")

    return pattern["id"]


def demo_example_3():
    """Example 3: Workflow sequence (WORKFLOW_SEQUENCE)"""
    print("\n" + "=" * 70)
    print("EXAMPLE 3: Workflow sequence error")
    print("=" * 70)

    tool_name = "gitlab_mr_create"
    params = {"title": "Add new feature", "source_branch": "feature-xyz"}
    error_message = "❌ Error: branch not on remote. Push your branch first."

    print(f"\nTool: {tool_name}")
    print(f"Params: {params}")
    print(f"Error: {error_message}")

    # Classify
    print("\n--- Step 1: Classify Error ---")
    classification = classify_error_type(tool_name, params, error_message)

    print(f"  Is usage error: {classification['is_usage_error']}")
    print(f"  Category: {classification['error_category']}")
    print(f"  Confidence: {classification['confidence']:.0%}")
    print(f"  Missing prerequisite: {classification['evidence'].get('missing_prerequisite')}")

    # Extract
    print("\n--- Step 2: Extract Pattern ---")
    pattern = extract_usage_pattern(tool_name, params, error_message, classification)

    print(f"  Pattern ID: {pattern['id']}")
    print(f"  Root cause: {pattern['root_cause']}")
    print(f"  Correct sequence: {pattern['mistake_pattern'].get('correct_sequence')}")
    print("  Prevention steps:")
    for i, step in enumerate(pattern["prevention_steps"], 1):
        print(f"    {i}. {step['action']}: {step.get('reason', 'N/A')}")

    # Store
    print("\n--- Step 3: Store Pattern ---")
    storage = UsagePatternStorage()
    success = storage.add_pattern(pattern)
    print(f"  Stored: {success}")

    return pattern["id"]


def demo_storage_operations():
    """Demonstrate storage operations"""
    print("\n" + "=" * 70)
    print("STORAGE OPERATIONS")
    print("=" * 70)

    storage = UsagePatternStorage()

    # Load all patterns
    data = storage.load()
    patterns = data.get("usage_patterns", [])

    print(f"\nTotal patterns: {len(patterns)}")
    print("\nStatistics:")
    stats = data.get("stats", {})
    print(f"  High confidence (>=0.85): {stats.get('high_confidence', 0)}")
    print(f"  Medium confidence (0.70-0.84): {stats.get('medium_confidence', 0)}")
    print(f"  Low confidence (<0.70): {stats.get('low_confidence', 0)}")

    print("\nBy category:")
    by_cat = stats.get("by_category", {})
    for cat, count in by_cat.items():
        if count > 0:
            print(f"  {cat}: {count}")

    # Show high-confidence patterns
    high_conf = storage.get_high_confidence_patterns(min_confidence=0.75)
    print("\nHigh-confidence patterns (>= 75%):")
    for pattern in high_conf[:5]:  # Show first 5
        print(f"  - {pattern['tool']}: {pattern['root_cause']}")
        print(f"    Confidence: {pattern['confidence']:.0%}, Observations: {pattern['observations']}")


def main():
    """Run all demos"""
    print("\n" + "#" * 70)
    print("# Layer 5: Usage Pattern Learning - Demonstration")
    print("#" * 70)

    # Run examples
    pattern_id_1 = demo_example_1()
    pattern_id_2 = demo_example_2()
    pattern_id_3 = demo_example_3()

    # Show storage
    demo_storage_operations()

    print("\n" + "#" * 70)
    print("# Demo Complete!")
    print("#" * 70)

    print("\nCreated patterns:")
    print(f"  1. {pattern_id_1}")
    print(f"  2. {pattern_id_2}")
    print(f"  3. {pattern_id_3}")

    print("\nPatterns stored in: memory/learned/usage_patterns.yaml")
    print("\nNext steps:")
    print("  - Phase 2: Implement pattern merging & confidence evolution")
    print("  - Phase 3: Implement pre-tool-call warnings")
    print("  - Phase 4: Integrate with Claude context")


if __name__ == "__main__":
    main()
