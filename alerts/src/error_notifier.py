"""Emails unhandled calculator failures as they happen.

Target of a CloudWatch Logs subscription filter on the get-livetiming-info log
group. Unhandled errors are rare (zero in a typical week), so one email per
occurrence is reasonable. Name-match misses are NOT handled here - they run to
hundreds a day in season and are batched by digest.py instead.
"""

import base64
import gzip
import json
import os
import re

import boto3

sns = boto3.client("sns")
TOPIC_ARN = os.environ["TOPIC_ARN"]
LOG_GROUP = os.environ.get("SOURCE_LOG_GROUP", "")

# the handler logs "params: {...}" on its own line inside the same event
PARAMS_PATTERN = re.compile(r"params: (\{.*?\})\n", re.DOTALL)


def extract_params(message):
    match = PARAMS_PATTERN.search(message)
    return match.group(1) if match else "(not captured)"


def first_line(message):
    for line in message.splitlines():
        if line.strip():
            return line.strip()
    return message[:200]


def build_email(events):
    lines = [
        f"{len(events)} unhandled error(s) in get-livetiming-info.",
        "",
    ]
    for event in events:
        message = event.get("message", "")
        lines += [
            "-" * 60,
            first_line(message),
            "",
            f"  params: {extract_params(message)}",
            f"  stream: {event.get('logStreamName', '?')}",
            "",
            message.strip()[:2000],
            "",
        ]

    if LOG_GROUP:
        lines += [
            "-" * 60,
            f"Log group: {LOG_GROUP}",
        ]
    return "\n".join(lines)


def lambda_handler(event, context):
    payload = json.loads(
        gzip.decompress(base64.b64decode(event["awslogs"]["data"])).decode("utf-8")
    )

    # control messages are sent once when the subscription is created
    if payload.get("messageType") == "CONTROL_MESSAGE":
        return

    events = payload.get("logEvents", [])
    if not events:
        return

    for entry in events:
        entry.setdefault("logStreamName", payload.get("logStream", "?"))

    sns.publish(
        TopicArn=TOPIC_ARN,
        Subject="fiscalculator: unhandled error in the calculator"[:100],
        Message=build_email(events),
    )
