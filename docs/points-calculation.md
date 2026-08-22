# Points calculation

How a race score is produced. All of this lives in `get-livetiming-info/src/app.py`.

See also: [get-livetiming-info](get-livetiming-info.md) · [architecture](architecture.md) ·
[get-points-list](get-points-list.md) · [testing](testing.md) · [operations](operations.md)

---

## Before changing anything here

**Matt is the domain expert; you are not.** Every constant on this page is a FIS rulebook value.
FIS revises the alpine points rules every few years, and nothing in the code records which season's
rules the current numbers encode. There is also **no test coverage** for any of this
([testing](testing.md)).

If a number looks wrong, that is a question for Matt with a pointer to the current FIS literature —
not something to infer from a formula, from what other implementations do, or from what looks
internally consistent. A "correction" here silently changes results for every user of the live
site, and a wrong score is indistinguishable from a right one in the logs.

The safe kinds of change: fixing a crash, adding a guard, renaming, extracting a constant.
The unsafe kind: adjusting a value or a rule because it seems off.

---

## The shape of it

```
score = race_points + penalty
```

where `race_points` measures how far behind the winner you finished, and `penalty` measures how
weak the field was. A fast time in a strong field gives a low (good) score.

```
race_points = ((your_time / winning_time) - 1) * F
penalty     = max((A + B - C) / 10, min_penalty)
```

`min_penalty` comes from the race level the user picked in the form; see the contract section of
[get-livetiming-info](get-livetiming-info.md).

---

## F-factors

`event_multiplier`, set in `Race.__init__` (`src/app.py:34-45`):

| event | F | `is_tech_race` |
|---|---|---|
| `SLpoints` | 730 | True |
| `GSpoints` | 1010 | True |
| `SGpoints` | 1190 | False |
| `DHpoints` | 1250 | False |
| `ACpoints` | 1360 | **True — see below** |

`is_tech_race` defaults to `True` at `src/app.py:33` and is only set `False` inside the SG and DH
branches. **`ACpoints` therefore keeps `is_tech_race = True`**, which looks unintended — alpine
combined is not a tech race. It has no live effect because `ACpoints` is not offered in the form
(`index.html:48-52`), but the branch exists and would be wrong if it were ever exposed.
`is_tech_race` controls two-run handling and run-rank computation in the scrapers.

## Race points

`get_race_points` (`src/app.py:205-207`):

```python
race_points = ((competitor.time / race.winning_time) - 1) * race.event_multiplier
return round(race_points, 2)
```

Rounded to 2dp. `winning_time` is maintained incrementally by the scrapers as the minimum finishing
time seen, starting from the sentinel `9999` (`src/app.py:49`).

## Penalty

`calculate_penalty` (`src/app.py:113-119`):

```python
A, C = self.get_A_and_C()
B = self.get_B(starting_racers_points)
penalty = max(((A+B-C)/10), self.min_penalty)
self.penalty = round(penalty, 2)
self.next_year_penalty = round(max(((A+B-C)/10) + self.adder, self.min_penalty), 2)
```

Note where `adder` lands in `next_year_penalty`: **inside** the `max`, added to the computed value
before the floor is applied — not added afterwards. So a race that bottoms out at `min_penalty`
gets the same value for both, rather than `min_penalty + adder`.

`next_year_penalty` feeds `next_year_score` (`src/app.py:195`), surfaced as the `score2027` response
field. That key name is hardcoded per season — see the seasonal notes in
[get-livetiming-info](get-livetiming-info.md).

---

## A, B, and C

### A and C — `get_A_and_C`, `src/app.py:121-168`

1. Sort all competitors by time (`src/app.py:122`, `time_sort`). DNFs sort last at `9999`.
2. Take the first 10, **skipping any with `time == 9999`** (`src/app.py:124-127`). Note this uses
   `continue`, so a DNF inside the first ten shrinks the group rather than pulling in an
   eleventh finisher.
3. **Tie for 10th** (`src/app.py:131-135`): everyone tied on time with the 10th-place racer is also
   included, per FIS rules. Guarded against `9999` on both sides. This walks forward from index 10
   without a bounds check — safe only because the loop condition fails at the end of a sorted list
   with distinct times, but it is a latent `IndexError` if every racer shares a time.
