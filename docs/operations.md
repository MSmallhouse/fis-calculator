# Operations

AWS reference and runbook. See [README.md](README.md) for the doc index, [architecture.md](architecture.md) for how the pieces fit.

---

## Traps — read before touching anything

1. **The `AWS/Lambda` `Errors` metric is always `0` for get-points-list.** Both download modules wrap everything in a bare `except Exception` that only logs, so the handler returns normally and Lambda records a success. A totally broken feed looks identical to a healthy run. Never use `Errors`, `Throttles`, or the scheduler DLQ to judge health.
2. **The nightly trigger is an EventBridge _Scheduler_ schedule, not an EventBridge _rule_.** Look under `aws scheduler`, not `aws events` — the latter returns nothing of ours, and `aws events list-rule-names-by-target` returns empty for the function, which reads as "no trigger exists". (A zero-target decoy rule named `get-points-list-daily-run` used to sit there and cost real debugging time; deleted 2026-08-21.)
3. **A schedule with an expired `EndDate` stays `State: ENABLED` while silently never firing.** This caused a 77-day outage (Jun 5 – Aug 21 2026) with no alert of any kind.
4. **`UpdateSchedule` is a full PUT.** Unspecified optional fields are reset to system defaults — you will silently lose the DLQ, retry policy, timezone, and description. Always `get-schedule` first and re-supply everything. It also **refuses a backdated `StartDate`** (`cannot be earlier than 5 minutes ago`), so you cannot round-trip an old one; omit it instead.
5. **The templates do not describe what is deployed.** See [IaC drift](#iac-drift). `sam deploy` is not a safe no-op.

---

## Account and resources

| | |
|---|---|
| Account | `828841719603` |
| Region | `us-east-2` |
| CLI identity | `sam-deploy-user` (default profile) |

Physical names differ from the logical IDs in the templates:

| Logical (template) | Physical (deployed) |
|---|---|
| `GetPointsListFunction` | `get-points-list-GetPointsListFunction-D0YVo1592Mhc` |
| `getLivetimingInfoFunction` | `get-livetiming-info-getLivetimingInfoFunction-kBjRyLq6345M` |

```bash
FN=get-points-list-GetPointsListFunction-D0YVo1592Mhc
LT=get-livetiming-info-getLivetimingInfoFunction-kBjRyLq6345M
```

### Full inventory (post-cleanup, 2026-08-21)

A large cleanup on 2026-08-21 removed everything that was not load-bearing. If you find
something in the account that is **not** on this list, it is either new or was missed:

| | |
|---|---|
| Stacks | `get-points-list`, `get-livetiming-info`, `fis-calculator-alerts`, `aws-sam-cli-managed-default` (owns the deploy bucket — **never delete**) |
| Lambdas | the two above, plus `fis-calculator-alerts-ErrorNotifierFunction-*` and `-NameMatchDigestFunction-*` |
| REST APIs | `i22c6hlx33` (`get-livetiming-info`) only — stack-owned, don't hand-delete |
| Alarms | `Get Points List error in logs alarm`, `get-points-list-did-not-run` |
| Metric filters | `get-points-list-error-log-message` only |
| Schedules | `get-fis-points-nightly-run`, `fis-calculator-name-match-digest` |
| EventBridge *rules* | **none at all** — `aws events list-rules` returns `[]`. The ApplicationInsights managed rules went with the `hello-world` stack. |
| Lambda layers | none |
| ECR repos | none |
| RDS proxies | none |
| DynamoDB | `points_list_dynamo_db`, `ussa_points_list` — both `PAY_PER_REQUEST` |
| SNS | `Fis_Points_Errors_Topic`, `Fis_Points_Errors_Topic_bc_email` |

Deleted in that pass: 8 abandoned stacks, 4 stale public REST APIs, 2 orphaned python3.9
layers, 3 ECR repos, an orphaned RDS proxy, the zero-target EventBridge rule, 2 dead
alarms, 2 stale metric filters, and 4 retired log groups (~450 MB).

### Log groups

Four, one per live function, **all with 90-day retention** (set 2026-08-21; they previously
grew forever). Retired groups from prior deployments have been deleted — historically these
were a trap, since querying the wrong one returns nothing and reads as "no activity".

---

## The nightly schedule

```bash
aws scheduler get-schedule --name get-fis-points-nightly-run
```

Current state (as of Aug 2026):

| Field | Value |
|---|---|
| `ScheduleExpression` | `cron(10 1 * * ? *)` |
| `ScheduleExpressionTimezone` | `America/New_York` |
| `StartDate` / `EndDate` | none — deliberately |
| `FlexibleTimeWindow` | `FLEXIBLE`, 15 min |
| Target | the get-points-list function |
| DLQ | `arn:aws:sqs:us-east-2:828841719603:fis-points-queue` |
| Retry | 1 attempt, max event age 86400s |

It was previously `rate(24 hours)` with a `StartDate`. Dropping the `StartDate` (forced — see trap 4) would have re-anchored a `rate()` expression to the moment of the update, turning a nightly job into an afternoon one, hence the cron.

Editing it — every field must be re-supplied:

```bash
aws scheduler update-schedule \
  --name get-fis-points-nightly-run \
  --group-name default \
  --state ENABLED \
  --action-after-completion NONE \
  --schedule-expression 'cron(10 1 * * ? *)' \
  --schedule-expression-timezone 'America/New_York' \
  --flexible-time-window 'Mode=FLEXIBLE,MaximumWindowInMinutes=15' \
  --description "..." \
  --target '{
    "Arn":"arn:aws:lambda:us-east-2:828841719603:function:get-points-list-GetPointsListFunction-D0YVo1592Mhc",
    "RoleArn":"arn:aws:iam::828841719603:role/service-role/Amazon_EventBridge_Scheduler_get-points-list",
    "DeadLetterConfig":{"Arn":"arn:aws:sqs:us-east-2:828841719603:fis-points-queue"},
    "RetryPolicy":{"MaximumEventAgeInSeconds":86400,"MaximumRetryAttempts":1}
  }'
```

The DLQ stays empty even during total failure, because the function never returns an error. It is not a health signal.

---

## Monitoring

Health is two independent questions, and the standard metrics answer neither:

1. **Did it run at all?** → `Invocations` count, or the most recent log stream date.
2. **Did the run log any `ERROR`?** → filter the logs. Not the `Errors` metric.

```bash
# 1. did it run? one datapoint per day
aws cloudwatch get-metric-statistics --namespace AWS/Lambda --metric-name Invocations \
  --dimensions Name=FunctionName,Value=$FN \
  --start-time 2026-05-13T00:00:00Z --end-time 2026-08-21T23:59:59Z \
  --period 86400 --statistics Sum \
  --query 'sort_by(Datapoints,&Timestamp)[].[Timestamp,Sum]' --output text

# most recent activity
aws logs describe-log-streams --log-group-name /aws/lambda/$FN \
  --order-by LastEventTime --descending --max-items 5 \
  --query 'logStreams[].{Stream:logStreamName,Last:lastEventTimestamp}'

# 2. the real health signal (--start-time is epoch MILLISECONDS)
aws logs filter-log-events --log-group-name /aws/lambda/$FN \
  --start-time 1779000000000 --filter-pattern 'ERROR' --max-items 40 \
  --query 'events[].[message]' --output text
```

A healthy run logs, in order: `Checking fis points` → `download_url: ...` → `SUCCESS: Connection to DynamoDB Table succeeded` → `UPDATES: N rows in database to be updated` → `Checking ussa points` → `USSA: season NN, list NN, valid since YYYY-MM-DD` → `USSA: list published ... (N days ago)` → `UPDATES: N rows`. `UPDATES: 0 rows` is a normal answer, not a failure — it means the diff found nothing to change.

### Alarms

All route to SNS. `Fis_Points_Errors_Topic` → Matt's gmail; `Fis_Points_Errors_Topic_bc_email` → a bc.edu address.

Two alarms, both live and both functional. Anything else you remember is gone.

| Alarm | Watches | Notes |
|---|---|---|
| `Get Points List error in logs alarm` | metric filter `get-points-list-error-log-message`, pattern `ERROR`, on the live get-points-list log group → custom metric ≥ 1 over 300s | Confirmed firing Aug 21 2026. `INSUFFICIENT_DATA` is its normal resting state — the metric only emits on a match. |
| `get-points-list-did-not-run` | `Invocations < 1` over 86400s, `TreatMissingData: breaching` | Added Aug 2026 so *silence* alarms instead of hiding. This is the gap that let the 77-day outage pass unnoticed. |

Two dead alarms were deleted on 2026-08-21 and should not be recreated:
`get_points_list_error_alarm` (on `AWS/Lambda` `Errors`, which can never fire while
exceptions are swallowed — see trap 1) and `get-livetiming-info-error` (whose metric filter
pointed at a **retired** log group, so it watched something nothing wrote to; superseded by
the alerts stack below).

**Neither remaining alarm can catch a _quiet wrong answer_** — a successful run that loads the wrong data. Two such bugs shipped undetected for months: a not-yet-valid points list, and a headerless CSV eating one athlete per file. Both produced clean, green runs. That failure class is what [testing.md](testing.md) exists for; no amount of alarming will find it.

---

## Alerting — the `fis-calculator-alerts` stack

Added 21 Aug 2026. SAM stack in [`alerts/`](../alerts), python3.13. **Fully described
by its template** — unlike the other two stacks, so keep it that way.

Two paths, because the two failures have different shapes:

| failure | delivery | mechanism |
|---|---|---|
| unhandled calculator error | immediate email | Logs subscription filter → `ErrorNotifierFunction` → SNS |
| racer points not matched | daily digest, 2:15am ET | `NameMatchDigestFunction` runs a Logs Insights query → SNS |

The digest is scheduled 15 minutes after the nightly points refresh so it reflects
whatever that ingest just fixed. It suppresses the email entirely at zero records.

**Do not alarm on bare `ERROR` in the calculator log group.** Measured over 14 days:
1,514 `ERROR` events, of which **1,181 were routine "points not found"** — a normal,
user-visible condition already surfaced to the user as `notFound`. `USER RAISED ERROR`
(`get-livetiming-info/src/app.py:314`) is likewise an expected 4xx and is deliberately
excluded from the subscription filter. An `ERROR` alarm here would fire constantly and
train you to ignore it.

Volume is why the digest exists rather than per-event mail: the calculator runs
**1,046–5,501 invocations/day in peak season**, 13–403/day off-season.

The two lambdas read structured lines that `app.py` emits — `NAME_MATCH_MISS {json}`
once per affected request (params, provider, missed names, counts, field size) and
`UNHANDLED ERROR` with params. If you change those markers or that JSON shape, update
[`alerts/src/digest.py`](../alerts/src/digest.py) and
[`alerts/src/error_notifier.py`](../alerts/src/error_notifier.py) with them.

See [get-livetiming-info.md](get-livetiming-info.md) for what a name-match miss actually
is and why it happens.

## Deploy runbook — get-points-list

The function **bundles its dependencies** (no layers), on `python3.14`. Build inside the matching Lambda base image so the compiled wheels are `cp314` + `manylinux` `x86_64`.

```bash
cd get-points-list
OUT=/tmp/gpl-build && rm -rf $OUT && mkdir -p $OUT

docker run --rm --platform linux/amd64 -v "$PWD":/work -v "$OUT":/out -w /work \
  --entrypoint /bin/sh public.ecr.aws/lambda/python:3.14 -c '
set -e
pip install -r src/requirements.txt -t /out > /tmp/pip.log 2>&1 || { tail -20 /tmp/pip.log; exit 1; }
grep "^Successfully installed" /tmp/pip.log
cp src/app.py src/fis_points_download.py src/ussa_points_download.py /out/
find /out -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
cd /out && python3 -c "import app, pandas, pypdf; print(\"import OK\", pandas.__version__)"
'

cd $OUT && zip -qr /tmp/get-points-list.zip .
```

**Do not use `pip install --quiet` here.** It once hid a failed pandas/numpy install and produced a silently incomplete 8 MB package that only failed at runtime. Always capture the log and assert on `Successfully installed`.

The zip is ~46 MB, close to the 50 MB direct-upload limit, so go through S3:

```bash
BUCKET=aws-sam-cli-managed-default-samclisourcebucket-5njxzzod1l5l
KEY=get-points-list/deploy-$(date +%Y-%m-%d).zip

# record the rollback handle FIRST
aws lambda get-function-configuration --function-name $FN \
  --query '{Runtime:Runtime,CodeSha256:CodeSha256,CodeSize:CodeSize}'

aws s3 cp /tmp/get-points-list.zip s3://$BUCKET/$KEY
aws lambda update-function-code --function-name $FN --s3-bucket $BUCKET --s3-key $KEY
aws lambda wait function-updated --function-name $FN
```

**`update-function-code` does not change the runtime.** Runtime, memory, timeout, and env vars go through a separate call, after the code update settles:

```bash
aws lambda update-function-configuration --function-name $FN --runtime python3.14
aws lambda wait function-updated --function-name $FN
aws lambda get-function-configuration --function-name $FN \
  --query '{Runtime:Runtime,State:State,LastUpdate:LastUpdateStatus,Sha:CodeSha256}'
```

Verify with an async invoke — `update_dynamodb` diffs before writing, so a redundant run is harmless:

```bash
aws lambda invoke --function-name $FN --invocation-type Event \
  --payload '{"source":"post-deploy-verify"}' --cli-binary-format raw-in-base64-out /tmp/out.json
```

Then read the logs as above. A full FIS refresh of ~8,400 rows takes ~120s against a 900s timeout; `UPDATES: 0 rows` on both halves is the expected result if a run already happened recently.

Two caveats on that invoke. It is **not** quite the scheduler's path — the scheduler uses its own IAM role, so if you have changed anything about permissions, confirm that separately with `aws iam simulate-principal-policy --policy-source-arn <scheduler role> --action-names lambda:InvokeFunction --resource-arns <fn arn>`, or by creating a throwaway one-off `at()` schedule with `ActionAfterCompletion: DELETE`. And with `ReservedConcurrentExecutions: 1`, a manual invoke launched while the nightly run is in flight will be **throttled**, not queued — that is intended.

**Prefer this over `sam deploy`.** A CloudFormation update is a live-fire test of the drift below; `update-function-code` touches only the code and leaves the hand-configured role, schedule, and tables alone. Rollback is re-uploading the prior artifact and flipping the runtime back.

---

## Changing a template without `sam deploy`

`sam deploy` is unusable here: SAM CLI 1.142.1 rejects `python3.14`
(`'python3.14' runtime is not supported`), and even on a newer CLI a local build on
an arm64 Mac produces macOS wheels. Drive CloudFormation directly instead, pointing
`CodeUri` at the S3 artifact **already running** so the code and runtime changes are
no-ops and the update is confined to what you meant to change:

```bash
# template.yaml edited as you want it; then a copy for the deploy:
sed 's|CodeUri: src/|CodeUri: s3://<bucket>/<key-already-deployed>.zip|' template.yaml > /tmp/cfn.yaml

aws cloudformation create-change-set --stack-name <stack> \
  --change-set-name <name> --capabilities CAPABILITY_IAM --template-body file:///tmp/cfn.yaml
aws cloudformation wait change-set-create-complete --stack-name <stack> --change-set-name <name>

# READ THIS before executing - it lists exactly what will be added/removed/replaced
aws cloudformation describe-change-set --stack-name <stack> --change-set-name <name> \
  --query 'Changes[].ResourceChange.{Action:Action,Logical:LogicalResourceId,Replacement:Replacement}' --output table

aws cloudformation execute-change-set --stack-name <stack> --change-set-name <name>
aws cloudformation wait stack-update-complete --stack-name <stack>
```

Used this way on 2026-08-21 to delete the unused API Gateway. Hand-added inline
policies on a CFN-managed IAM role survive an update that does not touch the role —
verified, `dynamo_db_permissions` and `ussa_points_list_policy` were both intact
afterwards. This *reduces* drift instead of adding to it.

## IaC drift

The two original `template.yaml` files are partial documentation, not truth — those stacks were grown by hand in the console. (`fis-calculator-alerts` is the exception: it is fully described by its template. Keep it that way.)

Still missing from IaC:

- **The nightly schedule.** get-points-list's template declares no event source at all; the EventBridge Scheduler schedule lives entirely outside IaC.
- **The Function URL** that the website actually calls. get-livetiming-info's template declares an API Gateway event instead (`i22c6hlx33`), which is vestigial — nothing routes through it.
- **Both DynamoDB tables**, and **the IAM permissions to reach them.** get-points-list's template has no `Policies` block at all; the role carries two hand-added inline policies, `dynamo_db_permissions` and `ussa_points_list_policy`. Verified still present after the 2026-08-21 change-set update — a CFN update that does not touch the role leaves them alone.
- **CORS**, configured on the Function URL (`AllowOrigins: *`), absent from the template.

A clean `sam deploy` into a fresh account would produce a non-working system.

**Fixed since:** `get-points-list/template.yaml` now matches reality on runtime (`python3.14`), `ReservedConcurrentExecutions: 1`, and the absence of an event source. There is **no pandas layer** — neither function has ever had one (`Layers: null` on both); dependencies are bundled in the zips. The repo's `get-livetiming-info/pandas-layer/` directory is 123 MB of dead weight referenced by nothing.

Also stale in-repo: `template-copy.yaml` and `template.backup.yaml` (python3.9 / Docker-image era), and `get-points-list/src/Dockerfile` (still `python:3.10`, referenced only by the gitignored backup template).

---

## Cost and abuse exposure

Account concurrency limit is **400** (399 unreserved, after the cap below). DynamoDB tables are both `PAY_PER_REQUEST`.

**Almost none of the AWS bill is this project.** Checked via Cost Explorer 2026-08-21 — the whole account runs ~$12/month, of which ~$7.74 is a `t3.micro` (`i-0923ce83c9a4b7047`, "arb-scanner") running in **us-east-1**, unrelated to fis-calculator, plus ~$3.72 for its public IPv4. Lambda, DynamoDB and CloudWatch for this project round to zero. Don't go hunting for savings here; the lever that matters is bounding *worst case*, not trimming baseline.

- **`get-livetiming-info` Function URL** — `https://hsa35mz4zsbu6nqwlb5jvkk4o40jruqd.lambda-url.us-east-2.on.aws/`, `AuthType: NONE`, `CORS: *`. Hardcoded in `website/app.js` and served on the live site, so it is public by design. Nothing to hide; it is also the entire remaining abuse surface.
- **`get-livetiming-info` is deliberately left uncapped.** Matt's call, and the right one: it is user-facing, and throttling a real race is worse than the cost exposure. Peak observed concurrency is **20** (Feb 2026) against the 400 limit; duration p50 2.5 ms (the preload warm-up pings), p99 12 s. **Do not propose capping it again without a new reason.**
- **`get-points-list` is capped at `ReservedConcurrentExecutions: 1`.** Its only trigger is the nightly schedule, so anything concurrent is a bug or abuse; a second invocation is visibly throttled rather than quietly running the ingest twice over the same tables. This is a duplicate-run guard, not a cost guard — that function has no public trigger at all any more.
- ~~get-points-list's unauthenticated API Gateway trigger~~ — **removed 2026-08-21** (commit `77f97bf`). Zero requests in 30 days while offering a free path to run the expensive function. It now has **no resource policy at all**; the scheduler invokes through its own IAM role (verified by `simulate-principal-policy` and by a real one-off scheduled invocation).
- ~~Four stale API Gateways~~, ~~an orphaned RDS proxy~~, ~~two python3.9 layers~~, ~~three ECR repos~~ — all removed 2026-08-21. The RDS proxy was **not** billing, despite appearances: Cost Explorer showed $0 RDS spend for the period. It was tidiness, not money.
- **Log retention is now 90 days** on all four live groups.

---

### The budget does not stop anything

There is a $15/month AWS Budget with alerts at 85% actual, 100% actual and 100%
forecasted, but **no budget actions** — and AWS has no account-level spend cap for
standard accounts. It is a smoke detector, not a sprinkler: spend continues past the
limit indefinitely and you get an email.

**Adding a budget action is deliberately rejected.** A budget action is the one mechanism
that *would* stop the lambdas at a threshold, i.e. take the live site down over a billing
number. Don't propose it.

Which means the only real control on runaway spend is the concurrency cap — and that is
only on `get-points-list`, which has no public trigger anyway. The calculator is
knowingly unbounded. Note also that baseline forecast (~$12) already sits close to the
$15 limit, mostly from the unrelated EC2 instance, so the 85% alert is prone to firing on
noise rather than on anything meaningful.

### Deleting a SAM image-based stack

CloudFormation cannot delete a non-empty ECR repository, so the companion stack ends
in `DELETE_FAILED`. Clear the images first, then re-issue the delete:

```bash
R=<repo-name>
IDS=$(aws ecr list-images --repository-name "$R" --query 'imageIds[*]' --output json)
aws ecr batch-delete-image --repository-name "$R" --image-ids "$IDS"
aws cloudformation delete-stack --stack-name <companion-stack>
```

Two of these had been silently stuck since 2023 for this exact reason.

## When something looks broken

Work down this list; each step rules out a whole class of cause.

1. **Did it run?** `describe-log-streams --order-by LastEventTime --descending`. No recent stream → the trigger is the problem, not the code. Check `aws scheduler get-schedule` for `EndDate`, `State`, and that the target ARN matches the live function.
2. **Did it log `ERROR`?** `filter-log-events --filter-pattern 'ERROR'` over the window. Remember a run can log errors *and* still report success.
3. **Which half failed?** The FIS and USSA paths are independent and each swallows its own exceptions. `Checking fis points` / `Checking ussa points` bracket them. A `sys.exit()` on a DynamoDB connect failure in the FIS half will take the USSA half down with it.
4. **Did it write anything?** Look for `UPDATES: N rows`. Zero is legitimate if the data has not changed since the last run — cross-check against a `get-item` for a known athlete.
5. **Is the source feed the problem?** Both scrapers depend on sites that owe this project nothing. See [get-points-list.md](get-points-list.md) for the FIS export-link indices and the USSA schedule-PDF discovery, both of which have broken before.
6. **Is it a quiet wrong answer?** No alarm will tell you. Run the tests ([testing.md](testing.md)), then spot-check a known athlete's points against the source list.

For the calculator lambda rather than the ingest job, see [get-livetiming-info.md](get-livetiming-info.md) and [points-calculation.md](points-calculation.md).
