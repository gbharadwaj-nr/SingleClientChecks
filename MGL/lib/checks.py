"""Independent CloudWatch Logs Insights / AWS API health-check functions for MGL.

Each `check_*` function targets one log stream (or, for RDS/Database Validation, calls an
AWS API or a database directly), runs its own query, parses the latest matching log
line(s), and returns {"status": "Healthy"|"Warning"|"Failed", "detail": str} for the HTML
report. Log-based functions share `_run_stream()` (single-stream query + field extraction).
"""

import logging
import re

import config
from lib.db_check import run_database_validation
from lib.logs_insights import extract_fields, extract_stats, run_query

logger = logging.getLogger(__name__)

HEALTHY = "Healthy"
WARNING = "Warning"
FAILED = "Failed"

# Keywords that indicate a batch/monitoring log line reports a failure.
_FAILURE_KEYWORDS = ("fail", "error", "exception", "unavailable", "timeout")


def _run_stream(logs_client, log_group: str, stream: str, lookback_minutes: int,
                 limit: int = 20, message_filter: str | None = None) -> list[dict[str, str]]:
    """Run a `fields @message, @timestamp` query restricted to one specific @logStream.

    Returns rows (most-recent-first) as {"@message": ..., "@timestamp": ...} dicts so
    callers can pull both the message text and its timestamp for the latest entry.
    """
    # Use a quoted substring match, not /regex/ - MGL's stream names contain literal "/"
    # (e.g. "batch/i-.../batch/norkom.log"), which breaks the /regex/ delimiter syntax.
    filter_clause = f'@logStream like "{stream}"'
    if message_filter:
        filter_clause += f" and ({message_filter})"
    query = (
        "fields @message, @timestamp\n"
        f"| filter {filter_clause}\n"
        "| sort @timestamp desc\n"
        f"| limit {limit}"
    )
    results = run_query(logs_client, log_group, query, lookback_minutes)
    return extract_fields(results)


def _evidence_lines(rows: list, limit: int = 5) -> list[str]:
    """Format up to `limit` raw log rows (dicts) or plain message strings for the HTML evidence panel."""
    lines = []
    for item in rows[:limit]:
        if isinstance(item, dict):
            lines.append(f"{item.get('@timestamp', '')} {item.get('@message', '')}".strip())
        else:
            lines.append(item)
    return lines


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
    detail = f"{pct:.1f}% available (success={stats.get('UI_Is_Up_Count', '0')}, failure={stats.get('UI_Is_Down_Count', '0')})"
    return {"status": HEALTHY if pct >= 100.0 else FAILED, "detail": detail, "evidence": [detail]}


def check_rds_status(logs_client, log_group: str, lookback_minutes: int) -> dict:
    """check_rds_status.log: verify RDS database health."""
    rows = _run_stream(logs_client, log_group, config.LOG_STREAMS["rds_status"], lookback_minutes, limit=2)
    if not rows:
        return {"status": FAILED, "detail": "No RDS status entries found in check_rds_status.log"}

    messages = [row.get("@message", "") for row in rows]
    failing = [m for m in messages if any(keyword in m.lower() for keyword in _FAILURE_KEYWORDS)]
    if failing:
        return {"status": FAILED, "detail": f"{len(failing)} RDS issue(s) - latest: {failing[0][:200]}", "evidence": _evidence_lines(rows)}
    return {"status": HEALTHY, "detail": messages[0][:200], "evidence": _evidence_lines(rows)}


def check_ec2_status(logs_client, log_group: str, lookback_minutes: int) -> dict:
    """check_ec2_status.log: verify EC2 instance health."""
    rows = _run_stream(logs_client, log_group, config.LOG_STREAMS["ec2_status"], lookback_minutes, limit=3)
    if not rows:
        return {"status": FAILED, "detail": "No EC2 status entries found in check_ec2_status.log"}

    messages = [row.get("@message", "") for row in rows]
    failing = [m for m in messages if any(keyword in m.lower() for keyword in _FAILURE_KEYWORDS)]
    if failing:
        return {"status": FAILED, "detail": f"{len(failing)} EC2 instance issue(s) - latest: {failing[0][:200]}", "evidence": _evidence_lines(rows)}
    return {"status": HEALTHY, "detail": messages[0][:200], "evidence": _evidence_lines(rows)}


