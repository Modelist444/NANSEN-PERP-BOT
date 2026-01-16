<!-- Brief, focused instructions to help AI coding agents be productive in this repo -->
# Copilot instructions for NANSEN PERP BOT

Purpose
- Provide condensed, actionable context so coding agents can make safe, correct edits.

Big picture
- This project is a small Python trading bot. Key modules: `main.py` (runner), `config.py` (settings),
  `exchange.py` (exchange API wrappers), `nansen.py` (Nansen data API), `strategy.py` (trade logic),
  `risk.py` (risk checks), and `logger.py` (logging helpers).
- Data flow: `main.py` orchestrates a loop -> requests market / on-chain data from `nansen.py` ->
  decides in `strategy.py` -> executes via `exchange.py` -> `risk.py` validates -> `logger.py` records.

Files of immediate interest
- `.env` — holds API keys and bot settings. Example keys present: `BINANCE_API_KEY`, `MEXC_API_KEY`, `NANSEN_API_KEY`.
- `main.py` — entrypoint; keep changes minimal to preserve orchestration flow.
- `strategy.py` and `risk.py` — core domain logic. Tests and careful review required for trade rules.

Conventions & patterns (discoverable in repo)
- Single-process synchronous scripts: modify `main.py` if adding async behavior and update all callers.
- Environment-first configuration: prefer reading secrets from `.env` and exposing defaults in `config.py`.
- Separation of concerns: keep exchange-specific code in `exchange.py` and data transformations in `nansen.py`.
- Logging: use `logger.py` for consistent structured logs; avoid printing directly in new code.

Run / debug
- Run the bot locally (Windows / PowerShell):
```powershell
python main.py
```
- For quick checks, `print` statements are present in `main.py` now; prefer adding debug-level logs via `logger.py`.

Safety & risk notes for edits
- Never commit real API keys. Use `.env` for local testing and instruct users to replace placeholders.
- Any change to `strategy.py` or `risk.py` must be conservative: include unit tests and a safe default (no-live-orders) mode.

What to do when adding features
- Add config knobs to `config.py` and mirror env variables in `.env`.
- New exchange integrations: follow `exchange.py` naming and return standardized order/result dicts used by current call sites.

Missing / expected items
- There are placeholder/empty modules (`exchange.py`, `nansen.py`, `strategy.py`, `risk.py`, `logger.py`).
  Assume the intended responsibilities above when implementing; surface questions if behavior is ambiguous.

If you modify this file
- Merge rather than overwrite if a human-maintained `.github/copilot-instructions.md` already exists.

Questions for maintainers
- Should the bot support a dry-run / simulation mode by default for CI? Where do you want tests to live?

-- end --