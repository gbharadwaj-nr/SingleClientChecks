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
        "category": "Infra Checks",
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
        "category": "Infra Checks",
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
        "category": "Infra Checks",
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
        # Maps to the "AML Batch Monitoring" dashboard widget.
        "name": "AML Batch",
        "category": "Infra Checks",
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
        # Maps to the "runBatch.log" batch instance log stream (acq_success flag creation).
        "name": "ACQ Success Flag",
        "category": "Batch Processing",
        "log_group": LOG_GROUPS["application"],
        "query": (
            "fields @message\n"
            "| filter @logStream like /runBatch.log/\n"
            "| filter @message like /acq_success/\n"
            "| sort @timestamp desc\n"
            "| limit 5"
        ),
        "detail_regex": r"(?i)(acq_success_\S+?\.flag)",  # flag file name, e.g. acq_success_20260812.flag
        "detail_target": "status",  # shown as "Created (acq_success_20260812.flag)"
        "success_label": "Created",
        "failure_label": "Not Created",
    },
    {
        # Maps to the "runBatch.log" batch instance log stream (aml_success flag creation).
        "name": "AML Success Flag",
        "category": "Batch Processing",
        "log_group": LOG_GROUPS["application"],
        "query": (
            "fields @message\n"
            "| filter @logStream like /runBatch.log/\n"
            "| filter @message like /aml_success/\n"
            "| sort @timestamp desc\n"
            "| limit 5"
        ),
        "detail_regex": r"(?i)(aml_success_\S+?\.flag)",  # flag file name, e.g. aml_success_20260812.flag
        "detail_target": "status",  # shown as "Created (aml_success_20260812.flag)"
        "success_label": "Created",
        "failure_label": "Not Created",
    },
    {
        # Maps to the "runBatch.log" batch instance log stream (NetReveal BAD file copy/flag creation).
        "name": "Bad Records Flag",
        "category": "Batch Processing",
        "log_group": LOG_GROUPS["application"],
        "query": (
            "fields @message\n"
            "| filter @logStream like /runBatch.log/\n"
            "| filter @message like /BAD/\n"
            "| sort @timestamp desc\n"
            "| limit 5"
        ),
        "detail_regex": r"(NetReveal_BAD_\S+?\.ZIP)",  # bad-file name, e.g. NetReveal_BAD_20260812.ZIP
        "detail_target": "status",  # shown as "Created (NetReveal_BAD_20260812.ZIP)"
        "success_label": "Created",
        "failure_label": "Not Created",
    },
]
