# get-points-list

Nightly Lambda. Ingests the FIS and USSA alpine points lists into DynamoDB so that
[get-livetiming-info](get-livetiming-info.md) can look up each racer's current points when
scoring a race. See [architecture.md](architecture.md) for how the two fit together.

## Read this first

Five things that cost real time to discover:

1. **A "successful" run means nothing.** Every code path is wrapped in a bare `except Exception`
   that only logs, so the Lambda reports success even when both feeds are dead. Judge health by
   `ERROR` lines in the logs and by *whether it ran at all* — never by the `AWS/Lambda Errors`
   metric. See [operations.md](operations.md).
2. **Newest USSA list on the server is the wrong list.** Lists are uploaded ~2 days before they
   become legal for competition. Selection is driven by a schedule PDF, not by file mtime.
3. **The USSA CSVs have no header row.** `pd.read_csv(..., header=None)` is mandatory
   (`src/ussa_points_download.py:241-242`). Without it pandas eats the first athlete of each file
   as column names — a silent, successful, wrong run.
4. **A missing USSA file returns HTTP 200 with an HTML error page**, not a 404. Status-code checks
   are useless here; check content type or the `PK` magic bytes.
5. **USSA needs no auth at all.** No cookie, no User-Agent, no referer. A previous hardcoded
   `cf_clearance` cookie was inert and has been deleted. Do not go re-harvesting cookies.
   FIS *does* require a browser User-Agent or it 403s.

## Shape

| | |
|---|---|
| Stack | `get-points-list` (SAM), us-east-2, account `828841719603` |
| Function | `get-points-list-GetPointsListFunction-D0YVo1592Mhc` |
| Handler | `app.lambda_handler` (`src/app.py:7`) |
| Runtime | **python3.14** |
| Memory / timeout | 3008 MB / 900 s — actual use is ~271 MB, ~55-120 s |
| Layers | **none**; dependencies are bundled in the zip (deployed `CodeSize` 48,698,158 ≈ 46 MB) |
| Concurrency | `ReservedConcurrentExecutions: 1` |
| Trigger | EventBridge **Scheduler** `get-fis-points-nightly-run`, `cron(10 1 * * ? *)` America/New_York — **the only one** |

`lambda_handler` does exactly two things (`src/app.py:12-13`): `fis_points_download(logger)` then
`ussa_points_download(logger)`. There is no return value and no event parsing — the payload is
ignored, so any invoke shape works.

**This function has exactly one caller and no resource policy.** `template.yaml` used to declare an
unauthenticated API Gateway `GET /get-points-list` event — a free public trigger for a 3 GB / 900 s
function that scans and rewrites DynamoDB. Nothing ever called it (zero requests in 30 days), and it
was removed 2026-08-21 along with the hand-added `apigateway.amazonaws.com` invoke permission that
outlived it. The scheduler invokes through its own IAM role, so `get-policy` now returns
`ResourceNotFoundException` — that is correct, not a misconfiguration.

The concurrency cap follows from that: with a single daily trigger, anything concurrent is a bug or
abuse, so a second invocation is throttled rather than quietly interleaving `get_item`/`update_item`
calls with a run already in flight. It is a duplicate-run guard, not a cost guard.

## FIS path — `src/fis_points_download.py`

1. `compose_download_url()` (`:31`) fetches `fis-ski.com/DB/alpine-skiing/fis-points-lists.html`
   with `REQUEST_HEADERS` (`:15-17`). **Without the browser User-Agent, FIS returns 403** — several
   commits exist solely to add these headers.
2. Collects `<a onclick>` elements containing `fct_export_fispointslist_csv` and reads indices
   **`[1]` and `[2]`** (`:44`, `:49`) — current list and previous list. Index `[0]` is skipped.
   *This is the single most brittle line in the file.* Commit `11b5862` exists because the link
   position already moved once, and an `IndexError: list index out of range` here was observed on
   2026-06-02. If FIS restyles the page, this is where it breaks.
3. Reads the "valid from" date by CSS class (`:57`) and fixed character offsets `[0:2]`, `[3:5]`,
   `[6:]` (`:59-61`). If that date is in the future, falls back to the previous list (`:66-68`).
   FIS publishes lists before they are valid — same problem the USSA path solves with a PDF, but
   FIS states the date inline.
   Uses `timezone('EST')`, a **fixed offset that does not follow DST**, so this can be an hour off
   near boundaries. Harmless in practice, wrong in principle.
4. `get_points_df()` (`:73`) downloads the CSV and filters to
   `Fiscode, Lastname, Firstname, Competitorname, DHpoints, SLpoints, GSpoints, SGpoints, ACpoints`,
   then `fillna(-1)`. **`-1` is the FIS "no points" sentinel.**

~16k rows. `Competitorname` here is the **raw** value from the FIS CSV — unlike USSA. That asymmetry
matters downstream; see [get-livetiming-info.md](get-livetiming-info.md).

