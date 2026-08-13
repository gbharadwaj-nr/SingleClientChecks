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
    # Shared by Index Rebuild Completion and WLM Status (index-completion half).
    "norkom": "batch/i-0a1a72b531032dc24/batch/norkom.log",
    # Envelope Processing.
    "poll_dxv_landing": "dmz-/i-078d2fff05b048af1/pollDXVLanding.log",
    # Batch Status / Acquisition Status / WLM Status (start-order half).
    "get_dxv_landing_files": "batch/i-0a1a72b531032dc24/batch/getDXVLandingFiles.log",
    # WorldCheck Daily Download / WLM Status (direct "WLM Batch Success" line). Bare filename
    # (not the full instance-specific path) so it still matches if the EC2 instance ID changes.
    "run_batch": "runBatch.log",
    # RDS Status.
    "rds_status": "check_rds_status.log",
    # EC2 Instance Health.
    "ec2_status": "check_ec2_status.log",
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

# Substring match (case-insensitive) used by the ASG/EFS Infra Checks to find production resources.
INFRA_NAME_FILTER = "production"

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
    {"name": "EC2 Instance Health", "category": "Infra Checks", "func": "check_ec2_status", "log_group": "application", "lookback_minutes": 180},
    {"name": "RDS Status", "category": "Infra Checks", "func": "check_rds_status", "log_group": "application", "lookback_minutes": 180},
    {"name": "RDS Pending Maintenance", "category": "Infra Checks", "func": "check_rds_maintenance", "kind": "aws_session"},
    {"name": "ASG Health", "category": "Infra Checks", "func": "check_asg_health", "kind": "aws_session"},
    {"name": "EFS Health", "category": "Infra Checks", "func": "check_efs_health", "kind": "aws_session"},
    {"name": "WorldCheck Download", "category": "Application", "func": "check_worldcheck_download", "log_group": "application"},
    {"name": "Index Rebuild Status", "category": "Application", "func": "check_index_rebuild", "log_group": "application"},
    {"name": "Envelope Processing", "category": "Application", "func": "check_envelope_processing", "log_group": "application"},
    {"name": "Batch Status", "category": "Application", "func": "check_batch_status", "log_group": "application"},
    {"name": "Acquisition Status", "category": "Application", "func": "check_acquisition_status", "log_group": "application"},
    {"name": "WLM Status", "category": "Application", "func": "check_wlm_status", "log_group": "application", "lookback_minutes": 720},
    # Database Validation is disabled until real MGL_DB_* connection details are provided -
    # re-add {"name": "Database Validation", "category": "Application", "func": "check_database_validation",
    # "kind": "standalone"} once they're configured (lib/db_check.py is still ready to use).
]
