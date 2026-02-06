# Video Series: Building an AI Workflow System

> 8 short videos (3-5 min each) - conversational style, not scripted

## The Core Philosophy

**Deterministic outcomes through progressive automation.**

The goal isn't just "AI assistance" - it's systematically eliminating variability and **firewalling yourself from poor LLM decisions**.

### The Defense Model

LLMs are probabilistic - same prompt can yield different outputs. Without guardrails, LLM decisions can cascade into real damage.

| Defense Line | Component | What It Does |
|--------------|-----------|--------------|
| **1st Line** | Tools | Constrained, atomic operations with defined inputs/outputs |
| **2nd Line** | Skills | Validated workflows with deterministic execution |

- **LLM decides WHAT** to do (intent recognition)
- **Code decides HOW** to do it (execution)
- The HOW is locked down - LLM can't improvise it

### The Extraction Rule

> **Anything repeatable with a deterministic outcome should be extracted and abstracted as a skill.**

Don't let the LLM improvise what can be codified.

### The Automation Layers

| Layer | What Gets Automated | Outcome |
|-------|---------------------|---------|
| **Tools** | Individual operations (git, jira, k8s) | Consistent execution, no typos |
| **Skills** | Multi-step workflows | Same process every time |
| **Auto-Remediation** | Error recovery | Self-healing, no manual intervention |
| **Learning** | Pattern recognition | System gets smarter over time |
| **Prevention** | Usage patterns | Stop mistakes before they happen |

### The Progression

1. First time: You do it manually, system watches
2. Second time: System suggests the pattern
3. Third time: System does it, you confirm
4. Fourth time: System does it automatically

**Everything that CAN be automated SHOULD be abstracted** - goals, workflows, error handling, even the learning itself.

---

## Series Overview

| # | Episode | ~Duration | Core Message |
|---|---------|-----------|--------------|
| 1 | The Problem & Vision | 3-4 min | Deterministic outcomes, progressive automation |
| 2 | MCP Server Architecture | 4-5 min | Single server, dynamic tools, personas |
| 3 | Multi-Workspace Sessions | 4-5 min | Multiple chats, one server, separate context |
| 4 | Skills: Workflow Automation | 4-5 min | Abstract workflows into repeatable YAML |
| 5 | Auto-Heal: Self-Repairing Tools | 4-5 min | 5 layers - from retry to prevention |
| 6 | Memory & Learning | 3-4 min | System learns, improves, remembers |
| 7 | Local Intelligence: NPU & Inference | 4-5 min | Classification, context, local models |
| 8 | Background Daemons | 4-5 min | Automation that runs without you |
| 9 | IDE Integration | 3-4 min | Visibility into the automated system |

**Style:** Natural conversation, walking through the system. Not reading a script.

---

## Episode 1: The Problem & Vision

### Key Points

