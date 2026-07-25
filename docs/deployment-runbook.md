# Offline LEAN Deployment Notes

The project is limited to offline ingestion, normalized bars, LEAN-format conversion, and local backtesting. No provider runtime, API credential, or live execution component is deployed by this repository.

Keep credentials outside Git and container images. Any future source adapter must normalize data before it reaches generic pipeline modules. Zerodha authentication is maintained separately and is not wired into this project.

The LEAN checkout and Docker image naming are intentionally unchanged in this cleanup.
