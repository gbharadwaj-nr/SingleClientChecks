"""Independent CloudWatch Logs Insights / AWS API health-check functions for Generali.

Each `check_*` function targets one log stream (or, for RDS/ASG/EFS, calls an AWS API
directly), runs its own query, parses the latest matching log line(s), and returns
{"status": "Healthy"|"Warning"|"Failed", "detail": str} for the HTML report. Log-based
functions share `_run_stream()` (single-stream query + field extraction).
"""

import logging
import re
from datetime import datetime, timedelta, timezone

import config
from lib.logs_insights import extract_fields, run_query

logger = logging.getLogger(__name__)

HEALTHY = "Healthy"
WARNING = "Warning"
FAILED = "Failed"

# Keywords that indicate a batch/monitoring log line reports a failure.
_FAILURE_KEYWORDS = ("fail", "error", "exception", "unavailable", "timeout")


def _run_stream(logs_client, log_group: str, stream: str, lookback_minutes: int,
                 limit: int = 20, message_filter: str | None = None, fallback: bool = False) -> list[dict[str, str]]:
    """Run a `fields @message, @timestamp` query restricted to one specific @logStream.

    Returns rows (most-recent-first) as {"@message": ..., "@timestamp": ...} dicts so
    callers can pull both the message text and its timestamp for the latest entry.
    """
    # Use a quoted substring match, not /regex/ - Generali's stream names contain literal "/"
    # (e.g. "batch/i-.../batch/runBatch.log"), which breaks the /regex/ delimiter syntax.
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
    rows = extract_fields(results)
    if not rows and fallback and lookback_minutes < _FALLBACK_LOOKBACK_MINUTES:
        # No evidence in the requested window - fall back to a much longer lookback so a
        # quiet day still surfaces the last known log line instead of an incorrect "no data" result.
        results = run_query(logs_client, log_group, query, _FALLBACK_LOOKBACK_MINUTES)
        rows = extract_fields(results)
    return rows


# Extended lookback used only when `fallback=True` and the requested window is empty.
_FALLBACK_LOOKBACK_MINUTES = 43200  # 30 days


def _evidence_lines(rows: list, limit: int = 5) -> list[str]:
    """Format up to `limit` raw log rows (dicts) or plain message strings for the HTML evidence panel."""
    lines = []
    for item in rows[:limit]:
        if isinstance(item, dict):
            lines.append(f"{item.get('@timestamp', '')} {item.get('@message', '')}".strip())
        else:
            lines.append(item)
    return lines


def _name_matches(name: str, filters) -> bool:
    """True if every substring in `filters` (a str, or list/tuple of strs) appears in `name`."""
    required = [filters] if isinstance(filters, str) else list(filters)
    name_lower = name.lower()
    return all(f.lower() in name_lower for f in required)


def check_runbatch_activity(logs_client, log_group: str, lookback_minutes: int) -> dict:
    """runBatch.log: batch file/flag creation activity - lists every matching log line."""
    rows = _run_stream(
        logs_client, log_group, config.LOG_STREAMS["run_batch"], lookback_minutes,
        limit=50, message_filter="@message like /Creating/",
        fallback=True,
    )
    if not rows:
        return {"status": FAILED, "detail": "No 'Creating' activity found in runBatch.log"}

    messages = [row.get("@message", "") for row in rows]
    has_failure = any(keyword in m.lower() for m in messages for keyword in _FAILURE_KEYWORDS)
    plural = "y" if len(rows) == 1 else "ies"
    detail = f"{len(rows)} file/flag creation entr{plural} found"
    return {"status": FAILED if has_failure else HEALTHY, "detail": detail, "evidence": _evidence_lines(rows, limit=len(rows))}


def check_acq_success_flag(logs_client, log_group: str, lookback_minutes: int) -> dict:
    """runBatch.log: verify the acq_success flag file was created."""
    rows = _run_stream(
        logs_client, log_group, config.LOG_STREAMS["run_batch"], lookback_minutes,
        limit=5, message_filter="@message like /acq_success/",
        fallback=True,
    )
    if not rows:
        return {"status": FAILED, "detail": "No 'acq_success' flag activity found in runBatch.log"}

    messages = [row.get("@message", "") for row in rows]
    has_failure = any(keyword in m.lower() for m in messages for keyword in _FAILURE_KEYWORDS)
    latest = messages[0]
    match = re.search(r"(?i)(acq_success\S*\.flag)", latest)
    flag_name = match.group(1) if match else latest[:150]
    detail = f"Not Created - latest: {latest[:200]}" if has_failure else f"Created ({flag_name})"
    return {"status": FAILED if has_failure else HEALTHY, "detail": detail, "evidence": _evidence_lines(rows)}


