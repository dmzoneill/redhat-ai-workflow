# Presentation Materials

> Slides and presentations for AI Workflow

## Available Presentations

| Presentation | Format | Description |
|--------------|--------|-------------|
| AI Personas and Auto Remediation | PPTX | Full technical deep-dive |
| AI Personas and Auto Remediation - TLDR | PPTX | Executive summary version |
| Context Engineering | PPTX + MD | Knowledge and project management |
| Onboarding | PPTX + MD | New user onboarding guide |

## Presentation Outlines

Markdown outlines are provided for easy editing and version control:

- [context-engineering-outline.md](./context-engineering-outline.md) - Context engineering concepts
- [onboarding-outline.md](./onboarding-outline.md) - New user onboarding

## Content Overview

### AI Personas and Auto Remediation

Covers the core architecture:

1. **Persona System** - How AI personas work
2. **Tool Loading** - Dynamic tool module loading
3. **Auto-Remediation** - Self-healing tool failures
4. **Memory System** - Persistent state management
5. **Skill Engine** - YAML workflow execution

### Context Engineering

Explains the knowledge layer:

1. **Context vs Prompt Engineering** - Two dimensions of AI optimization
2. **Context Window** - Understanding token limits
3. **Knowledge Layer** - Project-specific context
4. **Project Management** - Multi-project support
5. **Vector Search** - Semantic code search

### Onboarding

New user getting started:

1. **Installation** - Setup requirements
2. **First Steps** - Basic commands
3. **Daily Workflow** - `/coffee` and `/beer`
4. **Skills** - Automated workflows
5. **Memory** - State persistence

## Creating Presentations

### From Markdown

1. Edit the markdown outline
2. Run the PPTX generator:
   ```bash
   python docs/slides/create_tldr_deck.py
   ```

### Using create_tldr_deck.py

The script converts markdown outlines to PPTX format with:
- Title slides with speaker notes
- Bullet point slides
- Code block slides with syntax highlighting
- Diagram slides (mermaid rendered)

## Speaker Notes

All presentations include speaker notes in:
- PPTX: View in presenter mode
- Markdown: Blockquotes starting with `> **Speaker Notes**:`

## See Also

- [docs/README.md](../README.md) - Documentation index
- [DEVELOPMENT.md](../DEVELOPMENT.md) - Development guide
