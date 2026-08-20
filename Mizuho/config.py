"""Client-specific configuration for Mizuho AWS Daily Health Check."""

from bootstrap import CLIENTS, ROLE_NAME  # noqa: E402

CLIENT_NAME = "Mizuho"
CLIENT_LOGO = "symphonyai-logo.svg"

# Real account ID and IAM role, sourced from bootstrap.py's CLIENTS dict.
AWS_ACCOUNT_ID = CLIENTS["Mizuho"]["account_id"]
AWS_ROLE_NAME = ROLE_NAME
# No fixed region: main.py searches all enabled regions to find each log group.

OUTPUT_DIR = "output"
REPORT_FILENAME = "report.html"

# CloudWatch Logs log group used by the Application checks.
LOG_GROUPS = {
    "application": "mizuho-production-ApplicationLogs-93UNAQK0BVEo",
}

# Specific log streams used by the per-stream checks in lib/checks.py.
LOG_STREAMS = {
    # Bare filename, NOT a full instance path - the batch EC2 instance gets replaced/
    # autoscaled over time, and _run_stream()'s `@logStream like "text"` substring match
    # keeps matching any instance's stream as long as the filename itself is right.
    "initiate_pipeline": "initiatePipeline.log",
}

# How far back each Logs Insights query should look.
QUERY_LOOKBACK_MINUTES = 1440  # 24 hours

# Substrings (case-insensitive, ALL must be present) used by the EC2/RDS/ASG/EFS Infra Checks
# to find Mizuho's production resources - e.g. "mizuho-production-compute...".
INFRA_NAME_FILTER = ("mizuho", "production")

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
    # 2-day lookback (vs the default 24h) so weekend/off-day gaps in pipeline activity don't get flagged.
    {"name": "Pipeline", "category": "Application", "func": "check_pipeline", "log_group": "application", "lookback_minutes": 1440},
]
