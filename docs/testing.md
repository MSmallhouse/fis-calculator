# Testing

Coverage is deliberately lopsided: `get-points-list` has a real suite,
`get-livetiming-info` has none. Know which half you're in before you promise
anything about safety.

See also: [`architecture.md`](architecture.md) ·
[`get-points-list.md`](get-points-list.md) ·
[`get-livetiming-info.md`](get-livetiming-info.md) ·
[`operations.md`](operations.md) · [`points-calculation.md`](points-calculation.md)

## get-points-list — real suite

```bash
cd get-points-list
pip install -r requirements-dev.txt      # = -r src/requirements.txt + boto3 + pytest
python -m pytest tests/ -q               # 22 tests, ~0.4s, no network
```

Layout:

```
tests/conftest.py                          puts src/ on sys.path (flat package root)
tests/fixtures/2026-27_AL_List_Schedule.pdf   the real USSA schedule PDF
tests/fixtures/directory_index.html           saved nginx autoindex of the USSA media dir
tests/unit/test_ussa_points_download.py       all 22 tests
```

`conftest.py` exists because the lambda imports flat (`from fis_points_download
import ...`), so `src/` has to be the package root. Fixtures are real captured
artifacts, not hand-written mocks — the whole point is to pin the actual shape of
what USSA serves.

**Everything is offline.** Network calls are monkeypatched. The suite runs in
under a second and is safe to run in a loop while iterating.

### Why these tests exist

They target a specific bug class: **a run that succeeds and writes wrong data.**

No alarm can catch that. The lambda swallows exceptions, so CloudWatch reports
success; the log-error alarm sees no `ERROR` line; the "did not run" alarm sees
an invocation. Everything is green and the points are wrong. See
[`operations.md`](operations.md) for why the monitoring is structurally blind here.

Three real bugs of exactly this shape, all now pinned:

1. **Picking a not-yet-valid list.** USSA uploads a points list a few days before
   it becomes legal for competition. On 2026-08-19 the newest file on the server
   was list 08, but list 08 wasn't valid until 08-20 — the correct answer was list
   07. Selecting "newest available" silently loaded points that weren't in force.
2. **Year failing to roll over.** The schedule PDF prints months with no year
   ("Dec. 31", "Jan. 7"). Rows run in order, so the year ticks when the month goes
   backwards. Get that wrong and every list from January onward is misdated.
3. **The headerless-CSV bug.** USSA CSVs have no header row. A plain
   `pd.read_csv()` consumed the first athlete of each file as column names,
   silently dropping two skiers from every single run — always the same two, since
   the files are alphabetical.

### They were mutation-verified

Passing tests prove nothing on their own. Both fixed bugs were reintroduced to
confirm the suite actually catches them:

| mutation | result |
|---|---|
| drop `header=None` from the CSV reads | **1 failed** — `test_first_athlete_is_not_eaten_as_a_header` |
| ignore the valid date, take the newest list | **4 failed** — the Aug-19 case, the Aug-13 boundary, and the probe-fallback path |

If you materially change list selection or CSV parsing, redo this. A green suite
that doesn't fail when you break the thing is decoration.

### Running against the real runtime

Local Python is fine for iterating, but the deployed runtime is **python3.14** on
Amazon Linux. To test there:

```bash
cd get-points-list
docker run --rm --platform linux/amd64 -v "$PWD":/work -w /work \
  --entrypoint /bin/sh public.ecr.aws/lambda/python:3.14 -c '
    pip install pytz requests bs4 "pandas>=2.3.3,<3" numpy python-dateutil pypdf boto3 pytest
    python3 -m pytest tests/ -q'
```

`--platform linux/amd64` matters on Apple Silicon — the function is x86_64, and
you want the same wheels it will actually run.

Two constraints worth remembering: **pandas must be `>=2.3.3`** (first release
with cp314 wheels) and **`<3`** (pandas 3.x changes copy-on-write and the default
string dtype, which this code has not been checked against). Unpinned, pip
resolves to 3.x.

### What's worth testing here