def check_worldcheck_download(logs_client, log_group: str, lookback_minutes: int) -> dict:
    """runBatch.log: verify the daily WorldCheck download completed; extract status and timestamp."""
    rows = _run_stream(logs_client, log_group, config.LOG_STREAMS["run_batch"], lookback_minutes, limit=20)
    if not rows:
        return {"status": FAILED, "detail": "No runBatch.log activity found"}

    candidates = [r for r in rows if "worldcheck" in r.get("@message", "").lower()] or rows
    latest = candidates[0]
    message, timestamp = latest.get("@message", ""), latest.get("@timestamp", "")

    if any(keyword in message.lower() for keyword in _FAILURE_KEYWORDS):
        return {"status": FAILED, "detail": f"{message[:200]} at {timestamp}", "evidence": _evidence_lines(rows)}
    if any(keyword in message.lower() for keyword in ("success", "complete", "done")):
        return {"status": HEALTHY, "detail": f"{message[:200]} at {timestamp}", "evidence": _evidence_lines(rows)}
    return {"status": WARNING, "detail": f"Ambiguous download status - {message[:200]} at {timestamp}", "evidence": _evidence_lines(rows)}


def check_index_rebuild(logs_client, log_group: str, lookback_minutes: int) -> dict:
    """norkom.log: count 'Build totCount:' index rebuild events; report count and latest status."""
    rows = _run_stream(
        logs_client, log_group, config.LOG_STREAMS["norkom"], lookback_minutes,
        limit=100, message_filter="@message like /Build totCount:/",
    )
    if not rows:
        return {"status": FAILED, "detail": "No 'Build totCount:' index rebuild events found in norkom.log"}

    latest_message, latest_timestamp = rows[0].get("@message", ""), rows[0].get("@timestamp", "")
    has_failure = any(keyword in row.get("@message", "").lower() for row in rows for keyword in _FAILURE_KEYWORDS)
    detail = f"{len(rows)} rebuild event(s) - latest: {latest_message[:200]} at {latest_timestamp}"
    return {"status": FAILED if has_failure else HEALTHY, "detail": detail, "evidence": _evidence_lines(rows)}


def check_envelope_processing(logs_client, log_group: str, lookback_minutes: int) -> dict:
    """pollDXVLanding.log: detect envelope arrival; extract envelope filename and timestamp."""
    rows = _run_stream(
        logs_client, log_group, config.LOG_STREAMS["poll_dxv_landing"], lookback_minutes,
        limit=20, message_filter="@message like /Processing envelope/",
    )
    if not rows:
        return {"status": FAILED, "detail": "No 'Processing envelope' entries found in pollDXVLanding.log"}

    message, timestamp = rows[0].get("@message", ""), rows[0].get("@timestamp", "")
    filename_match = re.search(r"(ENVELOPE_\d{8}\.ZIP\.pgp)", message, re.IGNORECASE)
    filename = filename_match.group(1) if filename_match else message[:150]
    return {"status": HEALTHY, "detail": f"{filename} received at {timestamp}", "evidence": _evidence_lines(rows)}


def check_batch_status(logs_client, log_group: str, lookback_minutes: int) -> dict:
    """getDXVLandingFiles.log: confirm batch processing started after envelope arrival."""
    rows = _run_stream(logs_client, log_group, config.LOG_STREAMS["get_dxv_landing_files"], lookback_minutes, limit=100)
    if not rows:
        return {"status": FAILED, "detail": "No batch activity found in getDXVLandingFiles.log"}

    messages = [row.get("@message", "") for row in rows]
    failing = [m for m in messages if any(keyword in m.lower() for keyword in _FAILURE_KEYWORDS)]
    if failing:
        return {"status": FAILED, "detail": f"{len(failing)} batch issue(s) - latest: {failing[0][:200]}", "evidence": _evidence_lines(rows)}

    plural = "y" if len(rows) == 1 else "ies"
    return {"status": HEALTHY, "detail": f"Batch activity detected ({len(rows)} entr{plural}) - latest: {messages[0][:200]}", "evidence": _evidence_lines(rows)}


