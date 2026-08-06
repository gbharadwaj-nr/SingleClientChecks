"""Client-specific configuration for FleetCor AWS Daily Health Check."""

from bootstrap import CLIENTS, ROLE_NAME  # noqa: E402

CLIENT_NAME = "FleetCor"
CLIENT_LOGO = "symphonyai-logo.png"

# Real account ID and IAM role, sourced from DailyChecksFramework/config.py.
AWS_ACCOUNT_ID = CLIENTS["FleetCor"]["account_id"]
AWS_ROLE_NAME = ROLE_NAME
AWS_REGION = "us-east-1"

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
        "name": "DXV",
        "category": "System Checks",
        "log_group": None,  # TODO: log group + query to be provided
        "query": None,
        "success_label": "Available",
        "failure_label": "Unavailable",
    },
    {
        "name": "AML Batch",
        "category": "System Checks",
        "log_group": None,  # TODO: log group + query to be provided
        "query": None,
        "success_label": "Completed",
        "failure_label": "Failed",
    },
    {
        "name": "Batch Files",
        "category": "Batch Process",
        "log_group": None,  # TODO: log group + query to be provided
        "query": None,
        "success_label": "Completed",
        "failure_label": "Failed",
    },
    {
        "name": "Bad Records",
        "category": "Feedback Files",
        "log_group": None,  # TODO: log group + query to be provided
        "query": None,
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
        "success_label": "Sent",
        "failure_label": "Not Sent",
    },
]