Worth it: list selection by valid date, schedule-PDF parsing and year rollover,
directory-index parsing, the fallback tiers, CSV column mapping and row counts.
All pure logic over fixtures, all fast.

Not worth it: DynamoDB writes, live network calls, the FIS scrape. High
maintenance, low signal, and they fail for reasons unrelated to your change. The
FIS half is instead smoke-tested by hand when touched — see
[`get-points-list.md`](get-points-list.md).

## get-livetiming-info — no tests

`get-livetiming-info/tests/unit/test_handler.py` is **unmodified SAM hello-world
boilerplate**. It does `from hello_world import app` — a module that does not
exist in this repo — and asserts `data["message"] == "hello world"`. It fails at
collection with `ModuleNotFoundError`. Both were deleted on 2026-08-21, along with the matching
untouched fixture and contains none of the real query parameters, so
`sam local invoke` against it cannot exercise the handler either.

**Do not mistake those files for coverage.** The equivalent boilerplate was
deleted from `get-points-list` because it blocked pytest collection; it survives
here only because nothing else runs in this directory yet.

So the scoring math and all three scrapers have **zero** automated safety net.

### How changes here actually get verified

Two techniques, both proven on 2026-08-21 for the python3.14 move and two crash fixes. Full recipes
in [`get-livetiming-info.md`](get-livetiming-info.md#verifying-a-change-without-a-test-suite):

- **Differential run** — capture the live Function URL's response for a known race *before* the
  change, run the modified source in a `public.ecr.aws/lambda/python:3.14` container (mount
  `~/.aws` read-only so the DynamoDB lookups work), diff the JSON. Codex **5279** is a known-good
  case. Catches regressions across the scrapers, the lookups and the scoring in one shot — but only
  on the paths that one race happens to touch.
- **Synthetic edge cases** — build `scrapers.Competitor` objects by hand, set `.time` and
  `.fis_points`, monkeypatch `utils.scrape_results` and `utils.connect_to_database`. Needs no
  network and reaches everything a clean race misses: DNFs, ties, the penalty overrides, empty
  fields, `Decimal` values from DynamoDB.

Neither is a substitute for a suite, but together they are enough to say a change is safe with
evidence rather than hope. **Use both, and say which you ran.**

### The actual workflow

Uncomment the debug block at `get-livetiming-info/src/app.py:244-249`:

```python
#URL = "1926"
#MIN_PENALTY = "23"
#ADDER = "8"
#EVENT = "GSpoints"
#is_fis_race = True
#race = Race(URL, MIN_PENALTY, ADDER, EVENT, is_fis_race)
```

Set `URL` to a FIS codex (or a live-timing / Vola URL), match `MIN_PENALTY` and
`ADDER` to the race level from the form's encoding, pick the event, uncomment,
and run locally.

**Those constants are routinely left edited in the working tree.** A `git diff`
showing only changes inside that commented block is *not* a real change — it's
leftover from the last manual test. Leave it alone; don't revert it, don't commit
it, don't treat it as part of your change set.

### Seasonality

You can only test against races that are actually happening. The northern season
runs roughly **November through April**. Southern-hemisphere FIS races
(Chile, Argentina, New Zealand) run **August through September**, which is the
only off-season window with live data. Outside those, the FIS livetiming server
returns "race is not live or not found" for everything and there is nothing to
scrape.

Plan verification around that. If you're changing scraper behavior in, say, June,
you cannot confirm it end-to-end — say so rather than implying you did.

### If you want tests here

The thing to build is recorded fixtures from all three providers, mirroring
`get-points-list`: capture one real payload per provider (a live-timing AJAX blob,
a Vola `GetHeatListValues` response, a FIS `main.xml` PHP-serialized dump), commit
them, and test the parsers offline. The synthetic-edge-case technique above already
covers the scoring math — formalising it as `pytest` cases is the cheapest first
step and needs no fixtures at all. The scoring math in
particular is pure and trivially testable — penalty, A/B/C, race points, the
top-10 and top-5 rules, DNF handling. See
[`points-calculation.md`](points-calculation.md) for what the expected values
should be.