def check_acquisition_status(logs_client, log_group: str, lookback_minutes: int) -> dict:
    """getDXVLandingFiles.log: confirm the Acquisition batch stage started."""
    rows = _run_stream(
        logs_client, log_group, config.LOG_STREAMS["get_dxv_landing_files"], lookback_minutes,
        limit=100, message_filter="@message like /Acquisition/",
    )
    if not rows:
        return {"status": FAILED, "detail": "No Acquisition batch activity found in getDXVLandingFiles.log"}

    message, timestamp = rows[0].get("@message", ""), rows[0].get("@timestamp", "")
    if any(keyword in message.lower() for keyword in _FAILURE_KEYWORDS):
        return {"status": FAILED, "detail": f"{message[:200]} at {timestamp}", "evidence": _evidence_lines(rows)}
    return {"status": HEALTHY, "detail": f"Acquisition started at {timestamp} - {message[:150]}", "evidence": _evidence_lines(rows)}


def check_wlm_status(logs_client, log_group: str, lookback_minutes: int) -> dict:
    """runBatch.log: verify the WLM batch completed successfully; cross-check against
    the index rebuild completion in norkom.log (requirement: WLM runs only after it)."""
    rows = _run_stream(
        logs_client, log_group, config.LOG_STREAMS["run_batch"], lookback_minutes,
        limit=20, message_filter="@message like /WLM Batch/",
    )
    if not rows:
        return {"status": FAILED, "detail": "No 'WLM Batch' entries found in runBatch.log"}

    message, timestamp = rows[0].get("@message", ""), rows[0].get("@timestamp", "")
    if any(keyword in message.lower() for keyword in _FAILURE_KEYWORDS):
        return {"status": FAILED, "detail": f"{message[:200]} at {timestamp}", "evidence": _evidence_lines(rows)}
    if "success" not in message.lower():
        return {"status": WARNING, "detail": f"Ambiguous WLM batch status - {message[:200]} at {timestamp}", "evidence": _evidence_lines(rows)}

    index_rows = _run_stream(
        logs_client, log_group, config.LOG_STREAMS["norkom"], lookback_minutes,
        limit=10, message_filter="@message like /Finished executing procedure IndexReportProcedure/",
    )
    if not index_rows:
        return {"status": WARNING, "detail": f"{message[:150]} at {timestamp}, but IndexReportProcedure completion not found in norkom.log", "evidence": _evidence_lines(rows)}

    index_ts = index_rows[0].get("@timestamp", "")
    return {"status": HEALTHY, "detail": f"{message[:150]} at {timestamp}; IndexReportProcedure finished at {index_ts}", "evidence": _evidence_lines(rows + index_rows)}


def check_rds_maintenance(session, all_regions: list[str], lookback_minutes: int) -> dict:
    """RDS DescribePendingMaintenanceActions (read-only) across every enabled region."""
    pending = []
    for region in all_regions:
        rds = session.client("rds", region_name=region)
        try:
            paginator = rds.get_paginator("describe_pending_maintenance_actions")
            for page in paginator.paginate():
                for item in page.get("PendingMaintenanceActions", []):
                    resource_id = item.get("ResourceIdentifier", "unknown")
                    for action in item.get("PendingMaintenanceActionDetails", []):
                        pending.append(f"{resource_id} ({region}): {action.get('Action', 'unknown')} - notify stakeholders and schedule a maintenance window")
        except Exception:
            logger.exception("Failed to describe pending maintenance actions in %s", region)
            continue

    if not pending:
        return {"status": HEALTHY, "detail": "No pending maintenance actions on any RDS instance"}
    return {"status": WARNING, "detail": "; ".join(pending)[:500], "evidence": _evidence_lines(pending)}


