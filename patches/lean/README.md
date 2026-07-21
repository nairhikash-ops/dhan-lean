# LEAN Engine Patches

This directory contains repository-level patches to be applied to the vendored QuantConnect LEAN engine source tree (`Lean/`) during the bootstrap process.

## Patches

### `Market.cs`

- **Target File in LEAN:** `Lean/Common/Market.cs`
- **Purpose:** Adds custom market identifiers for Indian exchanges, specifically defining `Market.India = "india"` with identifier code `11`.
- **Application Method:** Automatically copied to `Lean/Common/Market.cs` by `scripts/bootstrap-lean.ps1`.
