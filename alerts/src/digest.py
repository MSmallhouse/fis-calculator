"""Daily summary of racers whose points could not be matched.

A miss means the calculator could not find a racer in the points table, so it
assigned the event maximum instead - the scores for that race are approximate.
Individually these are routine (hundreds a day in season), so emailing each one
is useless. What is actionable is *which racers keep missing*: a name that shows
up every day is either a normalisation failure worth patching in
NAME_ERROR_FISCODES, or a sign the points table is stale.

Reads the structured NAME_MATCH_MISS lines that get-livetiming-info emits, one
per affected request.
"""

import json
import os
import time
from collections import Counter, defaultdict

import boto3

logs = boto3.client("logs")
sns = boto3.client("sns")

TOPIC_ARN = os.environ["TOPIC_ARN"]
LOG_GROUP = os.environ["SOURCE_LOG_GROUP"]
LOOKBACK_HOURS = int(os.environ.get("LOOKBACK_HOURS", "24"))
TOP_N = int(os.environ.get("TOP_N", "25"))
# below this many affected requests it is not worth an email
MIN_REQUESTS_TO_REPORT = int(os.environ.get("MIN_REQUESTS_TO_REPORT", "1"))

QUERY = """
fields @timestamp, @message
| filter @message like /NAME_MATCH_MISS/
| sort @timestamp desc
| limit 10000
"""


def run_query(start, end):
    query_id = logs.start_query(
        logGroupName=LOG_GROUP,
        startTime=start,
        endTime=end,
        queryString=QUERY,
    )["queryId"]

    for _ in range(60):
        result = logs.get_query_results(queryId=query_id)
        if result["status"] in ("Complete", "Failed", "Cancelled", "Timeout"):
            if result["status"] != "Complete":
                raise Exception(f"Logs Insights query {result['status']}")
            return result["results"]
        time.sleep(2)

    raise Exception("Logs Insights query did not finish in time")


def parse_rows(rows):
    records = []
    for row in rows:
        message = next((f["value"] for f in row if f["field"] == "@message"), "")
        _, _, payload = message.partition("NAME_MATCH_MISS ")
        if not payload:
            continue
        try:
            records.append(json.loads(payload.strip()))
        except json.JSONDecodeError:
            continue
    return records


def build_email(records, hours):
    by_name = Counter()
    sample_url = {}
    by_provider = Counter()
    total_missed = 0

    for record in records:
        by_provider[record.get("provider", "?")] += 1
        for name in record.get("missed", []):
            by_name[name] += 1
            total_missed += 1
            sample_url.setdefault(name, record.get("url", ""))

    lines = [
        f"{len(records)} request(s) in the last {hours}h had racers whose points "
        f"could not be matched ({total_missed} racer-lookups, "
        f"{len(by_name)} distinct names).",
        "",
        "Scores for those races used the event maximum for the unmatched racers,",
        "so they are approximate.",
        "",
        "By provider: " + ", ".join(f"{k}={v}" for k, v in by_provider.most_common()),
        "",
        f"Most frequent unmatched names (top {TOP_N}):",
        "",
    ]

    for name, count in by_name.most_common(TOP_N):
        lines.append(f"  {count:>4}x  {name}")
        lines.append(f"         e.g. {sample_url.get(name, '')[:120]}")

    if len(by_name) > TOP_N:
        lines.append(f"  ... and {len(by_name) - TOP_N} more distinct names")

    lines += [
        "",
        "A name recurring every day is usually fixable: add it to",
        "NAME_ERROR_FISCODES in get-livetiming-info/src/utils.py, or check whether",
        "the points table has gone stale. See docs/get-livetiming-info.md.",
    ]
    return "\n".join(lines)


def lambda_handler(event=None, context=None):
    end = int(time.time())
    start = end - LOOKBACK_HOURS * 3600

    records = parse_rows(run_query(start, end))
    if len(records) < MIN_REQUESTS_TO_REPORT:
        print(f"only {len(records)} affected requests, not emailing")
        return {"affected_requests": len(records), "emailed": False}

    sns.publish(
        TopicArn=TOPIC_ARN,
        Subject=f"fiscalculator: {len(records)} races with unmatched racer points"[:100],
        Message=build_email(records, LOOKBACK_HOURS),
    )
    return {"affected_requests": len(records), "emailed": True}
