"""Reusable CloudWatch Logs Insights query runner, shared by all health checks."""

import logging
import time
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_POLL_INTERVAL_SECONDS = 2
_MAX_WAIT_SECONDS = 60
_TERMINAL_STATUSES = {"Complete", "Failed", "Cancelled", "Timeout"}


def _poll_query(logs_client, query_id: str, label: str) -> list[list[dict]]:
    """Poll get_query_results() until the query reaches a terminal state and return its rows."""
    elapsed_seconds = 0
    while elapsed_seconds < _MAX_WAIT_SECONDS:
        try:
            response = logs_client.get_query_results(queryId=query_id)
        except Exception:
            logger.exception("Failed to fetch Logs Insights results for %s", label)
            return []

        status = response.get("status")
        if status in _TERMINAL_STATUSES:
            if status != "Complete":
                logger.warning("Logs Insights query for %s ended with status %s", label, status)
                return []
            rows = response.get("results", [])
            logger.info("Logs Insights query for %s returned %d row(s)", label, len(rows))
            return rows

        time.sleep(_POLL_INTERVAL_SECONDS)
        elapsed_seconds += _POLL_INTERVAL_SECONDS

    logger.warning("Logs Insights query for %s did not complete within %ss", label, _MAX_WAIT_SECONDS)
    return []


def run_query(logs_client, log_group: str, query_string: str, lookback_minutes: int = 1440) -> list[list[dict]]:
    """Execute a Logs Insights query against one log group and return its result rows.

    Starts the query with start_query(), polls get_query_results() until it reaches
    a terminal state, and returns the raw rows. Returns an empty list if the query
    fails, times out, or raises an exception - callers should treat that as "no data".
    """
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=lookback_minutes)

    try:
        query_id = logs_client.start_query(
            logGroupName=log_group,
            startTime=int(start_time.timestamp()),
            endTime=int(end_time.timestamp()),
            queryString=query_string,
        )["queryId"]
    except Exception:
        logger.exception("Failed to start Logs Insights query for log group %s - query was:\n%s", log_group, query_string)
        return []

    return _poll_query(logs_client, query_id, log_group)


def run_query_multi(logs_client, log_groups: list[str], query_string: str, lookback_minutes: int = 1440) -> list[list[dict]]:
    """Execute a Logs Insights query across several log groups at once (must be same account/region).

    Same contract as run_query(), but for checks whose log lines could land in any of
    a handful of log groups (e.g. application vs system vs CloudFormation logs).
    """
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=lookback_minutes)

    try:
        query_id = logs_client.start_query(
            logGroupNames=log_groups,
            startTime=int(start_time.timestamp()),
            endTime=int(end_time.timestamp()),
            queryString=query_string,
        )["queryId"]
    except Exception:
        logger.exception("Failed to start Logs Insights query for log groups %s - query was:\n%s", log_groups, query_string)
        return []

    return _poll_query(logs_client, query_id, ", ".join(log_groups))


def find_log_group_region(session, log_group_name: str, regions: list[str]) -> str | None:
    """Search every region for a log group with this exact name and return the region it's in.

    Log groups are region-scoped and different client accounts may keep them in
    different regions, so this avoids hardcoding a region per client.
    """
    for region in regions:
        logs_client = session.client("logs", region_name=region)
        try:
            response = logs_client.describe_log_groups(logGroupNamePrefix=log_group_name, limit=1)
        except Exception:
            logger.exception("Failed to describe log groups in %s", region)
            continue

        if any(group["logGroupName"] == log_group_name for group in response.get("logGroups", [])):
            logger.info("Found log group %s in region %s", log_group_name, region)
            return region

    logger.warning("Log group %s not found in any of %d regions", log_group_name, len(regions))
    return None


def extract_messages(results: list[list[dict]]) -> list[str]:
    """Flatten Logs Insights result rows into a list of @message field values."""
    messages = []
    for row in results:
        for field in row:
            if field.get("field") == "@message":
                messages.append(field.get("value", ""))
    return messages


def extract_stats(results: list[list[dict]]) -> dict[str, str]:
    """Flatten a single-row `stats` query result into a {field_name: value} dict."""
    if not results:
        return {}
    return {field["field"]: field["value"] for field in results[0] if "field" in field}


def extract_fields(results: list[list[dict]]) -> list[dict[str, str]]:
    """Flatten Logs Insights result rows into a list of {field_name: value} dicts, one per row.

    Unlike extract_messages(), this keeps every requested field (e.g. both @message and
    @timestamp) so callers can pull a timestamp alongside the message text.
    """
    return [{field["field"]: field["value"] for field in row if "field" in field} for row in results]
