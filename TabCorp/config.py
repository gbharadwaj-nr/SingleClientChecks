"""Client-specific configuration for TabCorp AWS Daily Health Check."""

from bootstrap import CLIENTS, ROLE_NAME  # noqa: E402

CLIENT_NAME = "TabCorp"
CLIENT_LOGO = "symphonyai-logo.svg"

# Real account ID and IAM role, sourced from bootstrap.py's CLIENTS dict.
AWS_ACCOUNT_ID = CLIENTS["TabCorp"]["account_id"]
AWS_ROLE_NAME = ROLE_NAME
# No fixed region: main.py searches all enabled regions to find each log group.

OUTPUT_DIR = "output"
REPORT_FILENAME = "report.html"

# CloudWatch Logs log group used by the Application checks.
LOG_GROUPS = {
    "application": "tabcorp-production-ApplicationLogs-gZto273i92Ko",
}

# Specific log streams used by the per-stream checks in lib/checks.py.
LOG_STREAMS = {
    # World-Check Import (application.log) and RunBatch Activity (runBatch.log), same batch instance.
    "application_batch": "batch/i-0ecd19d24e01a9f9e/batch/application.log",
    "run_batch": "batch/i-0ecd19d24e01a9f9e/batch/runBatch.log",
}

# How far back each Logs Insights query should look.
QUERY_LOOKBACK_MINUTES = 1440  # 24 hours

# Substrings (case-insensitive, ALL must be present) used by the EC2/RDS/ASG/EFS Infra Checks
# to find TabCorp's production resources - e.g. "tabcorp-production-compute...".
INFRA_NAME_FILTER = ("tabcorp", "production")

# Each entry wires a check's independent function (lib/checks.py) into the report.
# category groups rows into report sections - every client standardizes on exactly two:
# "Infra Checks" (EC2/RDS/ASG/EFS - same across all clients) and "Application" (everything
# client-specific: batch jobs, file feeds, etc). "kind" picks how main.py calls func():
#   "logs" (default)  -> func(logs_client, log_group, lookback_minutes); needs "log_group" key
#   "aws_session"     -> func(session, all_regions, lookback_minutes); direct AWS API calls
# All must return {"status": "Healthy"|"Warning"|"Failed", "detail": str}.
CHECKS = [
    {"name": "EC2 Instances", "category": "Infra Checks", "func": "check_ec2_health", "kind": "aws_session"},
    {"name": "RDS", "category": "Infra Checks", "func": "check_rds_health", "kind": "aws_session"},
    {"name": "RDS Pending Maintenance", "category": "Infra Checks", "func": "check_rds_maintenance", "kind": "aws_session"},
    {"name": "ASG Health", "category": "Infra Checks", "func": "check_asg_health", "kind": "aws_session"},
    {"name": "EFS Health", "category": "Infra Checks", "func": "check_efs_health", "kind": "aws_session"},
    {"name": "World-Check Import", "category": "Application", "func": "check_worldcheck_import", "log_group": "application"},
    {"name": "RunBatch Activity", "category": "Application", "func": "check_runbatch_activity", "log_group": "application"},
    {"name": "ACQ Success Flag", "category": "Application", "func": "check_acq_success_flag", "log_group": "application"},
    {"name": "Bad Records", "category": "Application", "func": "check_bad_records", "log_group": "application"},
]