4. Re-sort that group by points (`src/app.py:138`, `point_sort`).
5. `A` = sum of the 5 best points in the group. `C` = sum of their **race points**
   (`src/app.py:150-162`).

`point_sort` (`src/app.py:202-203`) is `(fis_points, -time)` — **on a points tie, the slower racer
sorts first**, per FIS rules. The negation is the whole trick; don't "simplify" it.

### B — `get_B`, `src/app.py:170-186`

Sum of the 5 lowest points among **all starters**. The starter list is built at
`src/app.py:102-107`, excluding anyone whose points came back as `-1`.

```python
def get_B(self, starting_racers_points):
    #TODO: get top 5 out of seed
    # make sure to check DNS - time == 9999
```

**This TODO is live.** Per the rules, `B` should be the best 5 in the *seed*, not the best 5 among
everyone who started. The scrapers do not currently capture start order for Vola
(a matching TODO sits at `src/scrapers.py:215-216`), so the information needed isn't there yet.
This is the most likely source of a systematic discrepancy against hand-calculated results —
check it first if Matt reports scores that are close but consistently off.

---

## Event maximums

A cap applied to any individual racer's points inside both `A` and `B`.

| event | FIS (`src/app.py:10-16`) | USSA (`src/app.py:17-23`) |
|---|---|---|
| `SLpoints` | 165 | 360 |
| `GSpoints` | 220 | 530 |
| `SGpoints` | 270 | 660 |
| `DHpoints` | 330 | 820 |
| `ACpoints` | 270 | 660 |

Selected by `race.is_fis_race`. Applied at `src/app.py:155-158` (in `A`) and `src/app.py:179-182`
(in `B`), in both cases as: if the racer's points are `>= maximum`, **or** the racer's points are
exactly `1000`, substitute the maximum.

Each of those conditions is written as two branches, one per table, and each branch repeats the
`or points == 1000` test — so the `1000` sentinel is handled identically in both. Worth knowing if
you refactor: the two branches are not symmetric in a subtle way, since the first tests
`self.is_fis_race and ...` and the second `not self.is_fis_race and ...`, meaning a `1000` value
still requires the matching race type to land in its branch.

---

## Sentinels

Three magic numbers flow through the calculation. Knowing which is which saves real time:

| value | meaning | set at |
|---|---|---|
| `1000` | points **not found** in the database | `Competitor.__init__`, `src/scrapers.py:19` |
| `999.99` | racer is in the database but **has no points yet** | `src/utils.py:136-139` and siblings |
| `-1` | stored in DynamoDB to mean unscored | written by [get-points-list](get-points-list.md) |
| `9999` | time sentinel: DNF, DNS, or DSQ | `src/scrapers.py:18`, `time_to_float` |
| `-1` (score) | did not finish — filtered from output | `src/app.py:192` |

`1000` is the initial value on every `Competitor`, so "not found" is really "nothing ever
overwrote it". Those names are collected into the `notFound` response field (`src/app.py:262-263`)
and shown as a warning above the results table.

### The USSA wrinkle

The `-1 → 999.99` conversion in `src/utils.py` exists because FIS rows store `-1` for unscored
athletes. **USSA CSVs already contain `999.99` directly**, so for USSA races the conversion never
fires — the value arrives pre-set.

The consequence is downstream, at the `counter999` override below: it triggers far more readily on
USSA races than on FIS ones, because unscored USSA athletes are common early in a season and every
one of them counts toward the threshold. See [get-points-list](get-points-list.md) for where the
`999.99` originates.

---

## Edge cases

### Fewer than 5 finishers

`src/app.py:146-147`. Pads `A` with one event maximum per missing finisher:

```python
if len(top_ten_finishers) < 5:
    A += (5 - len(top_ten_finishers)) * (FIS_EVENT_MAXIMUMS[...] if is_fis_race else USSA_EVENT_MAXIMUMS[...])
```

### Three or more racers at 999.99 in the top 5