**The Problem** (show, don't just tell)
- Developer morning: Slack → Jira → GitLab → Prometheus → K8s logs
- Every time is slightly different - human variability
- AI assistants forget everything - no continuity
- Generic tools don't know YOUR context

**The Real Problem: Non-Deterministic Outcomes**
- Same task, different results each time
- Depends on who does it, when, what they remember
- Errors compound - one wrong step cascades
- Knowledge lives in heads, not systems

**LLMs Are Probabilistic - That's the Risk**
- LLMs generate plausible responses, not guaranteed correct ones
- Same prompt can yield different outputs
- "Hallucinations" - confident but wrong
- Without guardrails, LLM decisions can cascade into real damage

**The Vision: Firewall Yourself from Poor LLM Decisions**

Two lines of defense:

| Layer | Defense | What It Does |
|-------|---------|--------------|
| **1st Line** | Tools | Constrained operations with defined inputs/outputs |
| **2nd Line** | Skills | Validated workflows with deterministic execution |

- **Tools** = atomic operations the LLM can call, but can't modify
- **Skills** = pre-validated pathways the LLM triggers, but doesn't interpret
- LLM decides WHAT to do, not HOW to do it
- The HOW is locked down in code

**Clarification: Our Skills ≠ Claude Skills**

| | Claude Skills | Our Skills Engine |
|--|---------------|-------------------|
| **What** | Prompt templates | YAML workflow definitions |
| **Execution** | LLM interprets each time | Server executes deterministically |
| **Variability** | Same skill → different results | Same skill → same results |
| **Analogy** | Suggestions | Ansible playbooks |

In configuration management, we have Ansible, Puppet, Chef - declarative automation.
In the AI world, we need the same: **a custom skills engine that marries AI with automation**.

- Claude picks the skill (intent recognition)
- Our engine executes it (deterministic automation)
- Best of both worlds: AI flexibility + automation reliability

**The Rule: Extract and Abstract**
> Anything repeatable with a deterministic outcome should be extracted and abstracted as a skill.

Don't let the LLM improvise what can be codified.

**The Progression**
1. Manual → System watches
2. Assisted → System suggests
3. Supervised → System does, you confirm
4. Autonomous → System handles it

**Goals become skills. Skills become reliable. Reliability enables trust. Trust enables autonomy.**

### Demo

Run the "coffee" skill - show it gathering:
- Today's calendar
- Slack mentions
- Jira issues in progress
- MRs waiting for review
- Any alerts firing

**Same briefing, every morning, deterministic.**

### Show Code (briefly)

Open `skills/coffee.yaml` - the workflow is abstracted into YAML. Anyone can read it, modify it, trust it.

### Transition

"So how do we build a system that can do this? Let's look at the architecture."

---

## Episode 2: MCP Server Architecture

### Key Points

**What is MCP?**
- Model Context Protocol - Anthropic's standard
- How Claude talks to external tools
- JSON-RPC over stdio

**Our Architecture**
- Single server process
- ~700 tools across ~50 modules
- Dynamic loading based on persona

**Personas = Tool Profiles**
- developer: git, gitlab, jira, lint (~78 tools)
- devops: k8s, bonfire, quay (~74 tools)
- incident: prometheus, kibana, alertmanager (~78 tools)
- release: konflux, quay, appinterface (~91 tools)

**Key insight:** You're not spawning different AIs - you're changing which tools Claude has access to.

### Demo

1. Show current tool count
2. `persona_load("devops")`
3. Watch Cursor refresh with new tools (k8s, bonfire appear)

### Show Code (briefly)

`server/persona_loader.py` - the switch_persona function:
- Calculate delta (what to load/unload)
- Preserve core tools
- Notify Cursor of change

### Transition

"But what happens when you have multiple chat windows open? They all share this one server..."

---

## Episode 3: Multi-Workspace Sessions

### Key Points

**The Problem**
- Cursor spawns ONE MCP server
- Multiple chat windows share it
- Each chat needs its own context

**The Solution: WorkspaceRegistry**
- Workspace = directory/project
- Session = individual chat within workspace
- Each session has: ID, name, persona, active issue

**Session Lifecycle**
- Chat starts → `session_start()` → get session ID
- Claude tracks that ID for the conversation
- Context (project, persona, issue) tied to session ID

### Demo

1. Two chat windows side by side
2. Start session in each with different names
3. `session_list()` - show both sessions
4. Each has different persona/context

### Show Code (briefly)

`server/workspace_state.py`:
- ChatSession dataclass
- WorkspaceState holds multiple sessions
- WorkspaceRegistry manages multiple workspaces

### Transition

"Now each chat has context. But running 10 tools manually for every deploy is tedious. That's where skills come in."

---

## Episode 4: Skills - Workflow Automation

### Key Points

**Our Skills ≠ Claude Skills**

| | Claude Skills | Our Skills Engine |
|--|---------------|-------------------|
| **What** | Prompt templates | YAML workflow definitions |
| **Execution** | LLM interprets each time | Server executes deterministically |
| **Result** | Same skill → variable results | Same skill → same results |
| **Analogy** | Suggestions | Ansible playbooks |

**The Config Management Parallel**

| Domain | Tool | What It Does |
|--------|------|--------------|
| Servers | Ansible | Declarative automation |
| Containers | Kubernetes | Declarative orchestration |
| **AI Workflows** | **Our Engine** | **Declarative AI automation** |

Same principle: declare WHAT you want, engine handles HOW.

**Goals Should Be Abstracted Into Skills**

A goal like "deploy my MR to test" involves:
- 7+ steps
- Multiple tools
- Error handling
- Variable passing

**Without abstraction:**
- Different person = different steps
- Different order = different outcome
- Forgotten step = failure

**Skills as Neural Pathways (The Brain Analogy)**

```
Intent (thought)
    ↓
Skill (neural pathway)
    ↓
Tools (synapses)
    ↓
Outcome (action)
```

Like a tree: branches (skills) lead to leaves (tools).

**Two Lines of Defense Against LLM Variability**

| Line | Component | Protection |
|------|-----------|------------|
| **1st** | Tools | Atomic, constrained operations |
| **2nd** | Skills | Validated, deterministic workflows |

- **Tools** = synapses with defined behavior
- **Skills** = hardened pathways the LLM triggers but doesn't interpret
- LLM picks the path, but can't change what's on it

**Why This Matters:**
- **Claude's focus**: Understand intent, select skill, interpret result
- **Skill engine handles**: Business logic, error handling, tool orchestration
- Don't waste context window on internals
- **Don't let LLM improvise** what can be codified

**The Extraction Rule**
> Anything repeatable with a deterministic outcome → extract as a skill.

**Learned Pathways**
- First time: Manual, slow, error-prone
- Encoded as skill: Pathway formed
- Repeated use: Pathway strengthens
- Eventually: Automatic, reliable

The system develops "muscle memory" - and that memory is deterministic.

**What Makes a Good Skill**
- **Declarative**: Say WHAT, not HOW
- **Idempotent**: Safe to run twice
- **Observable**: Can see what it's doing
- **Recoverable**: Handles errors gracefully

**87 Skills = 87 Learned Pathways**

| Category | Examples | What They Abstract |
|----------|----------|-------------------|
| Development | start_work, create_mr | Issue → Code → Review |
| DevOps | test_mr_ephemeral | Code → Running in K8s |
| Incident | investigate_alert | Alert → Root cause |
| Release | release_to_prod | Code → Production |

### Demo

Show the manual process for deploying an MR:
1. Get MR from GitLab
2. Find commit SHA
3. Check image in Quay
4. Reserve namespace
5. Deploy
6. Wait for pods
7. Get route URL

Then: `skill_run("test_mr_ephemeral", '{"mr_id": 1459}')`

Watch the pathway fire: intent → tools → outcome.

### Show Code (briefly)

Open `skills/test_mr_ephemeral.yaml`:
- inputs: the goal parameters
- steps: the abstracted workflow
- Variable passing: `{{ steps.get_mr.sha }}`
- Error handling: `on_error:`

### Transition

"Skills give deterministic outcomes for the happy path. But what about when things go wrong?"

---

## Episode 5: Auto-Heal - Self-Repairing Tools

### Key Points

**The Goal: Errors Should Fix Themselves**
- Human intervention = variability
- Every manual fix is a chance for new errors
- System should learn from every failure

**5 Layers - From Reactive to Preventive**

| Layer | What it does | Learning |
|-------|--------------|----------|
| 1. Tool Decorators | Retry with VPN/auth fix | None - just retry |
| 2. Skill Patterns | YAML error handlers | Encoded knowledge |
| 3. Auto-Debug | Read source, propose fix | Fixes the tool itself |
| 4. Memory Learning | Store fixes for reuse | "We've seen this before" |
| 5. Usage Patterns | Warn before mistakes | **Prevention > Cure** |

**The Progression Matters**
- Layer 1: React to failure
- Layer 2: Handle known failures
- Layer 3: Fix unknown failures
- Layer 4: Remember the fix
- Layer 5: **Prevent the failure entirely**

**Layer 5 is the goal state**
- System learns your patterns
- "You usually use full SHA, not short SHA"
- Warns you BEFORE you make the mistake
- Deterministic prevention of known failure modes

**Performance Improvement**
- First failure: Takes 30 seconds to auto-heal
- Second failure: Instant - known fix applied
- Third time: No failure - prevented

### Demo

1. Disconnect VPN manually
2. Run a K8s tool
3. Watch: fail → detect → fix → retry → succeed
4. Show the pattern being learned

### Show Code (briefly)

`server/auto_heal_decorator.py` - the retry logic
`memory/learned/tool_fixes.yaml` - the knowledge base

### Transition

"Auto-heal learns from failures. But the system learns more than just fixes..."

---

## Episode 6: Memory & Learning

### Key Points

**Memory Enables Learning. Learning Enables Improvement.**

Without memory:
- Every session starts from zero
- Same mistakes repeated
- No improvement over time

With memory:
- Context persists
- Patterns accumulate
- System gets smarter

**Four Types of Memory**

| Type | Purpose | How It Improves Performance |
|------|---------|----------------------------|
| **State** | Current work | No re-explaining context |
| **Learned** | Error patterns, fixes | Faster recovery, prevention |
| **Knowledge** | Project expertise | Better suggestions, fewer mistakes |
| **Sessions** | Activity logs | Audit trail, pattern mining |

**The Learning Loop**
1. Action happens
2. Outcome recorded
3. Pattern extracted
4. Knowledge updated
5. Future actions improved

**Concrete Examples**
- "Last time you deployed billing, you needed to run migrations first"
- "This error usually means the image hasn't built yet"
- "You typically work on AAP issues in the morning"

**Performance Improvement Over Time**
- Week 1: System asks lots of questions
- Week 4: System suggests based on patterns
- Week 12: System handles most things autonomously

### Demo

1. Close Cursor, reopen
2. "What was I working on?" - instant context
3. `memory_ask("What errors have I seen with bonfire?")` - learned patterns
4. Show `memory/learned/patterns.yaml` - accumulated knowledge

### Show Code (briefly)

```
memory/
├── state/current_work.yaml    # What you're doing
├── learned/patterns.yaml      # What system learned
├── learned/tool_fixes.yaml    # Known fixes
└── knowledge/personas/        # Project expertise
```

### Transition

"Memory lets the system learn. But how does the system understand what you're asking and build the right context?"

---

## Episode 7: Local Intelligence - NPU, Classification & Context

### Key Points

**The Problem: Every API Call Costs Tokens**
- Sending full context to Claude = expensive
- ~700 tools × descriptions = massive prompt
- Repeated queries = repeated costs
- Latency for simple classifications

**The Solution: Local Intelligence**
- Run small models locally on NPU/GPU
- Classify intent BEFORE hitting the API
- Filter tools to only relevant ones
- Build context intelligently

**Three Layers of Local Intelligence**

| Layer | What It Does | Where It Runs |
|-------|--------------|---------------|
| **Intent Classification** | Understand what user wants | NPU (qwen2.5:0.5b) |
| **Tool Filtering** | Select relevant tools only | NPU + keywords |
| **Context Enrichment** | Gather relevant context | Local + vector search |

**Intent Classification**
- "What am I working on?" → `status_check`
- "How does billing work?" → `code_lookup`
- "Why did deploy fail?" → `troubleshooting`
- Routes query to right memory adapters
- Runs on NPU in ~100ms

**Tool Filtering (~93% Token Reduction)**
- ~700 tools → filter to ~50 relevant ones
- 4-layer architecture:
  1. Keyword matching (fast)
  2. NPU semantic classification
  3. Persona-based filtering
  4. Fallback to all tools

**Context Engineering**
- Don't dump everything into prompt
- Gather context based on intent
- Layer it: System → Persona → Session → Query
- Token budget management

**The Inference Stack**

| Backend | Model | Power | Use Case |
|---------|-------|-------|----------|
| NPU | qwen2.5:0.5b | 2-5W | Classification, filtering |
| iGPU | llama3.2:3b | 8-15W | Summaries, simple tasks |
| NVIDIA | llama3:7b | 40-60W | Complex reasoning |
| CPU | qwen2.5:0.5b | 15-35W | Fallback |

**Automatic Fallback Chain**
- Try NPU first (fastest, lowest power)
- Fall back through chain if unavailable
- Graceful degradation

### Demo

1. Show intent classification:
   ```
   "What errors have I seen with bonfire?"
   → Intent: troubleshooting (confidence: 0.92)
   → Routes to: learned patterns, tool failures
   ```

2. Show tool filtering:
   ```
   Before: ~700 tools in prompt
   After: ~50 relevant tools
   Token reduction: ~93%
   ```

3. Show context assembly:
   ```
   Query: "Deploy MR 1459"
   Context gathered:
   - MR details from GitLab
   - Image status from Quay
   - Available namespaces
   - Recent deployment history
   ```

### Show Code (briefly)

`services/memory_abstraction/classifier.py`:
```python
class IntentClassifier:
    async def classify(self, query: str) -> IntentClassification:
        # Try NPU first
        if self.npu_available:
            return await self._npu_classify(query)
        # Fall back to keywords
        return self._keyword_classify(query)
```

`tool_modules/aa_ollama/src/tool_filter.py`:
```python
class HybridToolFilter:
    # 4-layer filtering
    async def filter_tools(self, query: str, all_tools: list) -> list:
        # Layer 1: Keyword match
        # Layer 2: NPU semantic
        # Layer 3: Persona filter
        # Layer 4: Fallback
```

### Transition

"Local intelligence makes the system smarter and cheaper. But some things need to run continuously in the background."

---

## Episode 8: Background Daemons

### Key Points

**Automation That Runs Without You**

The ultimate goal: system operates autonomously
- You're in a meeting → Slack questions still get answered
- You're asleep → Scheduled tasks still run
- You're on vacation → System maintains itself

**6 Daemons = 6 Autonomous Capabilities**

| Daemon | Autonomous Behavior |
|--------|---------------------|
| **Slack** | Answer questions with full context |
| **Sprint** | Process issues, update status |
| **Meet** | Join meetings, take notes |
| **Cron** | Run scheduled skills |
| **Session** | Sync IDE state |
| **Video** | Render status to camera |

**The Progression to Autonomy**
1. Manual: You answer Slack messages
2. Assisted: System drafts response, you send
3. Supervised: System sends, you review
4. Autonomous: System handles it, logs for audit

**Slack Daemon Example**
- Someone asks "@daoneill is AAP-12345 ready?"
- Daemon loads context: issue status, MR, deployment
- Generates accurate response
- Posts in thread
- You never had to context-switch

**Cron Daemon Example**
- Every morning at 8am: run "coffee" skill
- Every Friday: run "weekly_summary" skill
- Deterministic, scheduled, autonomous

### Demo

1. `systemctl --user status bot-slack`
2. Show D-Bus interface
3. Show a Slack message being handled autonomously
4. Show cron schedule: `skill_run("cron_list")`

### Show Code (briefly)

`services/slack/daemon.py`:
- Autonomous message handling
- Context loading
- Response generation

### Transition

"Daemons provide autonomy. But you still need visibility into what's happening."

---

## Episode 9: IDE Integration

### Key Points

**Visibility Into the Autonomous System**

As automation increases, visibility becomes critical:
- What is the system doing?
- What has it learned?
- What's happening in the background?

**Trust Requires Transparency**
- Can't trust what you can't see
- Automation without visibility = anxiety
- IDE integration = window into the system

**VSCode Extension Features**

| Feature | What It Shows |
|---------|---------------|
| Status Bar | Current state at a glance |
| Skill Toast | Live execution progress |
| Memory Viewer | What system knows |
| Workflow Explorer | Available automations |

**Real-Time Updates**
- D-Bus signals from daemons
- WebSocket from MCP server
- File watchers for state changes

**The Feedback Loop**
- See what system is doing
- Understand why it made decisions
- Correct when needed
- System learns from corrections

### Demo

1. Status bar - 7 indicators showing system state
2. Run a skill - watch the toast show each step
3. Memory viewer - see accumulated knowledge
4. Workflow explorer - browse available skills

### Wrap-up: The Complete Picture

**The Philosophy:** Deterministic outcomes through progressive automation

| Component | Role in Determinism |
|-----------|---------------------|
| **Tools** | Consistent operations |
| **Personas** | Right tools for the job |
| **Sessions** | Isolated, tracked context |
| **Skills** | Abstracted, repeatable goals |
| **Auto-Heal** | Self-correcting errors |
| **Memory** | Learning and improvement |
| **Local Intelligence** | Smart routing, token efficiency |
| **Daemons** | Autonomous operation |
| **IDE** | Visibility and trust |

**The Progression:**
- Manual → Assisted → Supervised → Autonomous

**The Goal:**
- Everything that CAN be automated, IS automated
- System learns and improves continuously
- Local intelligence reduces cost and latency
- Deterministic outcomes, every time

"This is what AI-assisted development should look like - not just a chatbot, but a system that genuinely takes work off your plate and gets better at it over time."

---

## Recording Setup: Gnome Cube Workspaces

### 4-Desktop Layout

```
┌─────────────────────────────────────────────────────────────────┐
│                        GNOME CUBE                               │
│                                                                 │
│   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐            │
│   │  Desktop 1  │  │  Desktop 2  │  │  Desktop 3  │            │
│   │             │  │             │  │             │            │
│   │   SLIDES    │  │   CURSOR    │  │  DIAGRAMS   │            │
│   │             │  │   (Demo)    │  │             │            │
│   │ Key Points  │  │  Terminal   │  │ Architecture│            │
│   │ Sub-bullets │  │    IDE      │  │   Mermaid   │            │
│   │             │  │             │  │             │            │
│   └─────────────┘  └─────────────┘  └─────────────┘            │
│                                                                 │
│   ┌─────────────┐                                              │
│   │  Desktop 4  │  ← Behind the cube                           │
│   │             │                                              │
│   │  CONTROL    │                                              │
│   │  OBS/Video  │                                              │
│   │  Notes      │                                              │
│   └─────────────┘                                              │
└─────────────────────────────────────────────────────────────────┘
```

### Desktop Assignments

| Desktop | Content | App |
|---------|---------|-----|
| **1 - Left** | Slides with key points | Impress/Reveal.js/Markdown viewer |
| **2 - Center** | Live demo | Cursor + Terminal |
| **3 - Right** | Architecture diagrams | Browser/Image viewer |
| **4 - Back** | Production control | OBS, notes, video manager |

### Recording Flow

**For each episode:**
1. Start on **Desktop 1** (Slides) - introduce the topic
2. Cube rotate to **Desktop 2** (Cursor) - show the demo
3. Cube rotate to **Desktop 3** (Diagrams) - explain architecture
4. Rotate back as needed - natural flow between content

**Cube transitions:**
- `Ctrl+Alt+Left/Right` or mouse drag
- Smooth visual transition between contexts
- Keeps viewer oriented

### Desktop 1: Slides Format

Slides are pre-created in `docs/plans/video-slides/`:

```
video-slides/
├── README.md                 # Viewing options
├── episode-01-slides.md      # The Problem & Vision
├── episode-02-slides.md      # MCP Server Architecture
├── episode-03-slides.md      # Multi-Workspace Sessions
├── episode-04-slides.md      # Skills
├── episode-05-slides.md      # Auto-Heal
├── episode-06-slides.md      # Memory & Learning
├── episode-07-slides.md      # Local Intelligence
├── episode-08-slides.md      # Background Daemons
└── episode-09-slides.md      # IDE Integration
```

**Viewing options:**
- **Marp** (recommended) - `marp --preview episode-01-slides.md`
- **VS Code Marp extension** - preview in editor
- **mdp** - terminal presentation mode
- **Any text editor** - large font, simple

### Desktop 2: Demo Setup

- Cursor IDE (dark theme, large font)
- Terminal visible (clean, no clutter)
- Pre-staged state (issues, MRs ready)
- Test all commands before recording

### Desktop 3: Diagrams

- Browser with mermaid.live or exported PNGs
- One diagram per concept
- Large, readable
- Can zoom/pan as needed

### Desktop 4: Control Room

- OBS Studio (recording)
- Episode notes/checklist
- Timer
- Video file manager

### Recording Tips

**Cube rotation:**
- Practice the rotations before recording
- Smooth, deliberate movements
- Pause briefly after rotation (let viewer orient)

**Audio:**
- Keep talking during rotations: "Let me show you the architecture..."
- Natural transitions, not jarring

**Pacing:**
- Slides: Quick reference, don't linger
- Demo: Take your time, explain as you go
- Diagrams: Point out key relationships

### Per-Episode Prep Checklist

- [ ] Slide created (Desktop 1)
- [ ] Demo tested and staged (Desktop 2)
- [ ] Diagrams ready (Desktop 3)
- [ ] OBS scene configured (Desktop 4)
- [ ] Cube rotation practiced
- [ ] Audio check

---

## Diagrams & Images

### Extracted from Existing Presentation

98 images extracted from `slides.pptx` to `docs/plans/video-slides/images/`.
Review and map to episodes.

### Diagrams Needed

| Episode | Diagram | Source |
|---------|---------|--------|
| 1 | Before/after workflow comparison | Create or use existing |
| 2 | MCP server architecture (personas, tools) | slides.pptx has this |
| 3 | WorkspaceRegistry → Workspaces → Sessions | docs/architecture/diagrams/ |
| 4 | Skills as Neural Pathways (Intent → Skill → Tools) | Create - brain/tree analogy |
| 5 | 5-layer auto-heal stack | slides.pptx has this |
| 6 | Memory directory structure + learning loop | docs/architecture/diagrams/ |
| 7 | Local inference stack (NPU → iGPU → NVIDIA → CPU) | Create or docs/ |
| 8 | Daemon architecture (systemd → D-Bus → VSCode) | docs/architecture/diagrams/ |
| 9 | Extension architecture | docs/architecture/diagrams/ |

### Key Concepts from Existing Presentation

**Slide 42 - Skills as Synapses:**
```
Intent → Skill → Tools
Like a tree: branches lead to leaves
```

**Slide 40 - Context Rot Problem:**
- LLM exploration pollutes context
- Skills provide clean, deterministic paths

**Slide 41 - Interpretation vs Execution:**
- Claude Skills: interpreted each time (variable)
- Our Skills: executed by server (deterministic)

**Slide 27 - Stateless Agents Create Chaos:**
- Persistent memory essential for continuity
- One agent with memory > many without

Most diagrams exist in `docs/architecture/diagrams/` - export as PNG for Desktop 3.