## USSA path — `src/ussa_points_download.py`

Rewritten 2026-08-21. Base URL `POINTS_BASE_URL` (`:15`):
`https://media.usskiandsnowboard.org/CompServices/Points/Alpine`, files named `nlx{NN}{SS}.zip`
where `NN` is the zero-padded list number and `SS` the two-digit season code (2026-27 season = `27`).

### Selection

`compose_download_url()` (`:163`) is the entry point:

1. **`fetch_directory_listing()`** (`:41`) — the media host runs an **nginx autoindex**, so
   `GET .../Alpine/` returns a real file listing. One request yields both the published zips
   (`find_available_lists`, `:79`) and the schedule PDF name (`find_schedules`, `:87`).
   `LIST_ZIP_PATTERN` (`:22`) matches `nlx` only, so the parallel `flx*.zip` FIS-list files in the
   same directory are correctly ignored.
2. **`fetch_schedule()`** (`:119`) downloads `{YYYY}-{YY}_AL_List_Schedule.pdf` and
   `parse_schedule()` (`:93`) extracts it with `pypdf`. The row regex (`:23`) pulls the
   **"National Valid"** column — the second date on each row. There is also a "FIS Valid" column;
   for `nlx` national lists **National Valid is the correct one**. They happen to be identical for
   every row of the 2026-27 schedule, so a wrong choice would not show up in testing.
3. **`choose_list()`** (`:133`) takes, across *all* seasons present, the list with the latest valid
   date that has already passed and that actually has a zip on the server.

There is deliberately **no season-code derivation** in the primary path. Ranking purely by valid
date handles the early-summer overlap for free: on 2027-06-15 the 2026-27 season's List 45 (valid
Jun 1) is still in force while the 2027-28 lists don't start until Jul 2. An earlier design that
computed a season code from a May month-cutoff got this wrong every June.

### Dates and timezone

`today_in_race_timezone()` (`:32`) evaluates the date in **`America/New_York`** (`RACE_TIMEZONE`,
`:29`). Two reasons: the Lambda clock is **UTC regardless of region**, and USSA races are held only
in the US. At the 1:10am ET run the UTC date happens to match, so plain `datetime.now()` would work
today — but it would silently break if the schedule ever moved past 8pm ET. Eastern is also the
conservative choice: at 1am ET the whole country is on the valid date, so a noon-local race anywhere
in the US is safely inside it.

The PDF prints months with no year (`"Aug. 20"`). `parse_schedule` walks rows in order and
increments the year when the month runs backwards (`:110-111`), so List 27 → 2026-12-31 and
List 28 → 2027-01-07. `MONTHS` (`:24-25`) accepts both `sep` and `sept`; anything else raises rather
than silently mis-dating.

### Fallback tiers

| failure | behavior |
|---|---|
| none | directory index + schedule PDF → valid list |
| index unreachable | `probe_available_lists()` (`:54`) HEAD-probes list numbers for this season and the previous one; schedule still fetched by naming convention (`:125-127`), so **the valid date is still honored** |
| index *and* schedule unreachable | `newest_available_list()` (`:150`) — newest file on the server, which may be days early. Logs two `ERROR` lines |
| nothing on the server | raises `no USSA points lists found on the server` |

The middle tier matters: an early version dropped straight to newest-available when the index died,
silently losing valid-date correctness. `list_exists()` (`:47`) probes with `HEAD` and checks
`content-type`, which is the only reliable existence signal (see below).

Note `choose_list` has no per-season error handling — if `fetch_schedule` raises for *any* season,
the whole call fails and selection drops to newest-available. Also, `fetch_schedule` is called
inside the season loop, so with two seasons present the PDF is downloaded twice. Both are minor.

### Verified endpoint behavior

Probed 2026-08-21; these are facts about the server, not the code:

- **No auth of any kind.** Bare `curl` with no headers gets the zip. The old spoofed header block
  including a `cf_clearance` Cloudflare token was inert and is gone.
- **Missing files → HTTP 200, `content-type: text/html`, 4344 bytes**, beginning `<!DO`. Not a 404.
  This is why `get_points_df` (`:220`) checks for `PK` magic bytes (`:223`) and `list_exists` checks
  content type. A `status_code != 200` test — which is what the old code did — never fires and lets
  HTML reach `zipfile.ZipFile()` as `BadZipFile`.
- **`HEAD` works** and returns the distinguishing content type, so probing is cheap.
- **Prior seasons are deleted from the top level** and moved to `Old Files/` (seasons 19-26 are
  archived there). The top level holds only the current season.
- **Cadence changes between seasons.** 2026-27 is weekly with 45 lists; 2025-26 was biweekly with
  23. Any hand-maintained schedule table is wrong in shape, not just in dates.
- **No effective date exists anywhere in the payload.** The only dates are publication timestamps
  (HTTP `Last-Modified` and zip member mtimes, which agree). `get_published_date()` (`:213`) logs it
  as a staleness signal, but it cannot detect a pre-published list — the schedule PDF is the only
  source for that.

