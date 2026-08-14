"""
Mizuho AWS Daily Health Check.

Runs a set of independent checks - EC2/RDS/ASG/EFS (direct AWS API calls) plus Pipeline
(CloudWatch Logs Insights against a specific log stream) - prints a console health
report, and renders the same standard client HTML report used by the other client
folders.

Each check is an independent function in lib/checks.py returning a Healthy/Warning/Failed
status plus a detail string. Add new checks by adding a function there and an entry to
config.CHECKS - no other code changes are required.
"""

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

import config
from bootstrap import bootstrap, list_all_regions
from lib.checks import CHECK_FUNCTIONS
from lib.html_report import render_report
from lib.logs_insights import find_log_group_region
from lib.teams_notification import send_batch_failure_alert, send_teams_notification

logger = logging.getLogger(__name__)

# Row status accepted by report_template.html / styles.css.
_ROW_STATUS = {"Healthy": "ok", "Warning": "warning", "Failed": "error"}


def _get_logs_client(session, log_group: str, all_regions: list[str], region_cache: dict) -> object | None:
    """Return a logs client for this log group, discovering and caching its region."""
    if log_group not in region_cache:
        region_cache[log_group] = find_log_group_region(session, log_group, all_regions)

    region = region_cache[log_group]
    if region is None:
        return None
    return session.client("logs", region_name=region)


def run_checks(session, all_regions: list[str]) -> list[dict]:
    """Run every configured check and return results in their declared order."""
    region_cache: dict[str, str | None] = {}
    results = []
    for check in config.CHECKS:
        func = CHECK_FUNCTIONS[check["func"]]
        kind = check.get("kind", "logs")
        lookback_minutes = check.get("lookback_minutes", config.QUERY_LOOKBACK_MINUTES)

        try:
            if kind == "aws_session":
                outcome = func(session, all_regions, lookback_minutes)
            else:
                log_group = config.LOG_GROUPS[check.get("log_group", "application")]
                logs_client = _get_logs_client(session, log_group, all_regions, region_cache)
                if logs_client is None:
                    outcome = {"status": "Failed", "detail": f"Log group {log_group} not found in any region"}
                else:
                    outcome = func(logs_client, log_group, lookback_minutes)
            status, detail, evidence = outcome["status"], outcome["detail"], outcome.get("evidence")
        except Exception:
            logger.exception("Check %s raised an unexpected error", check["name"])
            status, detail, evidence = "Failed", "Unexpected error while running this check", None

        results.append({**check, "status": status, "detail": detail, "evidence": evidence})
    return results


def compute_overall_status(results: list[dict]) -> str:
    """Return 'UNHEALTHY' if any check failed, 'DEGRADED' if any warned, else 'HEALTHY'."""
    if any(result["status"] == "Failed" for result in results):
        return "UNHEALTHY"
    if any(result["status"] == "Warning" for result in results):
        return "DEGRADED"
    return "HEALTHY"


def print_report(results: list[dict]) -> None:
    """Print results grouped by category, matching the required report layout."""
    categories = list(dict.fromkeys(result["category"] for result in results))

    for category in categories:
        print(category)
        print("-" * len(category))

        for result in results:
            if result["category"] != category:
                continue
            print(f"{result['name']:<24}{result['status']:<10}{result['detail']}")

        print()

    print(f"Overall Status : {compute_overall_status(results)}")


def build_sections(results: list[dict]) -> list[dict]:
    """Convert check results into the {title, columns, rows} shape used by the HTML report.

    The status badge stays a plain status word; any supporting detail/raw log lines are
    attached as `evidence` for the report's expandable "View log evidence" panel.
    """
    sections = []
    for category in dict.fromkeys(result["category"] for result in results):
        rows = []
        for result in results:
            if result["category"] != category:
                continue
            evidence = result.get("evidence") or ([result["detail"]] if result.get("detail") else None)
            rows.append({
                "status": _ROW_STATUS[result["status"]],
                "cells": [result["name"], result["status"]],
                "evidence": evidence,
            })
        sections.append({"title": category, "columns": [category, "Status"], "rows": rows})
    return sections


def main() -> None:
    logging.basicConfig(level=logging.INFO)

    aws_ctx = bootstrap(account_id=config.AWS_ACCOUNT_ID, role_name=config.AWS_ROLE_NAME)
    all_regions = list_all_regions(aws_ctx.session)

    results = run_checks(aws_ctx.session, all_regions)
    print_report(results)

    sections = build_sections(results)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    output_path = Path(__file__).resolve().parent / config.OUTPUT_DIR / config.REPORT_FILENAME
    render_report(
        client_name=config.CLIENT_NAME,
        client_logo=config.CLIENT_LOGO,
        account_id=aws_ctx.account_id,
        sections=sections,
        output_path=output_path,
    )
    logger.info("Report written to %s", output_path)

    send_teams_notification(
        client_name=config.CLIENT_NAME,
        account_id=aws_ctx.account_id,
        generated_at=generated_at,
        overall_status=compute_overall_status(results),
        sections=sections,
    )

    send_batch_failure_alert(
        client_name=config.CLIENT_NAME,
        account_id=aws_ctx.account_id,
        generated_at=generated_at,
        sections=sections,
    )


if __name__ == "__main__":
    main()
