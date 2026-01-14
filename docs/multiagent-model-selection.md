# Multi-Agent Model Selection Strategy

## Overview

The multi-agent code review system uses **different LLMs for different agents** to optimize for cost, speed, and quality. Each agent is assigned the model best suited for its task complexity.

## Default Model Assignment

| Agent | Model | Max Tokens | Rationale |
|-------|-------|------------|-----------|
| 🏗️ **Architecture** | Sonnet 4.5 | 2000 | Deep reasoning for design patterns |
| 🔒 **Security** | Sonnet 4.5 | 2000 | Critical analysis for vulnerabilities |
| ⚡ **Performance** | Sonnet 3.7 | 1500 | Good balance for optimization |
| 🧪 **Testing** | Sonnet 3.7 | 1500 | Solid analysis for test coverage |
| 📝 **Documentation** | Haiku 3.5 | 1000 | Fast for simple doc checks |
| 🎨 **Style** | Haiku 3.5 | 1000 | Quick for formatting review |
| 🎯 **Coordinator** | Sonnet 4.5 | 3000 | Synthesis requires reasoning |

## Model Tiers

### 🌟 Opus 4.5 (Reserved)
**Model:** `claude-opus-4-5-20251101`

**Best For:**
- Mission-critical code reviews
- Complex architectural decisions
- High-stakes security audits
- When accuracy > cost

**Cost:** ~10x Haiku
**Speed:** Slowest (30-60s per agent)

**Use Cases:**
```bash
# Emergency security audit for production hotfix
agents_config["security"]["model"] = "claude-opus-4-5-20251101"

# Critical architecture review for microservices refactor
agents_config["architecture"]["model"] = "claude-opus-4-5-20251101"
```

### 🎯 Sonnet 4.5 (Premium)
**Model:** `claude-sonnet-4-5-20250929`

**Best For:**
- Security analysis (vulnerabilities, exploits)
- Architecture review (design patterns)
- Complex reasoning tasks
- When quality is paramount

**Cost:** ~5x Haiku
**Speed:** Medium (10-20s per agent)

**Default Agents:** Architecture, Security, Coordinator

### ⚖️ Sonnet 3.7 (Balanced)
**Model:** `claude-sonnet-3-7-20250219`

**Best For:**
- Performance analysis (algorithms, queries)
- Testing review (coverage, edge cases)
- Good quality at moderate cost
- General-purpose reviews

**Cost:** ~3x Haiku
**Speed:** Fast (5-10s per agent)

**Default Agents:** Performance, Testing

### ⚡ Haiku 3.5 (Economical)
**Model:** `claude-3-5-haiku-20241022`

**Best For:**
- Documentation checks
- Style/formatting review
- Simple pattern matching
- High-volume reviews

**Cost:** 1x (baseline)
**Speed:** Very fast (2-5s per agent)

**Default Agents:** Documentation, Style

## Cost Optimization Strategies

### Strategy 1: Tiered Review (Default)
**When:** Standard MR review

**Config:**
```python
{
    "architecture": "sonnet-4-5",  # Deep reasoning
    "security": "sonnet-4-5",       # Critical analysis
    "performance": "sonnet-3-7",    # Good balance
    "testing": "sonnet-3-7",        # Good balance
    "documentation": "haiku-3-5",   # Fast
    "style": "haiku-3-5",           # Fast
}
```

**Cost per Review:** ~$0.12
**Time:** ~30s (parallel)

### Strategy 2: Economy Mode
**When:** High-volume reviews, low-risk changes

**Config:**
```python
{
    "architecture": "sonnet-3-7",   # Downgrade
    "security": "sonnet-4-5",        # Keep critical
    "performance": "haiku-3-5",      # Downgrade
    "testing": "haiku-3-5",          # Downgrade
    "documentation": "haiku-3-5",    # Same
    "style": "haiku-3-5",            # Same
}
```

**Cost per Review:** ~$0.06 (50% cheaper)
**Time:** ~15s (parallel)

**Trade-off:** Lower quality on architecture and performance

### Strategy 3: Premium Mode
**When:** Production releases, security-critical changes

