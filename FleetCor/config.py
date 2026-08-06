"""Client-specific configuration for FleetCor AWS Daily Health Check."""

from bootstrap import CLIENTS, ROLE_NAME  # noqa: E402

CLIENT_NAME = "FleetCor"
CLIENT_LOGO = "symphonyai-logo.svg"

# Real account ID and IAM role, sourced from DailyChecksFramework/config.py.
AWS_ACCOUNT_ID = CLIENTS["FleetCor"]["account_id"]
AWS_ROLE_NAME = ROLE_NAME
# No fixed region: main.py searches all enabled regions to find each log group.

OUTPUT_DIR = "output"
REPORT_FILENAME = "report.html"

# CloudWatch Logs log groups used by the health checks.
LOG_GROUPS = {
    "application": "fltcr-production-ApplicationLogs-t0L7QoJyJRKY",
    "ui": "/aws/lambda/fltcrproductionUIAvailabilityCheck",
}

# How far back each Logs Insights query should look.
QUERY_LOOKBACK_MINUTES = 1440  # 24 hours

# Each entry defines one health check: which log group/query to run and the labels
# to print on success/failure. Set "query" (and/or "log_group") to None for checks
# that aren't wired up yet - they are reported as "Not Configured" until added.
CHECKS = [
    {
        "name": "RDS",
        "category": "System Checks",
        "log_group": LOG_GROUPS["application"],
        "query": (
            "fields @message\n"
            "| filter @logStream like /check_rds_status.log/\n"
            "| sort @timestamp desc\n"
            "| limit 2"
        ),
        "success_label": "Available",
        "failure_label": "Unavailable",
    },
    {
        "name": "EC2 Instances",
        "category": "System Checks",
        "log_group": LOG_GROUPS["application"],
        "query": (
            "fields @message\n"
            "| filter @logStream like /check_ec2_status.log/\n"
            "| sort @timestamp desc\n"
            "| limit 3"
        ),
        "success_label": "Available",
        "failure_label": "Unavailable",
    },
    {
        "name": "UI",
        "category": "System Checks",
        "log_group": LOG_GROUPS["ui"],
        "query": (
            "fields @message\n"
            "| filter @message like /Check result/\n"
            "| fields strcontains(@message, \"SUCCESS\") as @success,\n"
            "         strcontains(@message, \"FAIL\") as @fail\n"
            "| stats sum(@success) as UI_Is_Up_Count, sum(@fail) as UI_Is_Down_Count, "
            "sum(@success) / (sum(@fail) + sum(@success)) * 100 as UI_Availability_Percentage"
        ),
        "lookback_minutes": 180,  # matches START=-10800s in the original console query
        "result_type": "stats",
        "stats_field": "UI_Availability_Percentage",
        "stats_threshold": 100.0,
        "success_label": "Available",
        "failure_label": "Unavailable",
    },
    {
        # Maps to the "DXV - Acquisition Success Files" dashboard widget.
        "name": "DXV",
        "category": "System Checks",
        "log_group": LOG_GROUPS["application"],
        "query": (
            "fields @message\n"
            "| filter @logStream like /check_acq_success.log/\n"
            "| sort @timestamp desc\n"
            "| limit 6"
        ),
        "lookback_minutes": 10080,  # matches START=-604800s (7 days) in the original console query
        "success_label": "Available",
        "failure_label": "Unavailable",
    },
    {
        # Maps to the "AML Batch Monitoring" dashboard widget.
        "name": "AML Batch",
        "category": "System Checks",
        "log_group": LOG_GROUPS["application"],
        "query": (
            "fields @message\n"
            "| filter @logStream like /aml_batch_monitoring.log/\n"
            "| sort @timestamp desc\n"
            "| limit 5"
        ),
        "lookback_minutes": 180,  # matches START=-10800s (3 hours) in the original console query
        "success_label": "Completed",
        "failure_label": "Failed",
    },
    {
        # Maps to the "WLM Batch Monitoring" dashboard widget.
        "name": "Batch Files",
        "category": "Batch Process",
        "log_group": LOG_GROUPS["application"],
        "query": (
            "fields @message\n"
            "| filter @logStream like /wlm_batch_monitoring.log/\n"
            "| sort @timestamp desc\n"
            "| limit 10"
        ),
        "lookback_minutes": 10080,  # matches START=-604800s (7 days) in the original console query
        "detail_regex": r"(\d{8})\s*\|",  # batch date before the first '|' field separator
        "detail_target": "name",  # shown as "Batch Files (20260805)"
        "success_label": "Completed",
        "failure_label": "Failed",
    },
    {
        # Maps to the "DXV - BAD Files" dashboard widget.
        "name": "Bad Records",
        "category": "Feedback Files",
        "log_group": LOG_GROUPS["application"],
        "query": (
            "fields @message\n"
            "| filter @logStream like /check_bad_files.log/\n"
            "| sort @timestamp desc\n"
            "| limit 20"
        ),
        "lookback_minutes": 10080,  # matches START=-604800s (7 days) in the original console query
        "detail_regex": r"(NetReveal_BAD_\d+\.ZIP)",  # bad-file name, e.g. NetReveal_BAD_20260805.ZIP
        "detail_target": "status",  # shown as "Sent (NetReveal_BAD_20260805.ZIP)"
        "success_label": "Sent",
        "failure_label": "Not Sent",
    },
    {
        "name": "ACQ Flags",
        "category": "Feedback Files",
        "log_group": LOG_GROUPS["application"],
        "query": (
            "fields @message\n"
            "| filter @logStream like /check_acq_success.log/\n"
            "| sort @timestamp desc\n"
            "| limit 6"
        ),
        "detail_regex": r"(?i)(acq_success_\S+)",  # flag file name, e.g. acq_success_20260805.flag
        "detail_target": "status",  # shown as "Sent (acq_success_20260805.flag)"
        "success_label": "Sent",
        "failure_label": "Not Sent",
    },
]
