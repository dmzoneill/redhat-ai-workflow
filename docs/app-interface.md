# App-Interface Conventions

Lessons from chat transcripts (see [lessons-learned-from-chat-transcripts](lessons-learned-from-chat-transcripts.md)).

## Terraform-repo `ref` field

For app-interface repo files under `data/*/repos/*.yml` (e.g. terraform-repo):

- **`ref` is a required property** and must be a **full 40-character hex commit SHA**, not a branch name (e.g. `main`) or short SHA.
- Schema pattern: `^[0-9a-f]{40}$`.
- If validation fails with `'ref' is a required property`, add e.g. `ref: 6bc292160c8184571900271a0185d621b5e5eab1` (the intended merge or tip commit from the upstream repo).
- When updating refs after an upstream merge, use the **merge commit SHA** from upstream and squash the app-interface branch to one commit with that ref.

This applies to app-interface PRs that touch repo/terraform-repo YAML; use `appinterface_check` skill to validate.
