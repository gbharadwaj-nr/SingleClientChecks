"""Client-specific configuration for MGL AWS Daily Health Check."""

import os

from bootstrap import ROLE_NAME  # noqa: E402

CLIENT_NAME = "MGL"
CLIENT_LOGO = "symphonyai-logo.svg"

# NOTE: account 616476889381 is NOT bootstrap.CLIENTS["MGL"] (that entry is a different,
# pre-existing client account: 984546913585). It's also the same account already used by
# CLIENTS["LFS"]. Per the user, this is intentional/separate from both - hardcoded here
# instead of touching bootstrap.py's CLIENTS dict to avoid breaking either existing mapping.
AWS_ACCOUNT_ID = "616476889381"
AWS_ROLE_NAME = ROLE_NAME
# No fixed region: main.py searches all enabled regions to find each log group.

OUTPUT_DIR = "output"
REPORT_FILENAME = "report.html"

# CloudWatch Logs log groups used by the health checks.
LOG_GROUPS = {
    "application": "mgl-production-ApplicationLogs-1GIG4IOL2HSFZ",
    "ui": "/aws/lambda/mglproductionUIAvailabilityCheck",
}

# Specific log streams used by the per-stream checks in lib/checks.py.
LOG_STREAMS = {
    # World-Check Import (norkom.log) and RunBatch Activity (runBatch.log) - current batch instance.
    "norkom": "batch/i-076c46db2a038991c/batch/norkom.log",
    "run_batch": "batch/i-076c46db2a038991c/batch/runBatch.log",
}

# How far back each Logs Insights query should look.
QUERY_LOOKBACK_MINUTES = 1440  # 24 hours, matches START=-86400s in the reference console queries

# Database Validation (SERVER_STATES check) connection settings - sourced from environment
# variables only, never hardcoded. If unset, lib/db_check.py reports "Warning: Not Configured"
# instead of failing. Set these as Jenkins secret-bound env vars once real DB access is available.
DB_ENGINE = os.environ.get("MGL_DB_ENGINE", "postgres")  # "postgres" or "mysql"
DB_HOST = os.environ.get("MGL_DB_HOST")
DB_PORT = os.environ.get("MGL_DB_PORT")
DB_NAME = os.environ.get("MGL_DB_NAME")
DB_USER = os.environ.get("MGL_DB_USER")
DB_PASSWORD = os.environ.get("MGL_DB_PASSWORD")

# Substrings (case-insensitive, ALL must be present) used by the EC2/RDS/ASG/EFS Infra Checks
# to find MGL's production resources - e.g. "mgl-production-compute...".
INFRA_NAME_FILTER = ("mgl", "production")

# Each entry wires a check's independent function (lib/checks.py) into the report.
# category groups rows into report sections - every client standardizes on exactly two:
# "Infra Checks" (EC2/RDS/UI/ASG/EFS - same across all clients) and "Application" (everything
# client-specific: batch jobs, file feeds, etc). "kind" picks how main.py calls func():
#   "logs" (default)  -> func(logs_client, log_group, lookback_minutes); needs "log_group" key
#   "aws_session"     -> func(session, all_regions, lookback_minutes); direct AWS API calls
#   "standalone"      -> func(lookback_minutes); no AWS calls at all (e.g. a DB connection)
# All must return {"status": "Healthy"|"Warning"|"Failed", "detail": str}.
CHECKS = [
    {"name": "UI Availability", "category": "Infra Checks", "func": "check_ui_availability", "log_group": "ui", "lookback_minutes": 180},
    {"name": "EC2 Instances", "category": "Infra Checks", "func": "check_ec2_health", "kind": "aws_session"},
    {"name": "RDS", "category": "Infra Checks", "func": "check_rds_health", "kind": "aws_session"},
    {"name": "RDS Pending Maintenance", "category": "Infra Checks", "func": "check_rds_maintenance", "kind": "aws_session"},
    {"name": "ASG Health", "category": "Infra Checks", "func": "check_asg_health", "kind": "aws_session"},
    {"name": "EFS Health", "category": "Infra Checks", "func": "check_efs_health", "kind": "aws_session"},
    {"name": "World-Check Import", "category": "Application", "func": "check_worldcheck_import", "log_group": "application"},
    {"name": "RunBatch Activity", "category": "Application", "func": "check_runbatch_activity", "log_group": "application"},
    # Database Validation is disabled until real MGL_DB_* connection details are provided -
    # re-add {"name": "Database Validation", "category": "Application", "func": "check_database_validation",
    # "kind": "standalone"} once they're configured (lib/db_check.py is still ready to use).
]
