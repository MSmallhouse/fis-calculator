# get-livetiming-info

The core lambda. A user submits a race on [fiscalculator.com](https://www.fiscalculator.com/), this
snapshots the current live-timing state of that race and computes points for every racer in it.

See also: [architecture](architecture.md) · [points-calculation](points-calculation.md) ·
[get-points-list](get-points-list.md) · [operations](operations.md) · [testing](testing.md)

---

## Read this first

Six things that cost the most time to rediscover:

1. **Grass skiing is indistinguishable from alpine by event name.** FIS sector `GS` runs Slalom,
   Giant Slalom and Super G under identical names with identical category codes. Only the sector
   code separates them. See
   [The alpine sector filter](#the-alpine-sector-filter-do-not-remove) before touching the race
   list — an event-name whitelist is *not* enough.
2. **Codexes need zero-padding to four digits.** `al0279/main.xml` is the race; `al279/main.xml` is
   a 404 that surfaces as "Race is not live or not found", which reads as the race not existing.
   See [Codex padding](#codex-padding).
3. **There are no tests here.** Only empty `__init__.py` scaffolding under `tests/`; the SAM
   hello-world boilerplate that used to sit there and abort `pytest` collection was deleted
   2026-08-21. The real workflow is the commented-out debug block at `src/app.py:288-293`, plus the
   two offline techniques in
   [Verifying a change without a test suite](#verifying-a-change-without-a-test-suite). See
   [testing](testing.md).
4. **Provider detection is substring matching with a silent fallthrough** — anything unrecognized
   is treated as a FIS codex, so an unsupported timing site returns "Race is not live or not
   found". See [Provider dispatch](#provider-dispatch).
5. **The site calls a Lambda Function URL, not the API Gateway in `template.yaml`.**
   `https://hsa35mz4zsbu6nqwlb5jvkk4o40jruqd.lambda-url.us-east-2.on.aws/`, hardcoded at
   `website/app.js:14`. The template's API Gateway event is vestigial.
6. **There is no pandas layer, and there never was.** The deployed function reports `Layers: null`;
   dependencies are bundled in the ~47.5MB zip. A 123MB `pandas-layer/` directory sat in the repo
   until 2026-08-21 referenced by nothing, and was wrongly believed to block the python3.14 move.
   A stale `get-livetiming-info/_site/` holding a copy of `src/` was deleted at the same time — if
   either reappears, it is build output, not source. See [Runtime](#runtime).

---

## Contract

Handler `app.handler` (`src/app.py:220`). Declared as `app.handler` in `template.yaml:18`.

### Request

API Gateway proxy shape. Everything arrives in `event["queryStringParameters"]`:

| param | source | notes |
|---|---|---|
| `url` | `src/app.py:272` | a live-timing.com URL, a vola URL, a `fis-ski.com/...lv-al<codex>` URL, or a bare FIS codex |
| `min-penalty` | `src/app.py:279-280` | **a comma pair**, `"<min_penalty>,<adder>"`, split on `,` |
| `event` | `src/app.py:282` | `SLpoints` \| `GSpoints` \| `SGpoints` \| `DHpoints` |

The handler is a **router** (`src/app.py:220`) with three modes: `action=races`
returns the FIS live race list (`fis_race_list.py`), `url=preload` warms the container,
and anything else scores a race. Requests missing `url`/`min-penalty`/`event` return
**400**, deliberately — the Function URL is public and scanners hit it, and a 500 there
would page us via the alerting.

`url == "preload"` short-circuits in the router (`src/app.py:234-238`) with
`{"message": "preload successful"}`. The site fires this on page load (`_includes/head.html:1`) to
warm the lambda. It returns before `handle_score_race` configures the logger (`src/app.py:275-276`),
deliberately, so page views don't pollute the logs — only real form fills get logged.

The comma pair comes from the form dropdown at `index.html:37-43`:

```
USSA                    -1,0
Open FIS                23,8
National Championship   20,8
Noram/Europa Cup        15,0
Entry League            60,8
World Cup                0,0
Citizen                 40,8
```

**`min_penalty < "0"` at `src/app.py:284` is a string comparison**, not numeric. It works only
because the USSA sentinel is literally `"-1"` and `"-" < "0"` in ASCII. USSA races then get
`min_penalty` forced to `"40"` and `is_fis_race = False`, which switches the DynamoDB table and the
event maximums. The larger category→penalty map used for the FIS race list lives in the lambda now,
as `CATEGORY_PENALTIES` (`src/fis_race_list.py:38-50`), and must be kept in sync with the dropdown
by hand. It used to be duplicated in `website/app.js`; it is not any more.

**Frontend quirk:** the query string at `website/app.js:118-120` is a template literal spanning
three source lines, so literal newlines and indentation are embedded before `&min-penalty` and
`&event`. It works because the whitespace lands inside the preceding parameter's value. Don't
"fix" the indentation without checking it still parses.

### Response

`src/app.py:352-361`, status 200:

```jsonc
{
  "results": [
    {
      "place": 1,              // "" when tied with the previous finisher
      "name": "SMITH, John",
      "score": 42.15,
      "points": 38.22,         // the racer's current list points
      // the following only appear when they exist:
      "r1_time": "52.31", "r1_rank": 3,
      "r2_time": "51.88", "r2_rank": 1,
      "r3_time": null,   "r3_rank": null,
      "time": "1:44.19"
    }
  ],
  "event": "SLpoints",
  "hasRunTimes": true,           // ALWAYS true - hardcoded at src/app.py:355
  "areScoresProjections": false,
  "notFound": "SMITH, John ",    // space-joined names whose points weren't found
  "hasThirdRun": false,
  "isStartlist": false,
  "isFisRace": true
}
```

Times are formatted by `float_to_time_string` (`src/app.py:210-218`) as `m:ss.xx` or `ss.xx`.

Two things to know about `results`:

- **`place` is assigned twice in the same dict literal** (`src/app.py:358-316`). The second wins;
  the first is dead. The live expression blanks the place on a tie with the previous finisher.
- Racers with `score == -1` (DNF/DNS/DSQ) are filtered out at `src/app.py:310` unless this is a
  startlist-only response.
- **`results` can legitimately be empty** — a race where nobody has finished yet returns 200 with
  `"results": []` and `hasThirdRun: false` (`src/app.py:358`). The frontend renders an empty table.
  This used to be an `IndexError` -> 500; see [Fixed crashes](#fixed-crashes-worth-knowing-about).

### Errors

`UserFacingException` (`src/exceptions.py`) carries its own `status_code` (default 400) and is
returned as `{"error": "<message>"}` at that status (`src/app.py:368-376`). Anything else becomes a
500 with the raw exception string (`src/app.py:378-387`). The frontend shows `errJson.error`
verbatim except on 500, where it substitutes "Something went wrong...".

**The two handlers log deliberately different prefixes, and alerting depends on it:**

| log line | emitted at | alerted? |
|---|---|---|
| `USER RAISED ERROR: ...` | `src/app.py:372` | **no** — a bad URL is not an incident |
| `UNHANDLED ERROR: ...` | `src/app.py:382` | **yes**, immediate email |
| `NAME_MATCH_MISS {json}` | `src/app.py:340-350` | yes, but batched into a daily digest |

Both error lines now include `params: {...}` so an alert can say which request broke. If you rename
those prefixes or change the `NAME_MATCH_MISS` JSON shape, update `alerts/src/error_notifier.py` and
`alerts/src/digest.py` with them — see [operations](operations.md).

Two user-facing messages exist, both from the FIS scraper:
`"Race is not live or not found"` (404, `src/scrapers.py:464`) and
`"Wait for the race to start"` (404, `src/scrapers.py:498`).

---

## Fixed crashes worth knowing about

Two `IndexError`s were fixed on 2026-08-21 (commit `040816e`), both of which reached users
as a generic 500:

- **`app.py:358`** read `output[0]` to set `hasThirdRun`. `output` comes from `finishers`, and
  a competitor only lands there if `score != -1` — but `assign_scores` sets `-1` for anyone with
  `time == 9999`, which is how DNF, DNS and DSQ are all encoded. So **a race where nobody has
  finished yet produced an empty list and crashed**: the normal state of a live race in its first
  minute, i.e. the mid-race use the site advertises. It now returns 200 with zero results, which
  renders as an empty table.
- **`app.py:133-137`** walked forward from index 10 gathering racers tied with 10th, unbounded. The
  `!= 9999` guards make a DNF-heavy field safe; the reachable case is a scraper glitch parsing
  every time identically.

Both were reproduced against the old code and confirmed against the new using technique B in
[Verifying a change without a test suite](#verifying-a-change-without-a-test-suite).

## Codex padding

FIS codexes are four digits **with leading zeros**, and the live timing server is
literal about it — `/al0279/main.xml` is the race, `/al279/main.xml` is a 404. Users
type the codex off a start list without the leading zero, so `fis_livetiming_scraper`
zero-pads any all-digit codex to four (`src/scrapers.py:431-432`). Values already four
digits or longer are untouched. Before this, `279` failed with "Race is not live or
not found" while `0279` worked, which reads as the race simply not existing.

## The alpine sector filter (do not remove)

The race list comes from `general/live.html?sectorcode=AL&...`, with the sector
filter stated explicitly rather than relying on the `/DB/alpine-skiing/` path.

**Grass skiing (sector `GS`) runs Slalom, Giant Slalom and Super G under exactly the
same event names, with the same FIS category codes.** Neither the event name nor the
category can tell it apart from alpine — only the sector code can. On 2026-08-21 the
unfiltered page carried 12 grass-skiing races at Tambre (BL) alongside 2 alpine races
at El Colorado; an event-name whitelist happily accepted 6 of the grass-skiing ones.

So `fis_race_list.py` checks the sector too. One wrinkle: **the sector column only
appears when the page is not already filtered by sector.** The check therefore accepts
rows with no sector code (the URL filter did the job) and rejects rows carrying a
non-alpine one (the filter was ignored). Requiring `AL` unconditionally returns zero
races against the filtered URL — that mistake was made and caught in testing.

## Runtime

**python3.14** since Aug 2026 (commit `06f070c`), matching [get-points-list](get-points-list.md).
`pandas` moved `2.3.1` -> `>=2.3.3,<3`: 2.3.3 is the first release with cp314 wheels, and pandas
3.x is held off because it changes copy-on-write and the default string dtype, which the DynamoDB
lookup paths in `utils.py` have not been checked against. `phpserialize` — sdist-only and
unmaintained since 2016 — installs and round-trips fine on 3.14.

A note on a claim you may find elsewhere: the `pandas-layer/` directory was long assumed to block
this upgrade, because its path is hardcoded to `python/lib/python3.10/site-packages`. That was
wrong. **The deployed function has `Layers: null`** and always has; dependencies are bundled in
the function zip. The `pandas-layer/` directory was deleted on 2026-08-21.

## Verifying a change without a test suite

This lambda has no tests, so changes are verified with two complementary techniques. Both were used
for the python3.14 move and the two crash fixes; reuse them for anything touching scraping or
scoring.

### A. Differential run against a real race

Proves end-to-end behaviour is unchanged, including the scrapers and DynamoDB.

1. Capture the live Function URL's response for a known race as a baseline, **before** changing
   anything. Fetch it twice to confirm the race isn't still updating.
2. Run the modified source in a `public.ecr.aws/lambda/python:3.14` container
   (`--platform linux/amd64`, mount `~/.aws` read-only for the DynamoDB lookups) and diff the JSON
   against the baseline.
3. Deploy, then fetch the live URL again and diff once more.

Codex **5279** (Noram/Europa Cup SL, 16 finishers, no unmatched racers) is a known-good case worth
reusing while it stays live. Note this only exercises the paths that race happens to hit — a clean
race touches no DNF, tie, projection or name-matching code at all.

### B. Synthetic edge cases, offline

Covers what a single real race cannot, and needs no network:

```python
import app, scrapers, utils
c = scrapers.Competitor("RACER One"); c.time = 61.11; c.fis_points = 42.0
race = app.Race("1234", "23", "8", "SLpoints", True)
race.competitors = [c, ...]; race.winning_time = 61.11
utils.scrape_results = lambda r: None          # bypass the network
utils.connect_to_database = lambda r: None
```

Worth covering: DNFs in the field, the >=3-unscored penalty override, fewer-than-five-finishers
padding, an all-identical-times field, an empty field, both name-lookup paths with `Decimal` values
from DynamoDB, time parsing and formatting, and a `phpserialize` round trip. An 18-check harness of
exactly this shape caught nothing on the 3.14 move (correctly) and confirmed both crash fixes.


## Provider dispatch

`Race.__init__` sniffs the URL string (`src/app.py:53-59`):

```python
if 'vola' in url:            url_type = 'vola'
elif 'live-timing' in url:   url_type = 'live-timing'
else:                        url_type = 'fis'
```

**Anything unrecognized falls through to FIS**, where it is treated as a bare codex — including the
zero-padding below, which will happily pad a meaningless string. A typo'd URL therefore produces
"Race is not live or not found" rather than "unsupported provider". If a user reports a confusing
404, check the URL shape first.

This is not hypothetical. Production logs carry real requests with `alpinetiming.co.nz` URLs — a New
Zealand timing service the calculator does not support — and every one of those users was told the
race did not exist. Adding a fourth provider, or just an honest "that site isn't supported" message,
would be a real improvement.

Routing to the scrapers happens in `scrape_results` (`src/utils.py:255-276`), which also decides
which of the four name-matching functions runs.

`live-timing` is special-cased at `src/app.py:92`: it is the only provider that **does not connect
to DynamoDB at all**, because its feed carries points inline.

---

## Scraper: live-timing.com

`livetiming_scraper`, `src/scrapers.py:324-417`.

Hits `https://www.live-timing.com/includes/aj_race.` + `race.url.split(".")[-1]`
(`src/scrapers.py:326`) — it grafts the tail of the user's URL onto the AJAX endpoint. No HTML
parsing; the response is a pipe-delimited `key=value` stream.

Fields are filtered by prefix (`src/scrapers.py:330-346`):

- `m=` name — also the record separator; records are split on each `m=` (`src/scrapers.py:359-365`)
- `fp=` FIS points / `up=` USSA points — chosen by `race.is_fis_race`
- `r1`, `r2` run times
- `tt=` total time

**Points come from the feed**, `int(starter[1][3:])/100` at `src/scrapers.py:414`. This assumes the
points field is always the second element of the record. No DynamoDB, so no name matching, and the
`NAME_ERROR_FISCODES` patches don't apply here.

Quirks:

- DNS filtered up front by string match on `racer[2]` (`src/scrapers.py:370`).
- DNF/DSQ detected by sniffing the joined record for a missing `tt=`, or `DQ`/`DNF`/`DNS`, or
  membership in `TIMES_AS_LETTERS` (`src/scrapers.py:396-401`). An inline comment notes times can
  arrive as `DQg35`, which is why the check is a substring search rather than equality.
- Total time sometimes equals a single run time; patched by recomputing `r1 + r2`
  (`src/scrapers.py:412-413`).
- Provides no bibs, no codex, no gender, no category — all of that comes from the user's form.

---

## Scraper: Vola

`vola_scraper`, `src/scrapers.py:29-322`. The most fragile of the three.

POSTs to `https://vola.ussalivetiming.com/livetiming.php?command=<cmd>` (`src/scrapers.py:44`) with
a fully spoofed browser header block (`src/scrapers.py:44-61`) and payload
`{command, race_idx, runno}`. Two commands: `GetHeatListFields` returns column definitions
(`title`, `grid`, `col`); `GetHeatListValues` returns the cell values. JSON, not HTML.

**`race_idx` is `url.split("_")[1].split(".")[0]`** (`src/scrapers.py:37-39`). Any URL without an
underscore raises `IndexError`. This is the first thing to check when a Vola race fails.

### How columns are located

There is no schema. The scraper scans field titles for the substrings `"order"`, `"name"`, and
`"time"`, collects the matching `(grid, col)` coordinate pairs into a set, then keeps only values
at those coordinates (`src/scrapers.py:126-131` for the startlist, `:161-165` for results).
Values containing `&nbsp` are skipped.

### The ALL-CAPS surname assumption

Names arrive either as one field or split into first/last, detected by looking for `"first"` or
`"last"` in the column title (`src/scrapers.py:129`). When split,
`combine_first_last_name_fields` (`src/scrapers.py:98-113`) rejoins them —
**assuming the surname is the ALL-CAPS one**:

```python
if fields[i]['value'].isupper():
    fields[i]['value'] += " " + fields[i+1]['value']   # LAST first
else:
    fields[i+1]['value'] += " " + fields[i]['value']
```

`add_comma_to_full_name` (`src/scrapers.py:186-199`) makes the same assumption when splitting a
combined name, scanning for the first upper→lower transition. A racer whose name is entered in
mixed case will be silently mangled.

`filter_fields_with_no_time` (`src/scrapers.py:77-95`) walks the stream in awkward groups of three
because Vola emits name rows with no corresponding time. Its own comment calls this "pretty
awkward".

### Other Vola specifics

- Run 2 is only fetched for SL/GS (`src/scrapers.py:313-318`); speed races are single-run.
- `r2_time = total - r1_time` (`src/scrapers.py:283`) — the feed gives cumulative totals.
- Run ranks are computed only for tech races (`src/scrapers.py:288-305`).
- DNS is skipped by substring match on the time value (`src/scrapers.py:258`); DNF falls out via
  `time_to_float` returning `9999`.
- **Provides no fiscodes**, which forces the full-table scan described below.
- A TODO block at `src/scrapers.py:30-35` documents the correct approach that was never
  implemented: the page's own JS stores the startlist at `response["4"]` and results at
  `response["0"]`. If this scraper needs real work rather than patching, start there.
- `initialize_starting_racers` carries two more TODOs (`src/scrapers.py:208-209`, `:214-215`):
  DNS handling, and capturing start order so `B` could be computed from the seed. The second is
  the same gap noted in [points-calculation](points-calculation.md).

---

## Scraper: FIS livetiming

`fis_livetiming_scraper`, `src/scrapers.py:419-702`. The most reliable, and the only one that
supplies fiscodes.

Codex extraction: regex `lv-al(\d+)` against a fis-ski URL, else the raw string
(`src/scrapers.py:421-425`).

Two-step fetch:

1. `https://live.fis-ski.com/general/serverListFull.xml?t=<ms>` → pick `parsed['servers'][0][0]`
   (`src/scrapers.py:450-456`)
2. `{server}/al<CODEX>/main.xml?t=<ms>` (`src/scrapers.py:460`). A 404 raises
   `UserFacingException("Race is not live or not found", 404)`.

### The payload is PHP-serialized, despite the `.xml` name

`<lt>` tags are stripped by regex (`src/scrapers.py:436-437`), then parsed with
`phpserialize.loads(..., decode_strings=True)`.

**PHP serialization encodes byte lengths.** Multi-byte characters therefore break the parse. The
workaround (`remove_german_chars`, `src/scrapers.py:441-448`) substitutes exactly nine characters:

```
ä ö ü ß  →  z        Ä Ö Ü  →  Z        é → z    É → Z
```

**This is incomplete by design and will break on other alphabets** — Nordic `ø`/`å`, Polish `ł`,
Czech `ř`, Spanish `ñ`. If a FIS race throws a phpserialize length error, an unhandled character in
a racer's name is the near-certain cause; add it to the map. The payload is then re-encoded as
`iso-8859-1` before parsing (`src/scrapers.py:471`), which is what makes `é` survive at all.

Note `phpserialize` (v1.3, last released 2016, sdist-only) is unmaintained. It is pure Python and
works fine on 3.13/3.14, but it is ~50 lines to vendor if it ever breaks.

### Structures used

| key | meaning |
|---|---|
| `racers` | fiscode → `(fiscode, last, first)`, becomes the `starters` dict (`src/scrapers.py:491-497`) |
| `startlist[0][0][run]` | start order per run |
| `result[0][run]` | results per run |
| `racedef[0][run]` | column definitions, used to find the finish column |

### `finish_location` inference

The index within a result row holding the finish time is not declared — it is found by scanning
`racedef` for the substring `'finish'` (`src/scrapers.py:554-564`). There is an explicitly
self-deprecating branch ("hacky bug fix ... shitty code for now") for when run 2 hasn't started
yet, which falls back to `racedef[0][0]`.

Result rows are then skipped if `len(result) != finish_location + 1` (`src/scrapers.py:583`) — with
split timing, a DNF shows intervals but no finish, and this is how they're detected.

### Accumulated bug workarounds

Each of these is a real observed FIS behavior, not defensive padding:

- Results sometimes live at `result[0][1]` instead of `result[0][0]` (`src/scrapers.py:576`).
- Times can carry a suffix: `85530:p2`, `85530:c`. Split on `:` and keep the first part
  (`src/scrapers.py:588`, `:614`, `:637`).
- Stray fiscodes appear that aren't in `starters`; skipped (`src/scrapers.py:592`).
- `time == 0` means DNF, not a zero-second run; those racers are dropped
  (`src/scrapers.py:672`).
- Third-run DNFs were being missed, patched at `src/scrapers.py:667`.
- DNS removal is two-pronged (`src/scrapers.py:517-523`): racers flagged `'dns'` **and** racers
  simply absent from the run-1 startlist, because FIS sometimes just omits them.
- The per-bib `finished` flag comes from scanning the startlist row for the substring `'finish'`
  (`construct_start_order_to_fiscode_map`, `src/scrapers.py:473-485`).

Times are milliseconds ÷ 1000, rounded to 2dp.

### Three-run indoor slaloms

Supported by a third block at `src/scrapers.py:642-649` that is an acknowledged copy-paste of the
run-2 block. Surfaces as `hasThirdRun` in the response.

### Startlist-only mode

If there is a startlist but no results, `create_startlist` (`src/scrapers.py:487-498`) sets
`race.is_startlist_only = True`, assigns bibs by startlist order, and the handler returns names and
points sorted by bib with no scoring at all (`src/app.py:96-98`). This is what the site shows
before a race begins.

---

## Points lookup and the name-matching problem

Points come from the same DynamoDB tables written by [get-points-list](get-points-list.md):
`points_list_dynamo_db` (FIS) or `ussa_points_list` (USSA), selected by `race.is_fis_race` at
`src/utils.py:27`. Partition key `Fiscode` (String).

Two very different access patterns (`scan_dynamodb_table`, `src/utils.py:53-90`):

- **FIS livetiming** supplies fiscodes → `batch_get_item` in 100-key pages with a projection
  expression. Cheap and exact.
- **Everything else** → **full table scan** of ~16k or ~3.2k rows, then match by name.

### The anagram key

Names are canonicalized by lowercasing, stripping everything outside `a-z`, and **sorting the
characters**:

```python
def preprocess_name(full_name):
    return ''.join(sorted(re.sub('[^a-z]', '', full_name.lower())))
```

`src/utils.py:103-104`. The same function is duplicated as
`generate_ussa_competitor_name` (`src/scrapers.py:201-204`) and again in
`get-points-list/src/ussa_points_download.py`.

So `SMITH, John` and `john Sm-itH` match — and so does any anagram. Collisions are possible by
construction. The human-readable name is stashed in `competitor.temp_full_name` and restored for
output at `src/app.py:301-302`.

Note the asymmetry documented in [get-points-list](get-points-list.md): FIS rows store
`Competitorname` raw from the CSV, while USSA rows store it *already scrambled*. That is why
`ussa_add_points_to_competitors` compares `Competitorname` directly while the Vola matcher
recomputes `ProcessedName` first.

### Four matchers, one dead

Selected at `src/utils.py:266-276`:

| function | line | strategy |
|---|---|---|
| `fis_livetiming_add_points_to_competitors` | `src/utils.py:193` | exact `Fiscode` — the only reliable path |
| `vola_fis_add_points_to_competitors` | `src/utils.py:106` | anagram key vs `Competitorname` |
| `ussa_add_points_to_competitors` | `src/utils.py:223` | exact `Competitorname` (already scrambled) |
| `OLD_vola_fis_add_points_to_competitors` | `src/utils.py:142` | dead code, kept for reference |

### Known defects in the matchers

- **O(n²) recompute.** `src/utils.py:109` rebuilds `points_df["ProcessedName"]` for the entire
  points list *inside the per-competitor loop*. With a full-table scan behind it, this is the main
  candidate for the 120s timeout on a large Vola field.
- **`NAME_ERROR_FISCODES` key mismatch.** `src/utils.py:124` tests membership with the *raw* name
  but `src/utils.py:125` indexes with `preprocess_name(...)`. The dict (`src/utils.py:16-22`)
  holds both raw and scrambled keys for two of its three entries — Carter Robinson J. has only the
  raw form, so that path can `KeyError`.
- **`ussa_add_points_to_competitors` checks the wrong dict.** It early-exits on
  `NAME_ERROR_USSA_CODES` (`src/utils.py:231`, permanently empty at `src/utils.py:23`) but then
  indexes `NAME_ERROR_FISCODES` (`src/utils.py:234-238`).
- The manual patch list grows every season and is the only remedy for a racer whose name won't
  match.

---

## Deployment reality

`template.yaml` does not describe what runs. See [operations](operations.md) for the full picture.

| | template says | actually deployed |
|---|---|---|
| invoke path | API Gateway `GET /get-livetiming-info` | **Lambda Function URL**, `AuthType: NONE`, `CORS: *` |
| layers | none declared | none attached (`Layers: null`), never were |
| DynamoDB access | implicit SAM role, no policies | policies attached by hand |
| CORS | **absent entirely** | configured on the Function URL |

Timeout 120s, MemorySize 2048, python3.14, x86_64 (`template.yaml:7-12`). Deployed CodeSize
~47MB (it churns with every deploy; check the live value rather than trusting a number here), no reserved concurrency (deliberate — see [operations](operations.md)). Stack `get-livetiming-info`, region `us-east-2`, account `828841719603`.
`samconfig.toml` carries a stale global `stack_name = "selenium-get-fis-points-list"` that the
deploy section overrides.

A clean `sam deploy` into a fresh account would not produce a working system.

---

## Fragility checklist

When something breaks, in rough order of likelihood:

1. **Vola URL shape** — `race_idx` extraction (`src/scrapers.py:37-39`).
2. **A non-German accented character in a FIS racer's name** — extend `remove_german_chars`
   (`src/scrapers.py:441-448`).
3. **FIS restyles or reorders `racedef`** — `finish_location` inference breaks
   (`src/scrapers.py:554-564`).
4. **Vola renames a column title** — the `"order"`/`"name"`/`"time"` substring scan finds nothing
   and the race comes back empty.
5. **A name that won't match** — add to `NAME_ERROR_FISCODES` (`src/utils.py:16-22`), minding the
   key-mismatch bug above.
6. **Timeout on a large Vola field** — the O(n²) recompute at `src/utils.py:109`.

## Seasonal maintenance

- ~~`score2027`~~ — **removed Aug 2026, no longer a chore.** The site used to show `Score` (penalty
  without the adder) beside `2027 Score` (penalty with it) while both methods were current. From
  the 2027 season the adder is simply part of the penalty, so there is one `penalty` and one
  `score`, and nothing season-named left to bump. See
  [points-calculation](points-calculation.md).
- **F-factors and event maximums** (`src/app.py:11-24`, `:35-46`) are FIS rulebook constants.
  Nothing in the code records which season's rules they encode. See
  [points-calculation](points-calculation.md) — ask Matt, don't guess.
- **Penalty/adder pairs** exist in two places that must stay in sync with each other and with the
  FIS category list: the manual-entry dropdown at `index.html:37-43`, and `CATEGORY_PENALTIES` at
  `src/fis_race_list.py:38-50`.
