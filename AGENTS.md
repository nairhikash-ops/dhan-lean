# Project Agent Rules

Before work, read this file, `docs/PROJECT_BLUEPRINT.md`, `docs/AGENT_HANDOFF.md`, Git status, and the existing diff. Preserve user changes and do not overwrite uncommitted work.

The active architecture is offline only:

```text
source adapter -> NormalizedBar -> validation -> planner/ledger/executor -> LEAN converter -> backtest data
```

- Do not add brokerage authentication, credentials, live orders, network acquisition, or server changes without explicit approval.
- Provider adapters own payload parsing. Generic modules accept only provider-neutral contracts.
- Prices use `Decimal`; timestamps must be timezone-aware; adapters must not leak provider-specific identifiers into generic models.
- Do not install packages, modify LEAN, touch server data, or alter Docker/runtime configuration without explicit approval.
- Keep secrets out of source, logs, tests, documentation, and Git history.
- LEAN remains pinned at commit `1fee999e4f437d09e255be5c3fde783206e05389`; do not restore its removed sample data.

Before completion, inspect the final diff, run relevant offline validation, update the handoff and blueprint when safe, and report commands actually run. Do not claim tests passed unless they ran.
