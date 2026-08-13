"""AWS-API-based health checks for FleetCor (no CloudWatch Logs Insights involved).

Each function queries an AWS API directly across every active region and returns the
same (status_label, passed, detail) shape as lib.logs_insights-driven checks in main.py,
so main.py's evaluate_check() can dispatch to either kind interchangeably.
"""

import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


def check_asg_health(session, all_regions: list[str], name_filter: str) -> tuple[str, bool, str | None]:
    """Discover Auto Scaling groups whose name contains `name_filter`, across all regions."""
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
        return "Not Found", False, f"No Auto Scaling groups matching '{name_filter}' found"

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

    passed = unhealthy_total == 0
    return ("Healthy" if passed else "Unhealthy"), passed, "; ".join(details)


def check_efs_health(session, all_regions: list[str], name_filter: str) -> tuple[str, bool, str | None]:
    """Discover EFS file systems whose Name tag contains `name_filter`, across all regions."""
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
        return "Not Found", False, f"No EFS file systems matching '{name_filter}' found"

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

    passed = unavailable_total == 0
    return ("Healthy" if passed else "Unhealthy"), passed, "; ".join(details)


def check_ec2_health(session, all_regions: list[str], name_filter: str) -> tuple[str, bool, str | None]:
    """Per-instance EC2 health: state, system/instance status checks, AZ and live CPU, across all regions.

    Only instances whose Name tag contains `name_filter` are considered.
    """
    instances = []
    for region in all_regions:
        ec2 = session.client("ec2", region_name=region)
        try:
            paginator = ec2.get_paginator("describe_instances")
            for page in paginator.paginate():
                for reservation in page.get("Reservations", []):
                    for instance in reservation.get("Instances", []):
                        name = next((t["Value"] for t in instance.get("Tags", []) if t.get("Key") == "Name"), instance["InstanceId"])
                        if name_filter.lower() in name.lower():
                            instances.append((region, name, instance))
        except Exception:
            logger.exception("Failed to describe EC2 instances in %s", region)
            continue

    if not instances:
        return "Not Found", False, f"No EC2 instances matching '{name_filter}' found"

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

    passed = unhealthy_total == 0
    return ("Healthy" if passed else "Unhealthy"), passed, "; ".join(details)


def check_rds_health(session, all_regions: list[str], name_filter: str) -> tuple[str, bool, str | None]:
    """Per-instance RDS health: engine, status, multi-AZ and storage utilization, across all regions.

    Only DB instances whose identifier contains `name_filter` are considered.
    """
    db_instances = []
    for region in all_regions:
        rds = session.client("rds", region_name=region)
        try:
            paginator = rds.get_paginator("describe_db_instances")
            for page in paginator.paginate():
                for db in page.get("DBInstances", []):
                    if name_filter.lower() in db.get("DBInstanceIdentifier", "").lower():
                        db_instances.append((region, db))
        except Exception:
            logger.exception("Failed to describe RDS instances in %s", region)
            continue

    if not db_instances:
        return "Not Found", False, f"No RDS instances matching '{name_filter}' found"

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

    passed = unhealthy_total == 0
    return ("Healthy" if passed else "Unhealthy"), passed, "; ".join(details)


# Maps config.CHECKS[i]["func"] (a string) to the actual function.
CHECK_FUNCTIONS = {
    "check_asg_health": check_asg_health,
    "check_efs_health": check_efs_health,
    "check_ec2_health": check_ec2_health,
    "check_rds_health": check_rds_health,
}