`src/app.py:149-152`, `:164-166`. Counts how many of the best-5-by-points are unscored, and if 3 or
more:

```python
if counter999 >= 3 and self.is_fis_race:
    self.min_penalty = FIS_EVENT_MAXIMUMS[self.event] * 2
```

**This mutates `self.min_penalty` on the `Race` object**, so it changes the floor used by the
`max()` in `calculate_penalty` for both `penalty` and `next_year_penalty`. Note it is gated on
`is_fis_race` and only ever reads `FIS_EVENT_MAXIMUMS` — a USSA race never gets this override even
though, as noted above, USSA races are the ones most likely to have three unscored racers up front.
Whether that gating is intended is a question for Matt.

### DNF, DNS, DSQ

Normalized to a single representation everywhere: `time = 9999`.

- Set by `time_to_float` (`src/scrapers.py:671-685`) when the time is empty, in
  `TIMES_AS_LETTERS` (`{"DNF","DNS","DSQ","DQ","Did Not Finish","Did Not Start","Disqualified"}`,
  `src/scrapers.py:7`), or doesn't start with a digit or colon.
- Excluded from the top-10 group (`src/app.py:125-126`).
- Given `score = -1` in `assign_scores` (`src/app.py:191-193`) and **no** `next_year_score`, which
  is why that attribute keeps its `-1` initial value.
- Filtered out of the response at `src/app.py:266`.

Each scraper also has provider-specific DNF detection before this point — see
[get-livetiming-info](get-livetiming-info.md).

---

## Projected first-run scores

`first_run_projected_scores_adjustment` (`src/app.py:67-86`). This is the site's headline feature:
usable results while a race is still running.

Conditions, in order:

1. **SL or GS only** (`src/app.py:69-71`). Any other event sets `are_scores_projections = False`
   and returns.
2. **No second-run times anywhere** (`src/app.py:74-77`) — a single competitor with an `r2_time`
   aborts the whole adjustment.

Then for every competitor with a first-run time that isn't a DNF, it **doubles the first-run time**
to synthesize a total and recomputes `winning_time` (`src/app.py:85-86`). Everything downstream —
race points, A, B, C, penalty — runs on those doubled times unchanged.

Surfaces as `areScoresProjections: true`, which the frontend uses to switch the results table to a
"Projected Total" column.

Called from `get_points` at `src/app.py:100`, before the penalty calculation and after the
startlist-only early return.

---

## Order of operations

`Race.get_points`, `src/app.py:88-110`:

```
1. connect_to_database        (skipped for live-timing, which carries its own points)
2. scrape_results             (provider dispatch + points lookup)
3. if is_startlist_only       -> sort by bib, return with no scoring
4. first_run_projected_scores_adjustment
5. build starting_racers_points, excluding fis_points == -1
6. calculate_penalty          -> get_A_and_C, get_B
7. assign_scores
```

Step 5 filters on `-1`, which is the *database* sentinel rather than the in-memory one — in-memory,
unscored racers are `999.99` and not-found racers are `1000`. So in practice this filter rarely
removes anything, and both sentinels flow into `B` where the event-maximum substitution handles
them.

---

## Known issues, collected

| issue | location | note |
|---|---|---|
| `B` uses all starters, not the seed | `src/app.py:171` | live TODO; needs start order from the scrapers |
| `is_tech_race` stays `True` for `ACpoints` | `src/app.py:44-45` | latent; AC not exposed in the form |
| `counter999` override is FIS-only | `src/app.py:165` | but USSA races are likelier to hit the condition |
| duplicate `place` key | `src/app.py:271-272` | first is dead code |
| no tests at all | — | see [testing](testing.md) |

Two `IndexError`s that used to sit in this table were **fixed 2026-08-21** (commit `040816e`): the
unbounded tie-for-10th walk (`src/app.py:133`, now length-guarded) and `hasThirdRun` reading
`output[0]` on an empty field (`src/app.py:315`, now `bool(output) and ...`). Both reached users as
a generic 500. Details in [get-livetiming-info](get-livetiming-info.md#fixed-crashes-worth-knowing-about).
