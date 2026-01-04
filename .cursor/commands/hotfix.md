# Hotfix

Create an emergency hotfix from production.

## Instructions

```
skill_run("hotfix", '{"commit": "$COMMIT_SHA", "version": "$VERSION"}')
```

## What It Does

1. Fetches latest from origin
2. Creates hotfix branch from production tag
3. Cherry-picks the fix commit
4. Tags the hotfix version
5. Pushes branch and tag

## Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `commit` | Commit SHA to cherry-pick | Required |
| `version` | Hotfix version tag | Required |
| `base_tag` | Production tag to branch from | Latest release |

## Examples

```bash
# Create hotfix
skill_run("hotfix", '{"commit": "abc1234", "version": "v1.2.3-hotfix1"}')

# From specific base
skill_run("hotfix", '{"commit": "abc1234", "version": "v1.2.3-hotfix1", "base_tag": "v1.2.3"}')
```

## Next Steps

After hotfix is created:
1. Create MR from hotfix branch
2. Get emergency review
3. Merge and deploy
4. Consider backporting to main







