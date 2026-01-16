# Learn Architecture

Perform a deep scan of project architecture.

## Instructions

```text
skill_run("learn_architecture", '{"project": "$PROJECT"}')
```

## What It Does

Performs a detailed analysis of project architecture:
1. Scans directory structure
2. Identifies key components
3. Maps dependencies
4. Documents API patterns
5. Records database schema patterns
6. Updates architecture knowledge

## Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `project` | ⚪ | auto-detected | Project name |
| `persona` | ⚪ | developer | Target persona |
| `include_deps` | ⚪ | true | Analyze dependencies |

## Examples

```bash
# Scan current project
skill_run("learn_architecture", '{}')

# Scan specific project
skill_run("learn_architecture", '{"project": "automation-analytics-backend"}')

# Scan for devops persona
skill_run("learn_architecture", '{"project": "my-project", "persona": "devops"}')
```

## What Gets Analyzed

### Code Structure
- Directory layout
- Module organization
- Entry points
- Configuration files

### Dependencies
- Direct dependencies
- Dev dependencies
- Version constraints
- Security advisories

### API Patterns
- Framework (FastAPI, Flask, Express)
- Route organization
- Authentication patterns
- Error handling

### Database
- ORM/ODM used
- Migration patterns
- Schema organization
- Query patterns

### Testing
- Test framework
- Test organization
- Fixtures and factories
- Coverage configuration

## Output

Updates `memory/knowledge/personas/{persona}/{project}.yaml` with:

```yaml
architecture:
  framework: FastAPI
  database: PostgreSQL
  orm: SQLAlchemy
  cache: Redis

patterns:
  api: RESTful with OpenAPI
  auth: JWT with refresh tokens
  errors: Custom exception handlers

components:
  - name: api
    path: src/api/
    description: REST API endpoints
  - name: models
    path: src/models/
    description: SQLAlchemy models
```

## See Also

- `/bootstrap-knowledge` - Full knowledge generation
- `/knowledge-scan` - Quick scan
- `/knowledge-update` - Manual updates
