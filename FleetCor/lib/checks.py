"""AWS-API-based health checks for FleetCor (no CloudWatch Logs Insights involved).

Each function queries an AWS API directly across every active region and returns the
same (status_label, passed, detail) shape as lib.logs_insights-driven checks in main.py,
so main.py's evaluate_check() can dispatch to either kind interchangeably.
"""

import logging

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


# Maps config.CHECKS[i]["func"] (a string) to the actual function.
CHECK_FUNCTIONS = {
    "check_asg_health": check_asg_health,
    "check_efs_health": check_efs_health,
}
