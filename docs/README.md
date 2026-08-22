# docs/

Reference notes for working on fis-calculator, written for a coding agent rather than
a human reader. [`../CLAUDE.md`](../CLAUDE.md) is loaded every session and stays short;
these files are pulled in on demand and go deep.

## Where to look

| file | read it when |
|---|---|
| [architecture.md](architecture.md) | Orienting. System map, data flow, repo layout, the website frontend, DynamoDB schema. |
| [get-points-list.md](get-points-list.md) | Touching the nightly ingest, or FIS/USSA points list downloads. |
| [get-livetiming-info.md](get-livetiming-info.md) | Touching the calculator lambda or any of the three live-timing scrapers. |
| [points-calculation.md](points-calculation.md) | Changing scoring: F-factors, penalty, A/B/C, event maximums, projections. |
| [operations.md](operations.md) | Anything AWS or deploy-related: build/ship recipes for both lambdas, pushing to GitHub (which is also the site deploy), alarms and alerting, the schedule, "is it broken", cost exposure. |
| [testing.md](testing.md) | Running the `get-points-list` suite, or verifying a `get-livetiming-info` change that has no suite behind it. |

## Why these exist

Most of what is written down here was expensive to discover and invisible in the code:
that a missing USSA file returns HTTP 200 with an HTML body, that the points list CSVs
have no header row, that the nightly schedule can be `ENABLED` and still never fire.
Each of those cost real debugging time and each caused wrong results while everything
looked healthy. The point of these files is that the next agent pays that cost once.

Bias the content toward **gotchas, non-obvious behavior of external systems, and
decisions with reasons**. Do not restate what the code plainly says — that goes stale
and adds nothing over reading the source.

## Keeping them current

- **Update the doc in the same change as the code.** A stale doc is worse than none,
  because it is trusted.
- **New knowledge goes where it will be found**, one file only, cross-linked from the
  others. Resist adding files; prefer a section in an existing one.
- **Write down the failure, not just the fix.** "Detect the zip by `PK` magic bytes"
  is half the value; "because missing files return 200 with HTML" is the other half.
- **Verify before you write.** Several beliefs recorded during the first pass over this
  project turned out to be wrong on inspection (the USSA Cloudflare cookie was inert;
  the newest available points list is not the valid one). Check, then write.
- **Record what you ruled out.** Wrong turns avoided are worth as much as the answer.
- When a doc and the code disagree, the code wins — fix the doc immediately.

There is also a private memory store outside the repo holding user preferences, live
operational state, and AWS specifics. Facts that are durable and about *the code* belong
here; facts about *how Matt likes to work* or *what is currently broken* belong there.
