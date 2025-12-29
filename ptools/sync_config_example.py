#!/usr/bin/env python3
"""
Ensure config.json.example has all keys from config.json.

Compares the structure of config.json and config.json.example,
reporting any keys that exist in config.json but are missing from the example.

Usage:
    python ptools/sync_config_example.py              # Check for missing keys
    python ptools/sync_config_example.py --fix        # Add missing keys with placeholders
    python ptools/sync_config_example.py --verbose    # Show all compared keys
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_FILE = PROJECT_ROOT / "config.json"
EXAMPLE_FILE = PROJECT_ROOT / "config.json.example"


def get_all_keys(obj: Any, prefix: str = "") -> set[str]:
    """Recursively get all keys from a nested dict/list structure."""
    keys = set()

    if isinstance(obj, dict):
        for key, value in obj.items():
            full_key = f"{prefix}.{key}" if prefix else key
            keys.add(full_key)
            keys.update(get_all_keys(value, full_key))
    elif isinstance(obj, list) and obj:
        # For lists, check the first element's structure
        keys.update(get_all_keys(obj[0], f"{prefix}[]"))

    return keys


def get_value_at_path(obj: Any, path: str) -> Any:
    """Get value at a dot-separated path."""
    parts = path.replace("[]", ".0").split(".")
    current = obj

    for part in parts:
        if not part:
            continue
        if isinstance(current, dict):
            if part not in current:
                return None
            current = current[part]
        elif isinstance(current, list):
            idx = int(part) if part.isdigit() else 0
            if idx >= len(current):
                return None
            current = current[idx]
        else:
            return None

    return current


def set_value_at_path(obj: dict, path: str, value: Any) -> None:
    """Set a value at a dot-separated path, creating intermediate dicts as needed."""
    parts = path.replace("[]", "").split(".")
    current = obj

    for _i, part in enumerate(parts[:-1]):
        if not part:
            continue
        if part not in current:
            current[part] = {}
        current = current[part]

    final_key = parts[-1]
    if final_key:
        current[final_key] = value


def generate_placeholder(key: str, actual_value: Any) -> Any:
    """Generate a placeholder value based on the key name and actual value type."""
    key_lower = key.lower()

    # Determine type from actual value
    if isinstance(actual_value, bool):
        return False
    elif isinstance(actual_value, int):
        return 0
    elif isinstance(actual_value, float):
        return 0.0
    elif isinstance(actual_value, list):
        return []
    elif isinstance(actual_value, dict):
        return {}
    elif isinstance(actual_value, str):
        # Generate meaningful placeholders based on key name
        if "token" in key_lower:
            return "YOUR_TOKEN_HERE"
        elif "cookie" in key_lower:
            return "YOUR_COOKIE_HERE"
        elif "password" in key_lower or "secret" in key_lower:
            return "YOUR_SECRET_HERE"
        elif "key" in key_lower and "api" in key_lower:
            return "YOUR_API_KEY_HERE"
        elif "url" in key_lower:
            return "https://example.com"
        elif "path" in key_lower:
            return "/path/to/something"
        elif "id" in key_lower:
            return "YOUR_ID_HERE"
        elif "email" in key_lower:
            return "user@example.com"
        elif "name" in key_lower:
            return "example-name"
        elif "host" in key_lower:
            return "example.com"
        elif "description" in key_lower:
            return actual_value  # Keep descriptions as-is
        else:
            # Mask actual value if it looks like a credential
            if len(actual_value) > 20 and re.match(r"^[a-zA-Z0-9_\-]+$", actual_value):
                return "YOUR_VALUE_HERE"
            return actual_value
    else:
        return None


def compare_configs(config: dict, example: dict, verbose: bool = False) -> tuple[set[str], set[str]]:
    """Compare config keys and return (missing_in_example, extra_in_example)."""
    config_keys = get_all_keys(config)
    example_keys = get_all_keys(example)

    missing_in_example = config_keys - example_keys
    extra_in_example = example_keys - config_keys

    if verbose:
        print("\n📊 Key Statistics:")
        print(f"   config.json keys: {len(config_keys)}")
        print(f"   config.json.example keys: {len(example_keys)}")
        print(f"   Missing in example: {len(missing_in_example)}")
        print(f"   Extra in example: {len(extra_in_example)}")

    return missing_in_example, extra_in_example


def fix_example(config: dict, example: dict, missing_keys: set[str]) -> dict:
    """Add missing keys to example with placeholder values."""
    # Sort keys to process parent keys before children
    sorted_keys = sorted(missing_keys, key=lambda k: k.count("."))

    for key in sorted_keys:
        # Skip array index keys (handled by parent)
        if "[]" in key:
            continue

        actual_value = get_value_at_path(config, key)
        placeholder = generate_placeholder(key, actual_value)

        # Only set if the immediate parent exists or we can create it
        set_value_at_path(example, key, placeholder)

    return example


def main():
    parser = argparse.ArgumentParser(description="Ensure config.json.example has all keys from config.json")
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Add missing keys to config.json.example with placeholders",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed comparison")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Also warn about extra keys in example that aren't in config",
    )

    args = parser.parse_args()

    # Check files exist
    if not CONFIG_FILE.exists():
        print(f"❌ Config file not found: {CONFIG_FILE}")
        return 1

    if not EXAMPLE_FILE.exists():
        print(f"❌ Example file not found: {EXAMPLE_FILE}")
        return 1

    # Load configs
    try:
        config = json.loads(CONFIG_FILE.read_text())
        example = json.loads(EXAMPLE_FILE.read_text())
    except json.JSONDecodeError as e:
        print(f"❌ JSON parse error: {e}")
        return 1

    print("\n🔍 Comparing config.json with config.json.example...")

    # Compare
    missing_in_example, extra_in_example = compare_configs(config, example, verbose=args.verbose)

    # Report missing keys
    if missing_in_example:
        print("\n⚠️  Keys in config.json but MISSING from config.json.example:")
        for key in sorted(missing_in_example):
            actual_value = get_value_at_path(config, key)
            value_type = type(actual_value).__name__
            print(f"   ❌ {key} ({value_type})")

        if args.fix:
            print("\n🔧 Adding missing keys with placeholder values...")
            fixed_example = fix_example(config, example, missing_in_example)

            # Write back with pretty formatting
            EXAMPLE_FILE.write_text(json.dumps(fixed_example, indent=2, ensure_ascii=False) + "\n")
            print(f"✅ Updated {EXAMPLE_FILE.name}")
        else:
            print("\n💡 Run with --fix to add missing keys automatically")
    else:
        print("\n✅ All keys in config.json exist in config.json.example")

    # Report extra keys (optional)
    if args.strict and extra_in_example:
        print("\n📝 Keys in config.json.example but NOT in config.json:")
        for key in sorted(extra_in_example):
            print(f"   ℹ️  {key}")

    # Exit code
    if missing_in_example:
        return 1 if not args.fix else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
