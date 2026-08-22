# fis-calculator

Live ski racing points calculator: **https://www.fiscalculator.com/**

Paste a live-timing URL or a FIS codex mid-race and it scrapes the current standings,
looks up every starter's existing points, and computes the penalty and each racer's
score — before the official results are posted.

## How it works

A static site on GitHub Pages plus three AWS SAM stacks in `us-east-2`:

| | |
|---|---|
| root + [`website/`](website) | Jekyll site. Pages live at the repo root; `website/` holds JS, CSS and images. |
| [`get-points-list/`](get-points-list) | Runs nightly. Downloads the current FIS and USSA points lists and updates a DynamoDB table of every racer. |
| [`get-livetiming-info/`](get-livetiming-info) | The calculator. Snapshots a race from live-timing.com, Vola, or FIS live timing, joins it against the points table, and scores it. |
| [`alerts/`](alerts) | Emails on unhandled errors, plus a daily digest of racers whose points could not be matched. |

Scores follow the FIS rules: race points from the winner's time and the discipline's
F-factor, plus a penalty derived from the best five points among the top ten finishers
and the best five in the field.

## Development

```bash
cd get-points-list
pip install -r requirements-dev.txt
python -m pytest tests/ -q
```

Deeper notes live in [`docs/`](docs/README.md) — architecture, the scoring model, the
quirks of each timing provider, and an operations runbook. They are written for coding
agents working on this repo, but they are the most complete description of how the
thing actually behaves.