def check_bad_records(logs_client, log_group: str, lookback_minutes: int) -> dict:
    """runBatch.log: search for 'BAD'-flagged entries over a wide (4-week) window - routine daily archiving, not a failure signal by itself."""
    rows = _run_stream(
        logs_client, log_group, config.LOG_STREAMS["run_batch"], lookback_minutes,
        limit=50, message_filter="@message like /BAD/",
    )
    if not rows:
        return {"status": HEALTHY, "detail": "No 'BAD' entries found in runBatch.log over the lookback window"}

    messages = [row.get("@message", "") for row in rows]
    has_failure = any(keyword in m.lower() for m in messages for keyword in _FAILURE_KEYWORDS)
    plural = "y" if len(rows) == 1 else "ies"
    detail = f"{len(rows)} 'BAD' entr{plural} found - latest: {messages[0][:200]}"
    return {"status": FAILED if has_failure else HEALTHY, "detail": detail, "evidence": _evidence_lines(rows, limit=len(rows))}


def check_rds_maintenance(session, all_regions: list[str], lookback_minutes: int) -> dict:
    """RDS DescribePendingMaintenanceActions (read-only) across every enabled region.

    Restricted to resources matching config.INFRA_NAME_FILTER just like check_rds_health.
    """
    name_filter = config.INFRA_NAME_FILTER
    pending = []
    for region in all_regions:
        rds = session.client("rds", region_name=region)
        try:
            paginator = rds.get_paginator("describe_pending_maintenance_actions")
            for page in paginator.paginate():
                for item in page.get("PendingMaintenanceActions", []):
                    resource_id = item.get("ResourceIdentifier", "unknown")
                    if not _name_matches(resource_id, name_filter):
                        continue
                    for action in item.get("PendingMaintenanceActionDetails", []):
                        pending.append(f"{resource_id} ({region}): {action.get('Action', 'unknown')} - notify stakeholders and schedule a maintenance window")
        except Exception:
            logger.exception("Failed to describe pending maintenance actions in %s", region)
            continue

    if not pending:
        return {"status": HEALTHY, "detail": "No pending maintenance actions on any RDS instance"}
    return {"status": WARNING, "detail": "; ".join(pending)[:500], "evidence": _evidence_lines(pending)}


def check_asg_health(session, all_regions: list[str], lookback_minutes: int) -> dict:
    """Discover Auto Scaling groups whose name matches config.INFRA_NAME_FILTER, across all regions."""
    name_filter = config.INFRA_NAME_FILTER
    groups = []
    for region in all_regions:
        client = session.client("autoscaling", region_name=region)
        try:
            paginator = client.get_paginator("describe_auto_scaling_groups")
            for page in paginator.paginate():
                for group in page.get("AutoScalingGroups", []):
                    if _name_matches(group.get("AutoScalingGroupName", ""), name_filter):
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
    """Discover EFS file systems whose Name tag matches config.INFRA_NAME_FILTER, across all regions."""
    name_filter = config.INFRA_NAME_FILTER
    file_systems = []
    for region in all_regions:
        client = session.client("efs", region_name=region)
        try:
            paginator = client.get_paginator("describe_file_systems")
            for page in paginator.paginate():
                for fs in page.get("FileSystems", []):
                    if _name_matches(fs.get("Name", ""), name_filter):
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


def check_ec2_health(session, all_regions: list[str], lookback_minutes: int) -> dict:
    """Per-instance EC2 health: state, system/instance status checks, AZ and live CPU, across all regions.

    Only instances whose Name tag matches config.INFRA_NAME_FILTER are considered.
    """
    name_filter = config.INFRA_NAME_FILTER
    instances = []
    for region in all_regions:
        ec2 = session.client("ec2", region_name=region)
        try:
            paginator = ec2.get_paginator("describe_instances")
            for page in paginator.paginate():
                for reservation in page.get("Reservations", []):
                    for instance in reservation.get("Instances", []):
                        name = next((t["Value"] for t in instance.get("Tags", []) if t.get("Key") == "Name"), instance["InstanceId"])
                        if _name_matches(name, name_filter):
                            instances.append((region, name, instance))
        except Exception:
            logger.exception("Failed to describe EC2 instances in %s", region)
            continue

    if not instances:
        return {"status": FAILED, "detail": f"No EC2 instances matching '{name_filter}' found"}

    # Group by region so describe_instance_status (region-scoped) is only called once per region.
    by_region: dict[str, list[tuple[str, dict]]] = {}
    for region, name, instance in instances:
        by_region.setdefault(region, []).append((name, instance))

    details = []
    unhealthy_total = 0
    for region, named_instances in by_region.items():
        ec2 = session.client("ec2", region_name=region)
        cloudwatch = session.client("cloudwatch", region_name=region)
        instance_ids = [instance["InstanceId"] for _name, instance in named_instances]

        statuses = {}
        try:
            paginator = ec2.get_paginator("describe_instance_status")
            for page in paginator.paginate(InstanceIds=instance_ids, IncludeAllInstances=True):
                for status in page.get("InstanceStatuses", []):
                    statuses[status["InstanceId"]] = status
        except Exception:
            logger.exception("Failed to describe instance status in %s", region)

        for name, instance in named_instances:
            instance_id = instance["InstanceId"]
            state = instance.get("State", {}).get("Name", "unknown")
            az = instance.get("Placement", {}).get("AvailabilityZone", region)
            status = statuses.get(instance_id, {})
            system_status = status.get("SystemStatus", {}).get("Status", "n/a")
            instance_status = status.get("InstanceStatus", {}).get("Status", "n/a")

            cpu = None
            try:
                end = datetime.now(timezone.utc)
                metrics = cloudwatch.get_metric_statistics(
                    Namespace="AWS/EC2", MetricName="CPUUtilization",
                    Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
                    StartTime=end - timedelta(minutes=15), EndTime=end,
                    Period=300, Statistics=["Average"],
                )
                datapoints = sorted(metrics.get("Datapoints", []), key=lambda d: d["Timestamp"])
                if datapoints:
                    cpu = datapoints[-1]["Average"]
            except Exception:
                logger.exception("Failed to fetch CPUUtilization for %s in %s", instance_id, region)

            healthy = state == "running" and system_status == "ok" and instance_status == "ok"
            if not healthy:
                unhealthy_total += 1
            cpu_text = f"{cpu:.1f}%" if cpu is not None else "N/A"
            details.append(
                f"{name}: state={state} | system={system_status} | instance={instance_status} | "
                f"az={az} | cpu={cpu_text} ({'HEALTHY' if healthy else 'UNHEALTHY'})"
            )

    status = HEALTHY if unhealthy_total == 0 else FAILED
    return {"status": status, "detail": "; ".join(details)[:500], "evidence": details}