def check_database_validation(lookback_minutes: int) -> dict:
    """SERVER_STATES check: SELECT * FROM SERVER_STATES WHERE CURRENT_STATE <> NEW_STATE."""
    return run_database_validation()


def check_asg_health(session, all_regions: list[str], lookback_minutes: int) -> dict:
    """Discover Auto Scaling groups whose name contains config.INFRA_NAME_FILTER, across all regions."""
    name_filter = config.INFRA_NAME_FILTER
    groups = []
    for region in all_regions:
        client = session.client("autoscaling", region_name=region)
        try:
            paginator = client.get_paginator("describe_auto_scaling_groups")
            for page in paginator.paginate():
                for group in page.get("AutoScalingGroups", []):
                    if name_filter.lower() in group.get("AutoScalingGroupName", "").lower():
                        groups.append((region, group))
        except Exception:
            logger.exception("Failed to describe Auto Scaling groups in %s", region)
            continue

    if not groups:
        return {"status": FAILED, "detail": f"No Auto Scaling groups matching '{name_filter}' found"}

    details = []
    unhealthy_total = 0
    for region, group in groups:
        instances = group.get("Instances", [])
        in_service = sum(1 for i in instances if i.get("LifecycleState") == "InService")
        unhealthy = sum(1 for i in instances if i.get("HealthStatus") != "Healthy")
        unhealthy_total += unhealthy
        details.append(
            f"{group.get('AutoScalingGroupName', '')}: desired={group.get('DesiredCapacity', 0)} "
            f"min={group.get('MinSize', 0)} max={group.get('MaxSize', 0)} in_service={in_service} "
            f"unhealthy={unhealthy} region={region}"
        )

    status = HEALTHY if unhealthy_total == 0 else FAILED
    return {"status": status, "detail": "; ".join(details)[:500], "evidence": details}


def check_efs_health(session, all_regions: list[str], lookback_minutes: int) -> dict:
    """Discover EFS file systems whose Name tag contains config.INFRA_NAME_FILTER, across all regions."""
    name_filter = config.INFRA_NAME_FILTER
    file_systems = []
    for region in all_regions:
        client = session.client("efs", region_name=region)
        try:
            paginator = client.get_paginator("describe_file_systems")
            for page in paginator.paginate():
                for fs in page.get("FileSystems", []):
                    if name_filter.lower() in fs.get("Name", "").lower():
                        file_systems.append((region, fs))
        except Exception:
            logger.exception("Failed to describe EFS file systems in %s", region)
            continue

    if not file_systems:
        return {"status": FAILED, "detail": f"No EFS file systems matching '{name_filter}' found"}

    details = []
    unavailable_total = 0
    for region, fs in file_systems:
        life_cycle_state = fs.get("LifeCycleState", "unknown")
        if life_cycle_state != "available":
            unavailable_total += 1
        size_gb = fs.get("SizeInBytes", {}).get("Value", 0) / (1024 ** 3)
        details.append(
            f"{fs.get('Name') or fs.get('FileSystemId', '')}: state={life_cycle_state} "
            f"size={size_gb:.2f}GB region={region}"
        )

    status = HEALTHY if unavailable_total == 0 else FAILED
    return {"status": status, "detail": "; ".join(details)[:500], "evidence": details}


CHECK_FUNCTIONS = {
    "check_ui_availability": check_ui_availability,
    "check_ec2_status": check_ec2_status,
    "check_rds_status": check_rds_status,
    "check_worldcheck_download": check_worldcheck_download,
    "check_index_rebuild": check_index_rebuild,
    "check_envelope_processing": check_envelope_processing,
    "check_batch_status": check_batch_status,
    "check_acquisition_status": check_acquisition_status,
    "check_wlm_status": check_wlm_status,
    "check_rds_maintenance": check_rds_maintenance,
    "check_database_validation": check_database_validation,
    "check_asg_health": check_asg_health,
    "check_efs_health": check_efs_health,
}
