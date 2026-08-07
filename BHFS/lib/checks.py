"""Independent CloudWatch Logs Insights health-check functions for BHFS.

Each `check_*` function targets one log stream (or, for a couple of checks, the whole
application log group), builds its own Logs Insights query, runs it, parses the latest
matching log line(s), and returns {"status": "Healthy"|"Warning"|"Failed", "detail": str}
for the HTML report. Functions share `_run_rows()` (query + field extraction), `_run_stream()`
(same, scoped to one @logStream) and `_run()` (multi-stream query via config.LOG_STREAM_FILTER),
but each check's log stream, search terms and pass/fail logic are independent of the others.
"""

import re

import config
from lib.logs_insights import extract_fields, extract_messages, extract_stats, run_query

HEALTHY = "Healthy"
WARNING = "Warning"
FAILED = "Failed"

# Keywords that indicate a batch/monitoring log line reports a failure.
_FAILURE_KEYWORDS = ("fail", "error", "exception", "unavailable", "timeout")

# How many matches an error-style search tolerates before escalating Warning -> Failed.
_ERROR_WARNING_THRESHOLD = 3


def _run(logs_client, log_group: str, filter_clause: str, lookback_minutes: int, limit: int = 20) -> list[str]:
    """Run a `fields @message, @timestamp` query restricted to config.LOG_STREAM_FILTER."""
    query = (
        "fields @message, @timestamp\n"
        f"| filter {config.LOG_STREAM_FILTER}\n"
        f"| filter {filter_clause}\n"
        "| sort @timestamp desc\n"
        f"| limit {limit}"
    )
    results = run_query(logs_client, log_group, query, lookback_minutes)
    return extract_messages(results)


def _run_stream(logs_client, log_group: str, stream: str, lookback_minutes: int,
                 limit: int = 5, message_filter: str | None = None) -> list[dict[str, str]]:
    """Run a `fields @message, @timestamp` query restricted to one specific @logStream.

    Returns rows (most-recent-first) as {"@message": ..., "@timestamp": ...} dicts so
    callers can pull both the message text and its timestamp for the latest entry.
    """
    filter_clause = f"@logStream like /{stream}/"
    if message_filter:
        filter_clause += f" and ({message_filter})"
    return _run_rows(logs_client, log_group, filter_clause, lookback_minutes, limit)


def _run_rows(logs_client, log_group: str, filter_clause: str, lookback_minutes: int, limit: int = 10) -> list[dict[str, str]]:
    """Run a `fields @message, @timestamp` query with an arbitrary filter clause (no log-stream restriction).

    Returns rows (most-recent-first) as {"@message": ..., "@timestamp": ...} dicts.
    """
    query = (
        "fields @message, @timestamp\n"
        f"| filter {filter_clause}\n"
        "| sort @timestamp desc\n"
        f"| limit {limit}"
    )
    results = run_query(logs_client, log_group, query, lookback_minutes)
    return extract_fields(results)


def _error_search_status(messages: list[str], healthy_detail: str) -> dict:
    """Shared severity rule for "search for error keywords" checks.

    No matches -> Healthy. A few matches -> Warning. Many matches (or anything
    mentioning FATAL) -> Failed.
    """
    if not messages:
        return {"status": HEALTHY, "detail": healthy_detail}

    latest = messages[0][:200]
    if len(messages) > _ERROR_WARNING_THRESHOLD or any("fatal" in m.lower() for m in messages):
        return {"status": FAILED, "detail": f"{len(messages)} matching entr{'y' if len(messages) == 1 else 'ies'} - latest: {latest}"}
    return {"status": WARNING, "detail": f"{len(messages)} matching entr{'y' if len(messages) == 1 else 'ies'} - latest: {latest}"}


def _batch_monitoring_status(rows: list[dict[str, str]], stream: str, batch_name: str) -> dict:
    """Shared rule for the AML/WLM/CDD batch-monitoring checks: inspect the latest log line."""
    if not rows:
        return {"status": FAILED, "detail": f"No {batch_name} batch activity found in {stream}"}

    latest_message = rows[0].get("@message", "")
    has_failure = any(keyword in latest_message.lower() for keyword in _FAILURE_KEYWORDS)
    status = FAILED if has_failure else HEALTHY
    return {"status": status, "detail": f"Latest batch status: {latest_message[:200]}"}


