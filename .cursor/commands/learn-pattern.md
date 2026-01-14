# 📚 Learn Pattern

Save a new error pattern to memory for future recognition.

## Usage

When you discover an error pattern and its fix, teach the AI to remember it:

```text
skill_run("learn_pattern", '{"pattern": "OOMKilled", "meaning": "Container exceeded memory limit", "fix": "Increase memory limits"}')
```

## Categories

- **pod_errors**: Kubernetes pod issues (CrashLoopBackOff, ImagePullBackOff, etc.)
- **log_patterns**: Error messages found in logs
- **network**: Network-related issues
- **general**: Default category

## Example

```text
/learn-pattern
Pattern: ImagePullBackOff
Meaning: Kubernetes cannot pull the container image
Fix: Check image name, tag, and registry credentials
Commands: kubectl describe pod X, kubectl get events
Category: pod_errors
```

The pattern will be saved and automatically matched during `investigate_alert` and `debug_prod` skills.