### Parsing the zip

Each zip holds three CSVs. `NLM*` (men) and `NLW*` (women) are used; **`NLO*` is ignored** — 1,418
rows of all-`990.00` placeholder points, apparently masters/collegiate.

- `header=None` is mandatory (see "Read this first").
- Columns are selected **positionally**: `[1, 2, 4, 7, 8, 9, 10, 11]` (`:245`) → `Lastname,
  Firstname, Fiscode, DHpoints, SLpoints, GSpoints, SGpoints, ACpoints`. Unguarded; a USSA layout
  change corrupts the data without raising.
- `Competitorname` is **synthesized** (`generate_competitor_name`, `:207`) as a sorted-character
  anagram key of first+last, lowercased and stripped to `a-z`. **This differs from FIS**, which
  stores the raw name. Both formats are consumed by the name matching in
  [get-livetiming-info.md](get-livetiming-info.md).
- **USSA uses `999.99` for unscored athletes**, where FIS uses `-1`. So the `-1 → 999.99`
  conversion in the other Lambda never fires for USSA racers. This makes the "≥3 racers at 999.99
  in the top 5" penalty override trigger far more readily on USSA races — see
  [points-calculation.md](points-calculation.md).

~3.2k rows.

## Writing to DynamoDB — `update_dynamodb` (`fis_points_download.py:83`)

Shared by both paths; the USSA module imports it (`ussa_points_download.py:13`) and passes its own
table. Tables and key schema are in [architecture.md](architecture.md).

1. `filter_rows_needing_update()` (`:144`) does a **full table scan** into a DataFrame, then a
   per-row `Series.equals` diff.
2. Floats become `Decimal`, `Fiscode` becomes `str` (`:92-97`).
3. Per row: a `get_item`, then `update_item` or `put_item` (`:107-142`).

Weak spots, none currently causing problems:

- `Series.equals` compares values *and* dtypes. Decimal-vs-float64 or object-vs-numeric mismatches
  can make it report everything as changed, or miss a change. It also compares names, so a
  name-only edit triggers a write.
- The empty-table branch (`:148`) builds `columns=[[...]]` — a nested list, i.e. a MultiIndex —
  which would break the column selection on `:151` if a table were ever truly empty.
- No `batch_writer`, no conditional writes: a full scan plus two round trips per changed row.
  Fine in practice — 8,403 FIS rows updated in 120 s against a 900 s ceiling.
- `responses` is accumulated (`:99`, `:138`, `:142`) and then discarded. The only output is the
  `UPDATES: N rows in database to be updated` log line (`:87`), which is the main thing to grep for
  when checking whether a run did anything.

## Failure handling

`fis_points_download` (`:187`) and `ussa_points_download` (`:260`) each wrap everything in
`except Exception` that logs and returns. Consequences:

- The Lambda always reports success; the `AWS/Lambda Errors` metric is permanently 0.
- A failure in the FIS half does not stop the USSA half — except that
  `connect_to_dynamo_db` calls `sys.exit()` on a connection failure (`fis:26`,
  `ussa:202`), which kills the whole invocation including the half that hasn't run yet.
- Both handlers log the exception twice (once formatted with a traceback, once bare).

This is compensated for by CloudWatch alarms rather than fixed in code. Two alarms email Matt's
gmail via SNS (a second topic goes to a bc.edu address): one on `ERROR` appearing in the logs, one
on the function *not being invoked* in 24 h. The second exists because a dead schedule produces no
logs at all, and therefore no `ERROR` to match — that failure mode ran unnoticed for 77 days.
Details in [operations.md](operations.md).

## Fragility checklist

When something breaks, in rough order of likelihood:

1. `fis_points_download.py:44` / `:49` — the magic `[1]`/`[2]` link indices.
2. `fis_points_download.py:57-61` — the CSS class selector and fixed-offset date slicing.
3. USSA schedule PDF reformatting — degrades to the warned fallback rather than crashing.
4. `ussa_points_download.py:245` — positional CSV columns; corrupts data silently.
5. The nginx autoindex being switched off — covered by the HEAD-probing tier.
6. USSA naming conventions changing (`nlx{NN}{SS}.zip`, `{YYYY}-{YY}_AL_List_Schedule.pdf`).

## Testing and deploying

Tests cover the USSA selection logic, year rollover, the fallback tiers, and the header bug —
fixture-based, no network, ~0.4 s. The FIS path has no automated coverage. See
[testing.md](testing.md) for how to run them and [operations.md](operations.md) for the Docker build
and S3 deploy (the 46 MB zip exceeds the comfortable direct-upload margin).

## Dead weight

All of it was deleted on 2026-08-21: `events/event.json` (hello-world fixture),
`src/Dockerfile` (`python:3.10`, retired container-image path) and `template.backup.yaml`.
The ECR repository that path pushed to is gone too. If any of them reappear, they are junk.