def check_ec2_status(logs_client, log_group: str, lookback_minutes: int) -> dict:
    """check_ec2_status.log: verify EC2 instance health."""
    rows = _run_stream(logs_client, log_group, config.LOG_STREAMS["ec2_status"], lookback_minutes, limit=5)
    if not rows:
        return {"status": FAILED, "detail": "No EC2 status entries found in check_ec2_status.log"}

    messages = [row.get("@message", "") for row in rows]
    failing = [m for m in messages if any(keyword in m.lower() for keyword in _FAILURE_KEYWORDS)]
    if failing:
        return {"status": FAILED, "detail": f"{len(failing)} EC2 instance issue(s) - latest: {failing[0][:200]}"}
    return {"status": HEALTHY, "detail": messages[0][:200]}


def check_rds_status(logs_client, log_group: str, lookback_minutes: int) -> dict:
    """check_rds_status.log: verify RDS database health."""
    rows = _run_stream(logs_client, log_group, config.LOG_STREAMS["rds_status"], lookback_minutes, limit=3)
    if not rows:
        return {"status": FAILED, "detail": "No RDS status entries found in check_rds_status.log"}

    messages = [row.get("@message", "") for row in rows]
    failing = [m for m in messages if any(keyword in m.lower() for keyword in _FAILURE_KEYWORDS)]
    if failing:
        return {"status": FAILED, "detail": f"{len(failing)} RDS issue(s) - latest: {failing[0][:200]}"}
    return {"status": HEALTHY, "detail": messages[0][:200]}


def check_api_latency(logs_client, log_group: str, lookback_minutes: int) -> dict:
    """bhfs-production-ApplicationLogs: parse per-line latency values and compute min/avg/max client-side."""
    query = (
        "fields @timestamp, @logStream, @message\n"
        "| filter @message like /(?i)(latency|response time|api_rest_response|request completed)/\n"
        r"| parse @message /(?i)latency[:\s=]+(?P<latency_value>[0-9]+(\.[0-9]+)?)/" "\n"
        "| sort @timestamp desc\n"
        "| limit 100"
    )
    results = run_query(logs_client, log_group, query, lookback_minutes)
    rows = extract_fields(results)
    if not rows:
        return {"status": FAILED, "detail": "No latency/response-time activity found in application logs"}

    latencies = []
    for row in rows:
        raw = row.get("latency_value")
        if raw is None:
            continue
        try:
            latencies.append(float(raw))
        except ValueError:
            continue

    if not latencies:
        plural = "y" if len(rows) == 1 else "ies"
        return {"status": WARNING, "detail": f"{len(rows)} matching entr{plural} found but no numeric latency value could be parsed"}

    min_ms, max_ms, avg_ms = min(latencies), max(latencies), sum(latencies) / len(latencies)
    detail = f"Min {min_ms:.0f}ms / Avg {avg_ms:.0f}ms / Max {max_ms:.0f}ms (n={len(latencies)})"

    if max_ms >= config.API_LATENCY_FAILED_MS:
        return {"status": FAILED, "detail": detail}
    if max_ms >= config.API_LATENCY_WARNING_MS or avg_ms >= config.API_LATENCY_WARNING_MS:
        return {"status": WARNING, "detail": detail}
    return {"status": HEALTHY, "detail": detail}


def check_ui_availability(logs_client, log_group: str, lookback_minutes: int) -> dict:
    """UI availability Lambda log group: success/failure counts and availability percentage."""
    query = (
        "fields @message\n"
        "| filter @message like /Check result/\n"
        "| fields strcontains(@message, \"SUCCESS\") as @success,\n"
        "         strcontains(@message, \"FAIL\") as @fail\n"
        "| stats sum(@success) as UI_Is_Up_Count, sum(@fail) as UI_Is_Down_Count, "
        "sum(@success) / (sum(@fail) + sum(@success)) * 100 as UI_Availability_Percentage"
    )
    results = run_query(logs_client, log_group, query, lookback_minutes)
    stats = extract_stats(results)
    raw_pct = stats.get("UI_Availability_Percentage")
    if raw_pct is None:
        return {"status": FAILED, "detail": "No UI availability data found"}

    pct = float(raw_pct)
    up_count = stats.get("UI_Is_Up_Count", "0")
    down_count = stats.get("UI_Is_Down_Count", "0")
    detail = f"{pct:.1f}% available (success={up_count}, failure={down_count})"

    if pct >= 100.0:
        return {"status": HEALTHY, "detail": detail}
    if pct >= config.UI_AVAILABILITY_WARNING_PCT:
        return {"status": WARNING, "detail": detail}
    return {"status": FAILED, "detail": detail}


