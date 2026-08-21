# get-livetiming-info

The core lambda. A user submits a race on [fiscalculator.com](https://www.fiscalculator.com/), this
snapshots the current live-timing state of that race and computes points for every racer in it.

See also: [architecture](architecture.md) · [points-calculation](points-calculation.md) ·
[get-points-list](get-points-list.md) · [operations](operations.md) · [testing](testing.md)

---

## Read this first

Five things that cost the most time to rediscover:

1. **There are no tests here.** `tests/unit/test_handler.py` is unmodified SAM hello-world
   boilerplate that imports a nonexistent module; `pytest` errors at collection. The real workflow
   is the commented-out debug block at `src/app.py:244-249`. See [testing](testing.md).
2. **`get-livetiming-info/_site/` contains a stale copy of `src/`.** Jekyll build output that got
   committed once. Grep hits in there are lies. Same for `template-copy.yaml` (python3.9).
3. **`pandas-layer/` is dead.** 123MB on disk, referenced by nothing, and the deployed function
   reports `Layers: null`. Dependencies are bundled in the 30.8MB function zip. See
   [Why still python3.10](#why-still-python310).
4. **The site calls a Lambda Function URL, not the API Gateway in `template.yaml`.**
   `https://hsa35mz4zsbu6nqwlb5jvkk4o40jruqd.lambda-url.us-east-2.on.aws/`, hardcoded at
   `website/app.js:93`. The template's API Gateway event is vestigial.
5. **Provider detection is substring matching with a silent fallthrough** — anything unrecognized
   is treated as a FIS codex. See [Provider dispatch](#provider-dispatch).

---

## Contract

Handler `app.handler` (`src/app.py:219`). Declared as `app.handler` in `template.yaml:18`.

### Request

API Gateway proxy shape. Everything arrives in `event["queryStringParameters"]`:

| param | source | notes |
|---|---|---|
| `url` | `src/app.py:223` | a live-timing.com URL, a vola URL, a `fis-ski.com/...lv-al<codex>` URL, or a bare FIS codex |
| `min-penalty` | `src/app.py:235-236` | **a comma pair**, `"<min_penalty>,<adder>"`, split on `,` |
| `event` | `src/app.py:238` | `SLpoints` \| `GSpoints` \| `SGpoints` \| `DHpoints` |

`url == "preload"` short-circuits at `src/app.py:224-228` with
`{"message": "preload successful"}`. The site fires this on page load (`_includes/head.html:1`) to
warm the lambda. It returns *before* the logger is configured, deliberately, so page views don't
pollute the logs — only real form fills get logged (`src/app.py:230-233`).

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

**`min_penalty < "0"` at `src/app.py:240` is a string comparison**, not numeric. It works only
because the USSA sentinel is literally `"-1"` and `"-" < "0"` in ASCII. USSA races then get
`min_penalty` forced to `"40"` and `is_fis_race = False`, which switches the DynamoDB table and the
event maximums. A larger category→penalty map for FIS-app-driven races lives separately at
`website/app.js:275-306` and must be kept in sync with the dropdown by hand.

**Frontend quirk:** the query string at `website/app.js:122-124` is a template literal spanning
three source lines, so literal newlines and indentation are embedded before `&min-penalty` and
`&event`. It works because the whitespace lands inside the preceding parameter's value. Don't
"fix" the indentation without checking it still parses.

### Response

`src/app.py:295-309`, status 200:

```jsonc
{
  "results": [
    {
      "place": 1,              // "" when tied with the previous finisher
      "name": "SMITH, John",
      "score": 42.15,
      "points": 38.22,         // the racer's current list points
      "score2027": 50.15,      // score using next_year_penalty
      // the following only appear when they exist:
      "r1_time": "52.31", "r1_rank": 3,
      "r2_time": "51.88", "r2_rank": 1,
      "r3_time": null,   "r3_rank": null,
      "time": "1:44.19"
    }
  ],
  "event": "SLpoints",
  "hasRunTimes": true,           // ALWAYS true - hardcoded at src/app.py:298
  "areScoresProjections": false,
  "notFound": "SMITH, John ",    // space-joined names whose points weren't found
  "hasThirdRun": false,
  "isStartlist": false,
  "isFisRace": true
}
```

Times are formatted by `float_to_time_string` (`src/app.py:209-217`) as `m:ss.xx` or `ss.xx`.

Two things to know about `results`:

- **`place` is assigned twice in the same dict literal** (`src/app.py:269-270`). The second wins;
  the first is dead. The live expression blanks the place on a tie with the previous finisher.
- Racers with `score == -1` (DNF/DNS/DSQ) are filtered out at `src/app.py:264` unless this is a
  startlist-only response.
- `hasThirdRun` reads `output[0].keys()` (`src/app.py:301`) — **it will `IndexError` if `output`
  is empty**, which then surfaces as a generic 500.

### Errors

`UserFacingException` (`src/exceptions.py`) carries its own `status_code` (default 400) and is
returned as `{"error": "<message>"}` at that status (`src/app.py:311-318`). Anything else becomes a
500 with the raw exception string (`src/app.py:320-328`). The frontend shows `errJson.error`
verbatim except on 500, where it substitutes "Something went wrong...".

Two user-facing messages exist, both from the FIS scraper:
`"Race is not live or not found"` (404, `src/scrapers.py:457`) and
`"Wait for the race to start"` (404, `src/scrapers.py:498`).

---

## Why still python3.10

`get-points-list` moved to python3.14 in Aug 2026; this one did not. The reason usually given is
the `pandas-layer/` directory, whose path is hardcoded to `python/lib/python3.10/site-packages` —
Lambda only puts the matching runtime version on `sys.path`, so a layer built for 3.10 silently
stops resolving on any other runtime.

**But the deployed function has `Layers: null`.** Nothing references `pandas-layer/` in any
template, config, or source file. Dependencies are bundled in the function zip (CodeSize
30,863,104). So the layer is not actually a blocker — it is 123MB of dead weight that should be
deleted.

The real work is therefore the same as it was for [get-points-list](get-points-list.md): rebuild
the bundled dependencies against 3.14 and flip `template.yaml:10`. `pandas` must go to `>=2.3.3`
for cp314 wheels and should be held `<3`.

**Better still, drop pandas from this lambda entirely.** It is used for almost nothing:

| use | location |
|---|---|
| `pd.DataFrame(list_of_dicts)` | `src/utils.py:94` |
| one `pd.to_numeric(errors='coerce')` | `src/utils.py:97` |
| boolean masks + `.iloc[0][col]` | `src/utils.py:111-139`, and the parallel matchers |

All of it is a dict-of-lists and a loop in plain Python. Removing it drops ~120MB, cuts cold-start
time (which matters — the site warm-pings on page load), and removes the runtime-upgrade problem
permanently. It is also the natural moment to fix the O(n²) recompute described below.

---

## Provider dispatch

`Race.__init__` sniffs the URL string (`src/app.py:53-59`):

```python
if 'vola' in url:            url_type = 'vola'
elif 'live-timing' in url:   url_type = 'live-timing'
else:                        url_type = 'fis'
```

**Anything unrecognized falls through to FIS**, where it is treated as a bare codex. A typo'd URL
therefore produces "Race is not live or not found" rather than "unrecognized provider". If a user
reports a confusing 404, check the URL shape first.

Routing to the scrapers happens in `scrape_results` (`src/utils.py:255-276`), which also decides
which of the four name-matching functions runs.

`live-timing` is special-cased at `src/app.py:92`: it is the only provider that **does not connect
to DynamoDB at all**, because its feed carries points inline.

---

## Scraper: live-timing.com

`livetiming_scraper`, `src/scrapers.py:325-418`.

Hits `https://www.live-timing.com/includes/aj_race.` + `race.url.split(".")[-1]`
(`src/scrapers.py:327`) — it grafts the tail of the user's URL onto the AJAX endpoint. No HTML
parsing; the response is a pipe-delimited `key=value` stream.

Fields are filtered by prefix (`src/scrapers.py:331-347`):

- `m=` name — also the record separator; records are split on each `m=` (`src/scrapers.py:360-366`)
- `fp=` FIS points / `up=` USSA points — chosen by `race.is_fis_race`
- `r1`, `r2` run times
- `tt=` total time

**Points come from the feed**, `int(starter[1][3:])/100` at `src/scrapers.py:415`. This assumes the
points field is always the second element of the record. No DynamoDB, so no name matching, and the
`NAME_ERROR_FISCODES` patches don't apply here.

Quirks:

- DNS filtered up front by string match on `racer[2]` (`src/scrapers.py:371`).
- DNF/DSQ detected by sniffing the joined record for a missing `tt=`, or `DQ`/`DNF`/`DNS`, or
  membership in `TIMES_AS_LETTERS` (`src/scrapers.py:396-401`). An inline comment notes times can
  arrive as `DQg35`, which is why the check is a substring search rather than equality.
- Total time sometimes equals a single run time; patched by recomputing `r1 + r2`
  (`src/scrapers.py:412-413`).
- Provides no bibs, no codex, no gender, no category — all of that comes from the user's form.

---

## Scraper: Vola

`vola_scraper`, `src/scrapers.py:30-323`. The most fragile of the three.

POSTs to `https://vola.ussalivetiming.com/livetiming.php?command=<cmd>` (`src/scrapers.py:44`) with
a fully spoofed browser header block (`src/scrapers.py:45-62`) and payload
`{command, race_idx, runno}`. Two commands: `GetHeatListFields` returns column definitions
(`title`, `grid`, `col`); `GetHeatListValues` returns the cell values. JSON, not HTML.

**`race_idx` is `url.split("_")[1].split(".")[0]`** (`src/scrapers.py:38-40`). Any URL without an
underscore raises `IndexError`. This is the first thing to check when a Vola race fails.

### How columns are located

There is no schema. The scraper scans field titles for the substrings `"order"`, `"name"`, and
`"time"`, collects the matching `(grid, col)` coordinate pairs into a set, then keeps only values
at those coordinates (`src/scrapers.py:127-131` for the startlist, `:162-165` for results).
Values containing `&nbsp` are skipped.

### The ALL-CAPS surname assumption

Names arrive either as one field or split into first/last, detected by looking for `"first"` or
`"last"` in the column title (`src/scrapers.py:130-131`). When split,
`combine_first_last_name_fields` (`src/scrapers.py:99-114`) rejoins them —
**assuming the surname is the ALL-CAPS one**:

```python
if fields[i]['value'].isupper():
    fields[i]['value'] += " " + fields[i+1]['value']   # LAST first
else:
    fields[i+1]['value'] += " " + fields[i]['value']
```

`add_comma_to_full_name` (`src/scrapers.py:187-200`) makes the same assumption when splitting a
combined name, scanning for the first upper→lower transition. A racer whose name is entered in
mixed case will be silently mangled.

`filter_fields_with_no_time` (`src/scrapers.py:78-96`) walks the stream in awkward groups of three
because Vola emits name rows with no corresponding time. Its own comment calls this "pretty
awkward".

### Other Vola specifics

- Run 2 is only fetched for SL/GS (`src/scrapers.py:313-318`); speed races are single-run.
- `r2_time = total - r1_time` (`src/scrapers.py:283`) — the feed gives cumulative totals.
- Run ranks are computed only for tech races (`src/scrapers.py:289-306`).
- DNS is skipped by substring match on the time value (`src/scrapers.py:259`); DNF falls out via
  `time_to_float` returning `9999`.
- **Provides no fiscodes**, which forces the full-table scan described below.
- A TODO block at `src/scrapers.py:31-36` documents the correct approach that was never
  implemented: the page's own JS stores the startlist at `response["4"]` and results at
  `response["0"]`. If this scraper needs real work rather than patching, start there.
- `initialize_starting_racers` carries two more TODOs (`src/scrapers.py:209-210`, `:215-216`):
  DNS handling, and capturing start order so `B` could be computed from the seed. The second is
  the same gap noted in [points-calculation](points-calculation.md).

---

## Scraper: FIS livetiming

`fis_livetiming_scraper`, `src/scrapers.py:420-669`. The most reliable, and the only one that
supplies fiscodes.

Codex extraction: regex `lv-al(\d+)` against a fis-ski URL, else the raw string
(`src/scrapers.py:422-426`).

Two-step fetch:

1. `https://live.fis-ski.com/general/serverListFull.xml?t=<ms>` → pick `parsed['servers'][0][0]`
   (`src/scrapers.py:443-449`)
2. `{server}/al<CODEX>/main.xml?t=<ms>` (`src/scrapers.py:453`). A 404 raises
   `UserFacingException("Race is not live or not found", 404)`.

### The payload is PHP-serialized, despite the `.xml` name

`<lt>` tags are stripped by regex (`src/scrapers.py:429-430`), then parsed with
`phpserialize.loads(..., decode_strings=True)`.

**PHP serialization encodes byte lengths.** Multi-byte characters therefore break the parse. The
workaround (`remove_german_chars`, `src/scrapers.py:434-441`) substitutes exactly nine characters:

```
ä ö ü ß  →  z        Ä Ö Ü  →  Z        é → z    É → Z
```

**This is incomplete by design and will break on other alphabets** — Nordic `ø`/`å`, Polish `ł`,
Czech `ř`, Spanish `ñ`. If a FIS race throws a phpserialize length error, an unhandled character in
a racer's name is the near-certain cause; add it to the map. The payload is then re-encoded as
`iso-8859-1` before parsing (`src/scrapers.py:464`), which is what makes `é` survive at all.

Note `phpserialize` (v1.3, last released 2016, sdist-only) is unmaintained. It is pure Python and
works fine on 3.13/3.14, but it is ~50 lines to vendor if it ever breaks.

### Structures used

| key | meaning |
|---|---|
| `racers` | fiscode → `(fiscode, last, first)`, becomes the `starters` dict (`src/scrapers.py:500-507`) |
| `startlist[0][0][run]` | start order per run |
| `result[0][run]` | results per run |
| `racedef[0][run]` | column definitions, used to find the finish column |

### `finish_location` inference

The index within a result row holding the finish time is not declared — it is found by scanning
`racedef` for the substring `'finish'` (`src/scrapers.py:550-564`). There is an explicitly
self-deprecating branch ("hacky bug fix ... shitty code for now") for when run 2 hasn't started
yet, which falls back to `racedef[0][0]`.

Result rows are then skipped if `len(result) != finish_location + 1` (`src/scrapers.py:576`) — with
split timing, a DNF shows intervals but no finish, and this is how they're detected.

### Accumulated bug workarounds

Each of these is a real observed FIS behavior, not defensive padding:

- Results sometimes live at `result[0][1]` instead of `result[0][0]` (`src/scrapers.py:568-569`).
- Times can carry a suffix: `85530:p2`, `85530:c`. Split on `:` and keep the first part
  (`src/scrapers.py:580`, `:606`, `:629`).
- Stray fiscodes appear that aren't in `starters`; skipped (`src/scrapers.py:585`).
- `time == 0` means DNF, not a zero-second run; those racers are dropped
  (`src/scrapers.py:665-666`).
- Third-run DNFs were being missed, patched at `src/scrapers.py:660-661`.
- DNS removal is two-pronged (`src/scrapers.py:510-525`): racers flagged `'dns'` **and** racers
  simply absent from the run-1 startlist, because FIS sometimes just omits them.
- The per-bib `finished` flag comes from scanning the startlist row for the substring `'finish'`
  (`construct_start_order_to_fiscode_map`, `src/scrapers.py:466-478`).

Times are milliseconds ÷ 1000, rounded to 2dp.

### Three-run indoor slaloms

Supported by a third block at `src/scrapers.py:616-638` that is an acknowledged copy-paste of the
run-2 block. Surfaces as `hasThirdRun` in the response.

### Startlist-only mode

If there is a startlist but no results, `create_startlist` (`src/scrapers.py:480-491`) sets
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
`generate_ussa_competitor_name` (`src/scrapers.py:202-205`) and again in
`get-points-list/src/ussa_points_download.py`.

So `SMITH, John` and `john Sm-itH` match — and so does any anagram. Collisions are possible by
construction. The human-readable name is stashed in `competitor.temp_full_name` and restored for
output at `src/app.py:255-257`.

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
| layers | none declared | none attached (`Layers: null`) — `pandas-layer/` is unused |
| DynamoDB access | implicit SAM role, no policies | policies attached by hand |
| CORS | **absent entirely** | configured on the Function URL |

Timeout 120s, MemorySize 2048, python3.10, x86_64 (`template.yaml:7-12`). Deployed CodeSize
30,863,104. Stack `get-livetiming-info`, region `us-east-2`, account `828841719603`.
`samconfig.toml` carries a stale global `stack_name = "selenium-get-fis-points-list"` that the
deploy section overrides.

A clean `sam deploy` into a fresh account would not produce a working system.

---

## Fragility checklist

When something breaks, in rough order of likelihood:

1. **Vola URL shape** — `race_idx` extraction (`src/scrapers.py:38-40`).
2. **A non-German accented character in a FIS racer's name** — extend `remove_german_chars`
   (`src/scrapers.py:434-441`).
3. **FIS restyles or reorders `racedef`** — `finish_location` inference breaks
   (`src/scrapers.py:550-564`).
4. **Vola renames a column title** — the `"order"`/`"name"`/`"time"` substring scan finds nothing
   and the race comes back empty.
5. **A name that won't match** — add to `NAME_ERROR_FISCODES` (`src/utils.py:16-22`), minding the
   key-mismatch bug above.
6. **Timeout on a large Vola field** — the O(n²) recompute at `src/utils.py:109`.

## Seasonal maintenance

- **`score2027`** is hardcoded to one season in two places that must change together: the response
  key at `src/app.py:274`, and the column header `<th>2027 Score</th>` at `website/app.js:84`
  (with reads at `website/app.js:244-248`). Deriving it from `race.adder` and the current date
  would remove the chore.
- **F-factors and event maximums** (`src/app.py:10-23`, `:34-45`) are FIS rulebook constants.
  Nothing in the code records which season's rules they encode. See
  [points-calculation](points-calculation.md) — ask Matt, don't guess.
- **Penalty/adder pairs** at `index.html:37-43` and the 33-entry `raceCategoryToPenalty` map at
  `website/app.js:275-306` must stay in sync with each other and with FIS categories.
