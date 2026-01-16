# Find Similar Code

Find code similar to a snippet or description using semantic vector search.

## Instructions

Find similar code patterns:

```text
skill_run("find_similar_code", '{"query": "$QUERY"}')
```

This will:
1. Search the vector index for semantically similar code
2. Return matching code snippets with file locations
3. Show similarity scores
4. Highlight relevant patterns

## Examples

```bash
# Find by description
skill_run("find_similar_code", '{"query": "billing calculation logic"}')

# Find similar to a code pattern
skill_run("find_similar_code", '{"query": "async def fetch_data_from_api"}')

# Find error handling patterns
skill_run("find_similar_code", '{"query": "retry logic with exponential backoff"}')

# Find test patterns
skill_run("find_similar_code", '{"query": "pytest fixture for database setup"}')
```

## Use Cases

- **Before implementing**: Find existing patterns to follow
- **Code review**: Check for duplication
- **Learning**: Discover how patterns are used in the codebase
- **Refactoring**: Find all similar implementations to consolidate