def check_factiva_import(logs_client, log_group: str, lookback_minutes: int) -> dict:
    """norkom.log: confirm the Factiva FPFA list import finished; extract filename and timestamp."""
    rows = _run_stream(
        logs_client, log_group, config.LOG_STREAMS["norkom"], lookback_minutes,
        limit=5, message_filter="@message like /End of Factiva FPFA list import/",
    )
    if not rows:
        return {"status": FAILED, "detail": "No 'End of Factiva FPFA list import' entry found in norkom.log"}

    message = rows[0].get("@message", "")
    timestamp = rows[0].get("@timestamp", "")
    filename_match = re.search(r"([\w\-]+\.(?:txt|csv|zip|dat))", message, re.IGNORECASE)
    filename = filename_match.group(1) if filename_match else "unknown file"
    return {"status": HEALTHY, "detail": f"{filename} imported at {timestamp}"}


def check_envelope_processing(logs_client, log_group: str, lookback_minutes: int) -> dict:
    """bhfs-production-ApplicationLogs: search for 'Envelope Processing' entries; extract
    processing status, timestamp, and envelope filename from the latest event."""
    rows = _run_rows(logs_client, log_group, "@message like /Envelope Processing/", lookback_minutes, limit=10)
    if not rows:
        return {"status": FAILED, "detail": "No 'Envelope Processing' entries found in bhfs-production-ApplicationLogs"}

    message = rows[0].get("@message", "")
    timestamp = rows[0].get("@timestamp", "")

    filename_match = re.search(r"(ENVELOPE_\S*\.ZIP(?:\.PGP)?)", message, re.IGNORECASE)
    filename = filename_match.group(1) if filename_match else "unknown file"

    status_match = re.search(r"(?i)status\s*[:=]\s*(\w+)", message)
    if status_match:
        processing_status = status_match.group(1).upper()
    elif any(keyword in message.lower() for keyword in ("fail", "error")):
        processing_status = "FAILED"
    elif any(keyword in message.lower() for keyword in ("success", "complete")):
        processing_status = "SUCCESS"
    else:
        processing_status = "UNKNOWN"

    detail = f"{filename} - status: {processing_status} at {timestamp}"

    if processing_status in ("FAILED", "FAILURE", "ERROR"):
        return {"status": FAILED, "detail": detail}
    if processing_status in ("SUCCESS", "COMPLETED", "COMPLETE", "OK"):
        return {"status": HEALTHY, "detail": detail}
    return {"status": WARNING, "detail": detail}


def check_aml_batch(logs_client, log_group: str, lookback_minutes: int) -> dict:
    """aml_batch_monitoring.log: verify the AML batch completed successfully."""
    rows = _run_stream(logs_client, log_group, config.LOG_STREAMS["aml_batch"], lookback_minutes, limit=5)
    return _batch_monitoring_status(rows, config.LOG_STREAMS["aml_batch"], "AML")


def check_wlm_batch(logs_client, log_group: str, lookback_minutes: int) -> dict:
    """wlm_batch_monitoring.log: verify the WLM batch completed successfully."""
    rows = _run_stream(logs_client, log_group, config.LOG_STREAMS["wlm_batch"], lookback_minutes, limit=5)
    return _batch_monitoring_status(rows, config.LOG_STREAMS["wlm_batch"], "WLM")


def check_cdd_batch(logs_client, log_group: str, lookback_minutes: int) -> dict:
    """cdd_batch_monitoring.log: verify the CDD batch completed successfully."""
    rows = _run_stream(logs_client, log_group, config.LOG_STREAMS["cdd_batch"], lookback_minutes, limit=5)
    return _batch_monitoring_status(rows, config.LOG_STREAMS["cdd_batch"], "CDD")


def check_acq_success(logs_client, log_group: str, lookback_minutes: int) -> dict:
    """check_acq_success.log: verify the ACQ success flag exists; extract the latest success message."""
    rows = _run_stream(logs_client, log_group, config.LOG_STREAMS["acq_success"], lookback_minutes, limit=5)
    if not rows:
        return {"status": FAILED, "detail": "No ACQ success flag found in check_acq_success.log"}

    latest_message = rows[0].get("@message", "")
    if "acq_success" in latest_message.lower() or "success" in latest_message.lower():
        return {"status": HEALTHY, "detail": latest_message[:200]}
    return {"status": WARNING, "detail": f"check_acq_success.log has activity but no success flag - latest: {latest_message[:200]}"}


