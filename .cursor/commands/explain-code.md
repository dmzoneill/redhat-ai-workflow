# Explain Code

Explain a code snippet or file using project knowledge and semantic search.

## Instructions

Get an explanation of code with project context:

```text
skill_run("explain_code", '{"file_path": "$FILE_PATH"}')
```

This will:
1. Read the code from the file
2. Query project architecture knowledge
3. Find similar code patterns via vector search
4. Retrieve relevant gotchas
5. Generate a comprehensive explanation

## Examples

```bash
# Explain a specific file
skill_run("explain_code", '{"file_path": "src/api/routes.py"}')

# Explain a code snippet directly
skill_run("explain_code", '{"code_snippet": "def calculate_billing(): ..."}')

# With specific project context
skill_run("explain_code", '{"file_path": "src/models.py", "project": "automation-analytics-backend"}')
```

## What You Get

- Architecture context from project knowledge
- Relevant coding patterns
- Project-specific gotchas to watch for
- Similar code examples from the codebase
