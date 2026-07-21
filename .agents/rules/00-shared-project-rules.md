# Shared Project Rules

Before planning, editing, or running commands:

1. Read and obey AGENTS.md.
2. Read docs/PROJECT_BLUEPRINT.md.
3. Read docs/AGENT_HANDOFF.md.
4. Inspect Git status and existing uncommitted changes.

Treat AGENTS.md as the canonical project instruction source.

Preserve existing work. Do not reset, revert, delete, overwrite, or discard unrelated changes.

After every meaningful task:

- Run relevant validation.
- Update docs/AGENT_HANDOFF.md.
- Update docs/PROJECT_BLUEPRINT.md when durable architecture or behaviour changes.

Do not duplicate the full contents of AGENTS.md here.

## Final verification

After creating or updating the files:

1. Re-read all relevant files.
2. Confirm that their instructions do not conflict.
3. Confirm that the blueprint reflects the actual repository rather than generic placeholders.
4. Confirm that no secrets were copied.
5. Run git diff --check.
6. Show git status.
7. Review the final diff.
8. Do not commit unless explicitly instructed.

## Final response

Report:

- Files created
- Files updated
- Repository facts discovered
- Commands run
- Validation results
- Existing uncommitted changes preserved
- Unknown or unverified areas
- Whether any application code changed