def check_rds_health(session, all_regions: list[str], lookback_minutes: int) -> dict:
    """Per-instance RDS health: engine, status, multi-AZ and storage utilization, across all regions.

    Only DB instances whose identifier matches config.INFRA_NAME_FILTER are considered.
    """
    name_filter = config.INFRA_NAME_FILTER
    db_instances = []
    for region in all_regions:
        rds = session.client("rds", region_name=region)
        try:
            paginator = rds.get_paginator("describe_db_instances")
            for page in paginator.paginate():
                for db in page.get("DBInstances", []):
                    if _name_matches(db.get("DBInstanceIdentifier", ""), name_filter):
                        db_instances.append((region, db))
        except Exception:
            logger.exception("Failed to describe RDS instances in %s", region)
            continue

    if not db_instances:
        return {"status": FAILED, "detail": f"No RDS instances matching '{name_filter}' found"}

    details = []
    unhealthy_total = 0
    for region, db in db_instances:
        identifier = db.get("DBInstanceIdentifier", "")
        engine = db.get("Engine", "unknown")
        status = db.get("DBInstanceStatus", "unknown")
        multi_az = db.get("MultiAZ", False)
        allocated_gb = db.get("AllocatedStorage", 0)

        storage_used_pct = None
        if allocated_gb:
            try:
                cloudwatch = session.client("cloudwatch", region_name=region)
                end = datetime.now(timezone.utc)
                metrics = cloudwatch.get_metric_statistics(
                    Namespace="AWS/RDS", MetricName="FreeStorageSpace",
                    Dimensions=[{"Name": "DBInstanceIdentifier", "Value": identifier}],
                    StartTime=end - timedelta(minutes=30), EndTime=end,
                    Period=300, Statistics=["Average"],
                )
                datapoints = sorted(metrics.get("Datapoints", []), key=lambda d: d["Timestamp"])
                if datapoints:
                    free_bytes = datapoints[-1]["Average"]
                    allocated_bytes = allocated_gb * (1024 ** 3)
                    storage_used_pct = (allocated_bytes - free_bytes) / allocated_bytes * 100
            except Exception:
                logger.exception("Failed to fetch FreeStorageSpace for %s in %s", identifier, region)

        healthy = status == "available"
        if not healthy:
            unhealthy_total += 1
        storage_text = f"{storage_used_pct:.1f}%" if storage_used_pct is not None else "N/A"
        details.append(
            f"{identifier}: engine={engine} | status={status} | region={region} | "
            f"multi_az={multi_az} | storage_used={storage_text} | health={'HEALTHY' if healthy else 'UNHEALTHY'}"
        )

    status = HEALTHY if unhealthy_total == 0 else FAILED
    return {"status": status, "detail": "; ".join(details)[:500], "evidence": details}


CHECK_FUNCTIONS = {
    "check_runbatch_activity": check_runbatch_activity,
    "check_acq_success_flag": check_acq_success_flag,
    "check_bad_records": check_bad_records,
    "check_rds_maintenance": check_rds_maintenance,
    "check_asg_health": check_asg_health,
    "check_efs_health": check_efs_health,
    "check_ec2_health": check_ec2_health,
    "check_rds_health": check_rds_health,
}
