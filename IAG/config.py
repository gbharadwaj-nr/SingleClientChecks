"""Client-specific configuration for IAG AWS Daily Health Check."""

from bootstrap import ROLE_NAME  # noqa: E402

CLIENT_NAME = "IAG"
CLIENT_LOGO = "symphonyai-logo.svg"

# NOTE: account 616476889381 is NOT bootstrap.CLIENTS["IAG"] (that entry is a different,
# pre-existing client account: 402366105298). It's the same account already used by MGL/LFS.
# Per the user, this is intentional/separate - hardcoded here instead of touching bootstrap.py's
# CLIENTS dict to avoid breaking any of the existing mappings.
AWS_ACCOUNT_ID = "616476889381"
AWS_ROLE_NAME = ROLE_NAME
# No fixed region: main.py searches all enabled regions to find each log group.

OUTPUT_DIR = "output"
REPORT_FILENAME = "report.html"

# CloudWatch Logs log group used by the Application checks.
LOG_GROUPS = {
    "application": "iag-production-ApplicationLogs-OXmQcqtZLrnN",
}

# Specific log streams used by the per-stream checks in lib/checks.py.
LOG_STREAMS = {
    # Bare filenames, NOT full instance paths - the batch EC2 instance gets replaced/
    # autoscaled over time, and _run_stream()'s `@logStream like "text"` substring match
    # keeps matching any instance's stream as long as the filename itself is right.
    "application_batch": "application.log",
    "run_batch": "runBatch.log",
}

# How far back each Logs Insights query should look.
QUERY_LOOKBACK_MINUTES = 1440  # 24 hours

# Substrings (case-insensitive, ALL must be present) used by the EC2/RDS/ASG/EFS Infra Checks
# to find IAG's production resources - e.g. "iag-production-compute...".
INFRA_NAME_FILTER = ("iag", "production")

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
    {"name": "ACQ Success Flag", "category": "Application", "func": "check_acq_success_flag", "log_group": "application"},
    {"name": "RunBatch Activity", "category": "Application", "func": "check_runbatch_activity", "log_group": "application"},
    {"name": "Failure Flag", "category": "Application", "func": "check_acq_failure_flag", "log_group": "application", "lookback_minutes": 1440},
    {"name": "Bad Records", "category": "Application", "func": "check_bad_records", "log_group": "application"},
]
