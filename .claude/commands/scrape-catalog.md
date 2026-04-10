---
description: "Scrape PinTradingDB catalog or check scrape progress"
argument-hint: "[status | start | start --end-page 100]"
allowed-tools: ["Bash", "Read"]
---

# PinTradingDB Scraper

Manage the PinTradingDB catalog scraper from within Claude Code.

## Commands

Based on the argument provided, run the appropriate action:

### `status` (or no argument)
Check current scrape progress:
```bash
cd disney-pin-assistant && python3 scripts/scrape_pintradingdb.py status
```
Report the results clearly: how many pins scraped, how many remaining, estimated time left.

### `start`
Start or resume the scraper in the background. The user should run this in a separate terminal:

Tell the user to open a new terminal and run:
```
cd ~/Documents/GitHub/Disney-pins/disney-pin-assistant
python3 scripts/scrape_pintradingdb.py scrape 2>&1 | tee scrape.log
```

Explain the behavior:
- First run: discovers all ~57K pin IDs (~30 min), caches them, then scrapes newest first
- Subsequent runs: loads cached IDs, checks for new pins (seconds), skips already-scraped, continues where it left off
- Ctrl-C safe: checkpoints every 100 pins, just re-run to continue
- Pass any extra args from the user's input (e.g., `--end-page 100` for a partial run)

### `tail`
Show recent scrape progress from the log:
```bash
tail -20 disney-pin-assistant/scrape.log 2>/dev/null || echo "No scrape.log found. Is the scraper running?"
```
