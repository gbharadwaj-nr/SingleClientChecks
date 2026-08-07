"""Client-specific configuration for BHFS AWS Daily Health Check."""

from bootstrap import CLIENTS, ROLE_NAME  # noqa: E402

CLIENT_NAME = "BHFS"
CLIENT_LOGO = "symphonyai-logo.svg"

AWS_ACCOUNT_ID = CLIENTS["BHFS"]["account_id"]
AWS_ROLE_NAME = ROLE_NAME
# No fixed region: main.py searches all enabled regions to find each log group.

OUTPUT_DIR = "output"
REPORT_FILENAME = "report.html"

# CloudWatch Logs log groups used by the health checks.
# TODO: confirm the exact "application" log group name in the BHFS account - this is a placeholder.
LOG_GROUPS = {
    "application": "bhfs-production-ApplicationLogs-uu5ZxF4Mn8aS",
    "ui": "/aws/lambda/bhfsproductionUIAvailabilityCheck",
}

# Restricts every query below to the log streams that carry BHFS batch/application activity.
LOG_STREAM_FILTER = "(@logStream like /norkom.log/ or @logStream like /application.log/)"

# Specific log streams used by the per-stream checks in lib/checks.py.
LOG_STREAMS = {
    "norkom": "norkom.log",
    "application": "application.log",
    "aml_batch": "aml_batch_monitoring.log",
    "wlm_batch": "wlm_batch_monitoring.log",
    "cdd_batch": "cdd_batch_monitoring.log",
    "acq_success": "check_acq_success.log",
    "bad_files": "check_bad_files.log",
    "ec2_status": "check_ec2_status.log",
    "rds_status": "check_rds_status.log",
}

# How far back each Logs Insights query should look.
QUERY_LOOKBACK_MINUTES = 1440  # 24 hours

# Assumed thresholds (not yet confirmed with the client) for the stats-based checks below.
# Adjust once real SLAs/latency targets for BHFS are known.
API_LATENCY_WARNING_MS = 1000.0
API_LATENCY_FAILED_MS = 3000.0
UI_AVAILABILITY_WARNING_PCT = 95.0

# Each entry wires a check's independent function (lib/checks.py) into the report.
# category groups rows into report sections; log_group is a key into LOG_GROUPS (defaults to
# "application" in main.py if omitted); func(logs_client, log_group, lookback_minutes) must
# return {"status": "Healthy"|"Warning"|"Failed", "detail": str}.
CHECKS = [
    {"name": "EC2 Instance Health", "category": "System Checks", "func": "check_ec2_status", "log_group": "application"},
    {"name": "RDS Database Health", "category": "System Checks", "func": "check_rds_status", "log_group": "application"},
    {"name": "UI Availability", "category": "System Checks", "func": "check_ui_availability", "log_group": "ui", "lookback_minutes": 180},
    {"name": "Factiva Import", "category": "Batch & File Processing", "func": "check_factiva_import"},
    {"name": "Envelope Processing", "category": "Batch & File Processing", "func": "check_envelope_processing"},
    {"name": "AML Batch", "category": "Batch & File Processing", "func": "check_aml_batch"},
    {"name": "WLM Batch", "category": "Batch & File Processing", "func": "check_wlm_batch"},
    {"name": "CDD Batch", "category": "Batch & File Processing", "func": "check_cdd_batch"},
    {"name": "ACQ Success", "category": "Batch & File Processing", "func": "check_acq_success"},
    {"name": "Transaction File", "category": "Batch & File Processing", "func": "check_transaction_file"},
    {"name": "Bad Files", "category": "Feedback Files", "func": "check_bad_files"},
    {"name": "Application Errors & Notifications", "category": "Error Monitoring", "func": "check_application_log"},
    {"name": "Real-Time API Latency", "category": "Real-Time Processing", "func": "check_api_latency"},
    {"name": "Real-Time Processing", "category": "Real-Time Processing", "func": "check_realtime_processing"},
]

