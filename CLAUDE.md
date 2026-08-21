# fis-calculator

Ski racing points calculator behind https://www.fiscalculator.com/. A Jekyll site on
GitHub Pages plus three AWS SAM stacks in **us-east-2**.

| part | what it does |
|---|---|
| root + `website/` | Jekyll site. Pages live at the **repo root**; `website/` is assets only. Push to `main` publishes. |
| `get-points-list/` | Nightly ingest of FIS + USSA points lists into DynamoDB. python3.14. |
| `get-livetiming-info/` | The calculator. Snapshots a live race and scores it. python3.14. |
| `alerts/` | Error emails + daily name-match digest. The one stack fully described by its template. |

Detail lives in [`docs/`](docs/README.md) — pull in the file you need rather than
guessing. Start at [docs/architecture.md](docs/architecture.md).

## Rules that prevent damage

1. **A green run means nothing.** Both ingest paths swallow exceptions and return
   normally, so the Lambda `Errors` metric is always 0. Judge health by *did it run*
   plus *do the logs contain `ERROR`*. See [docs/operations.md](docs/operations.md).
2. **The SAM templates do not describe what is deployed.** The schedule, DynamoDB
   tables, IAM permissions, Function URL, and pandas layer all live outside IaC.
   `sam deploy` is not a safe no-op — prefer `update-function-code`.
3. **Don't deploy or push without being asked.** Batch changes, deploy once. Pushing
   `main` also republishes the live site.
4. **This is a public repo and a live site with real users.** Prefer surgical changes.
5. **Matt owns the ski-racing domain.** FIS rules, penalty formulas, and event
   constants change every few seasons — ask him rather than inferring from the code.

## Working here

- Tests: `cd get-points-list && python -m pytest tests/ -q` (22, no network).
  `get-livetiming-info` has none — see [docs/testing.md](docs/testing.md).
- Never read `_site/`, `get-livetiming-info/_site/` (a stale copy of `src/` that will
  mislead you), `.aws-sam/`, `pandas-layer/`, `template-copy.yaml`, `template.backup.yaml`.
- Scraped upstreams break in specific, catalogued ways. Check the relevant doc before
  debugging from scratch.
- `get-livetiming-info/src/app.py` usually has an edited debug block in the working
  tree. That is not a real change; leave it.