**Config:**
```python
{
    "architecture": "opus-4-5",     # Maximum quality
    "security": "opus-4-5",          # Maximum quality
    "performance": "sonnet-4-5",     # Upgrade
    "testing": "sonnet-4-5",         # Upgrade
    "documentation": "sonnet-3-7",   # Upgrade
    "style": "sonnet-3-7",           # Upgrade
}
```

**Cost per Review:** ~$0.50 (4x more expensive)
**Time:** ~90s (parallel)

**Benefit:** Best possible quality across all dimensions

### Strategy 4: Selective Premium
**When:** Known security or architecture changes

**Config:**
```python
# Only run critical agents with premium models
{
    "architecture": "opus-4-5",
    "security": "opus-4-5",
}
# Skip other agents
```

**Cost per Review:** ~$0.20
**Time:** ~45s

**Benefit:** Focus premium attention where it matters

## Dynamic Model Selection

### Based on MR Metadata

```python
# In skill step
- name: select_models_by_context
  compute: |
    # Parse MR labels and changed files
    labels = mr_details.get("labels", [])
    files = mr_diff  # Parse changed files

    # Default economy mode
    models = {
        "architecture": "claude-sonnet-3-7-20250219",
        "security": "claude-sonnet-3-7-20250219",
        "performance": "claude-3-5-haiku-20241022",
        "testing": "claude-3-5-haiku-20241022",
        "documentation": "claude-3-5-haiku-20241022",
        "style": "claude-3-5-haiku-20241022",
    }

    # Upgrade based on labels
    if "security" in labels:
        models["security"] = "claude-opus-4-5-20251101"
        models["architecture"] = "claude-sonnet-4-5-20250929"

    if "performance" in labels:
        models["performance"] = "claude-sonnet-4-5-20250929"

    if "architecture" in labels:
        models["architecture"] = "claude-opus-4-5-20251101"

    # Upgrade based on changed files
    if any("auth" in f or "security" in f for f in files):
        models["security"] = "claude-opus-4-5-20251101"

    if any("migration" in f or "schema" in f for f in files):
        models["performance"] = "claude-sonnet-4-5-20250929"

    result = models
  output: dynamic_models
```

### Based on Code Size

```python
# Small MRs: economy mode
# Large MRs: premium for architecture

- name: adjust_by_size
  compute: |
    lines_changed = len(mr_diff.split('\n'))

    if lines_changed < 100:
        # Small change - economy
        model_tier = "economy"
    elif lines_changed < 500:
        # Medium change - standard
        model_tier = "standard"
    else:
        # Large change - need better architecture review
        model_tier = "premium_architecture"
```

### Based on Author Experience

```python
# Junior devs: more thorough review
# Senior devs: trust more, review less

- name: adjust_by_author
  compute: |
    author = mr_details.get("author")

    # Look up experience level (from config or API)
    junior_devs = ["newdev1", "intern2"]

    if author in junior_devs:
        # More thorough review for learning
        models["architecture"] = "claude-sonnet-4-5-20250929"
        models["testing"] = "claude-sonnet-4-5-20250929"
    else:
        # Standard review for experienced devs
        pass
```text

## Cost Analysis

### Per-Review Cost Breakdown

**Economy Mode** (~$0.06):
```
Haiku agents (4):    4 × $0.005 = $0.020
Sonnet 3.7 (1):      1 × $0.015 = $0.015
Sonnet 4.5 (1):      1 × $0.025 = $0.025
Coordinator:         1 × $0.025 = $0.025
Total:                           $0.085
```text

**Standard Mode** (~$0.12):
```
Haiku agents (2):    2 × $0.005 = $0.010
Sonnet 3.7 (2):      2 × $0.015 = $0.030
Sonnet 4.5 (2):      2 × $0.025 = $0.050
Coordinator:         1 × $0.025 = $0.025
Total:                           $0.115
```text

**Premium Mode** (~$0.50):
```
Sonnet 3.7 (2):      2 × $0.015 = $0.030
Sonnet 4.5 (2):      2 × $0.025 = $0.050
Opus 4.5 (2):        2 × $0.150 = $0.300
Coordinator:         1 × $0.025 = $0.025
Total:                           $0.405
```text

### Monthly Cost Projections

