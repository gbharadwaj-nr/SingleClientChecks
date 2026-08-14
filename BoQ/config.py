"""Client-specific configuration for BoQ AWS Daily Health Check."""

from bootstrap import CLIENTS, ROLE_NAME  # noqa: E402

CLIENT_NAME = "BoQ"
CLIENT_LOGO = "symphonyai-logo.svg"

# Real account ID and IAM role, sourced from bootstrap.py's CLIENTS dict.
AWS_ACCOUNT_ID = CLIENTS["BoQ"]["account_id"]
AWS_ROLE_NAME = ROLE_NAME
# No fixed region: main.py searches all enabled regions to find each log group.

OUTPUT_DIR = "output"
REPORT_FILENAME = "report.html"

# CloudWatch Logs log group used by the Application checks.
LOG_GROUPS = {
    "application": "boq9-production-ApplicationLogs-ba8QYe1dCaKe",
}

# Specific log streams used by the per-stream checks in lib/checks.py.
LOG_STREAMS = {
    # Factiva Import (application.log) and RunBatch Activity (runBatch.log), same batch instance.
    "application_batch": "batch/i-03d590ed2babde8e7/batch/application.log",
    "run_batch": "batch/i-03d590ed2babde8e7/batch/runBatch.log",
}

# How far back each Logs Insights query should look.
QUERY_LOOKBACK_MINUTES = 1440  # 24 hours

# Substrings (case-insensitive, ALL must be present) used by the EC2/RDS/ASG/EFS Infra Checks
# to find BoQ's production resources - e.g. "boq9-production-compute...".
INFRA_NAME_FILTER = ("boq", "production")

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
    {"name": "Factiva Import", "category": "Application", "func": "check_factiva_import", "log_group": "application"},
    {"name": "RunBatch Activity", "category": "Application", "func": "check_runbatch_activity", "log_group": "application"},
]