def check_transaction_file(logs_client, log_group: str, lookback_minutes: int) -> dict:
    """bhfs-production-ApplicationLogs: confirm the transaction file arrived and extract its record count."""
    filter_clause = (
        "@message like /TRANSACTIONS_/ "
        "or @message like /Temporary Transaction File/ "
        "or @message like /records within/ "
        "or @message like /record count/"
    )
    rows = _run_rows(logs_client, log_group, filter_clause, lookback_minutes, limit=100)
    if not rows:
        return {"status": FAILED, "detail": "No TRANSACTIONS_ file activity found"}

    message = rows[0].get("@message", "")
    timestamp = rows[0].get("@timestamp", "")
    filename_match = re.search(r"(TRANSACTIONS_\S*\.txt)", message, re.IGNORECASE)
    filename = filename_match.group(1) if filename_match else "Temporary Transaction File"

    count_match = re.search(r"(?i)(\d+)\s*records?\s*within", message) or re.search(r"(?i)record\s*count\D{0,10}(\d+)", message)
    if count_match:
        return {"status": HEALTHY, "detail": f"{filename} - {count_match.group(1)} records at {timestamp}"}
    return {"status": WARNING, "detail": f"{filename} found at {timestamp} but record count could not be parsed"}


def check_bad_files(logs_client, log_group: str, lookback_minutes: int) -> dict:
    """check_bad_files.log: verify NetReveal_BAD ZIP generation; extract the latest bad-file info."""
    rows = _run_stream(
        logs_client, log_group, config.LOG_STREAMS["bad_files"], lookback_minutes,
        limit=10, message_filter="@message like /NetReveal_BAD/",
    )
    if not rows:
        return {"status": FAILED, "detail": "No NetReveal_BAD ZIP found in check_bad_files.log"}

    latest_message = rows[0].get("@message", "")
    filename_match = re.search(r"(NetReveal_BAD\S*\.ZIP)", latest_message, re.IGNORECASE)
    filename = filename_match.group(1) if filename_match else latest_message[:150]
    return {"status": HEALTHY, "detail": f"Latest bad file: {filename}"}


def check_application_log(logs_client, log_group: str, lookback_minutes: int) -> dict:
    """application.log: search for application errors, exceptions, API errors and failed notifications."""
    message_filter = (
        "@message like /ERROR/ or @message like /Exception/ or @message like /FATAL/ "
        "or @message like /HTTP 500/ or @message like /Internal Server Error/ or @message like /API Error/ "
        "or @message like /Failed outbound/ or @message like /Notification failed/ or @message like /SMTP Error/"
    )
    rows = _run_stream(
        logs_client, log_group, config.LOG_STREAMS["application"], lookback_minutes,
        limit=50, message_filter=message_filter,
    )
    messages = [row.get("@message", "") for row in rows]
    return _error_search_status(messages, healthy_detail="No errors, exceptions, API errors, or failed notifications found in application.log")


def check_realtime_processing(logs_client, log_group: str, lookback_minutes: int) -> dict:
    """Real-Time Processing: confirm real-time activity is happening and free of failures."""
    messages = _run(logs_client, log_group, "@message like /Realtime/", lookback_minutes, limit=30)
    if not messages:
        return {"status": WARNING, "detail": "No real-time processing activity found in the lookback window"}

    failure_keywords = ("fail", "error", "exception", "timeout")
    failures = [m for m in messages if any(keyword in m.lower() for keyword in failure_keywords)]
    if failures:
        return {"status": FAILED, "detail": f"{len(failures)} real-time processing failure(s) - latest: {failures[0][:150]}"}
    return {"status": HEALTHY, "detail": f"{len(messages)} real-time processing entries, no failures detected"}


# Maps config.CHECKS[i]["func"] (a string) to the actual function, so main.py doesn't
# need a giant if/elif and config.py doesn't need to import this module's functions.
CHECK_FUNCTIONS = {
    "check_ec2_status": check_ec2_status,
    "check_rds_status": check_rds_status,
    "check_api_latency": check_api_latency,
    "check_ui_availability": check_ui_availability,
    "check_factiva_import": check_factiva_import,
    "check_envelope_processing": check_envelope_processing,
    "check_aml_batch": check_aml_batch,
    "check_wlm_batch": check_wlm_batch,
    "check_cdd_batch": check_cdd_batch,
    "check_acq_success": check_acq_success,
    "check_transaction_file": check_transaction_file,
    "check_bad_files": check_bad_files,
    "check_application_log": check_application_log,
    "check_realtime_processing": check_realtime_processing,
}