**Team of 10 developers, 5 MRs/day:**
- Economy: 10 × 5 × 20 × $0.06 = **$600/month**
- Standard: 10 × 5 × 20 × $0.12 = **$1,200/month**
- Premium: 10 × 5 × 20 × $0.50 = **$5,000/month**

**Mixed Strategy** (80% standard, 20% premium):
- 80% × $1,200 + 20% × $5,000 = **$1,960/month**

## Speed Optimization

### Parallel Execution (Default)
All agents run simultaneously:
```
Total time = max(agent times) ≈ slowest agent + coordinator

Economy:  max(2-5s)  + 10s = ~15s
Standard: max(5-10s) + 10s = ~20s
Premium:  max(30-60s) + 20s = ~80s
```text

### Sequential Execution
Agents run one at a time (for rate limiting):
```
Total time = sum(agent times) + coordinator

Economy:  6×5s  + 10s = ~40s
Standard: 6×10s + 10s = ~70s
Premium:  6×45s + 20s = ~290s
```

## Model Override via Input

Allow per-review model override:

```python
# Add to skill inputs
- name: model_overrides
  type: string
  required: false
  description: "JSON dict of agent:model overrides, e.g. {\"security\":\"opus-4-5\"}"

# In agent config step
- name: apply_overrides
  compute: |
    if inputs.get("model_overrides"):
        import json
        overrides = json.loads(inputs["model_overrides"])

        for agent, model in overrides.items():
            if agent in agents_config["configs"]:
                agents_config["configs"][agent]["model"] = model
```

**Usage:**
```bash
skill_run("review_pr_multiagent", '{
  "mr_id": 1482,
  "model_overrides": "{\"security\":\"claude-opus-4-5-20251101\",\"architecture\":\"claude-opus-4-5-20251101\"}"
}')
```

## Best Practices

### 1. Start with Standard Tier
Use default config for most MRs. It provides excellent quality at reasonable cost.

### 2. Reserve Opus for Critical Reviews
- Production releases
- Security patches
- Major architectural changes
- Compliance-critical code

### 3. Use Economy for High Volume
- Documentation-only changes
- Style/formatting fixes
- Dependency updates
- Bot-generated MRs

### 4. Profile Your Patterns
Track which model tier catches which issues to optimize your mix:
```python
# memory/learned/model_effectiveness.yaml
model_effectiveness:
  security:
    opus: {critical_found: 5, false_positives: 0}
    sonnet_45: {critical_found: 4, false_positives: 1}
    sonnet_37: {critical_found: 2, false_positives: 2}
```

### 5. Budget-Aware Scheduling
```python
# Check monthly spend
current_spend = get_monthly_api_cost()
budget = 1500  # $1500/month

if current_spend > budget * 0.9:
    # Last 10% of month - switch to economy
    mode = "economy"
else:
    mode = "standard"
```

## Advanced: Multi-Provider Support

### Adding OpenAI Models

```python
agent_configs = {
    "architecture": {
        "provider": "anthropic",
        "model": "claude-sonnet-4-5-20250929",
    },
    "security": {
        "provider": "anthropic",
        "model": "claude-opus-4-5-20251101",
    },
    "performance": {
        "provider": "openai",
        "model": "gpt-4-turbo",  # Alternative for perf analysis
    },
}
```

### Model Fallback Chain

```python
# Try premium, fallback to economy if rate limited
model_chain = {
    "security": [
        "claude-opus-4-5-20251101",      # Try first
        "claude-sonnet-4-5-20250929",    # Fallback 1
        "claude-sonnet-3-7-20250219",    # Fallback 2
    ]
}
```

## Summary

**Key Takeaways:**
- ✅ Different tasks need different models
- ✅ Security & Architecture: Use premium (Sonnet 4.5 or Opus)
- ✅ Documentation & Style: Use economy (Haiku 3.5)
- ✅ Performance & Testing: Use balanced (Sonnet 3.7)
- ✅ Standard mode costs ~$0.12 per MR review
- ✅ Parallel execution keeps total time ~30s
- ✅ Dynamic selection based on MR context saves money

**ROI:**
Even at premium tier ($0.50/review), if one critical security bug is caught before production, the system pays for itself 100x over.
