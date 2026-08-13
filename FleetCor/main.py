"""
FleetCor AWS Daily Health Check.

Runs a set of CloudWatch Logs Insights queries (RDS, EC2, UI, DXV, AML Batch,
Batch Files, Bad Records, ACQ Flags), prints a console health report, and renders
the same standard client HTML report used by the other client folders.

Add new checks by appending an entry to config.CHECKS - no other code changes
are required as long as the check follows the same {log_group, query, labels} shape.
"""

import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

import config
from bootstrap import bootstrap, list_all_regions
from lib.checks import CHECK_FUNCTIONS
from lib.html_report import render_report
from lib.logs_insights import extract_messages, extract_stats, find_log_group_region, run_query
from lib.teams_notification import send_batch_failure_alert, send_teams_notification

logger = logging.getLogger(__name__)

# Keywords in a log message that indicate a check should be treated as failed.
_FAILURE_KEYWORDS = ("fail", "error", "exception", "unavailable", "timeout")


def _evaluate_stats_check(check: dict, results: list[list[dict]]) -> tuple[str, bool, list[str]]:
    """Evaluate a `stats`-style query (e.g. UI availability percentage) against a threshold."""
    stats = extract_stats(results)
    raw_value = stats.get(check["stats_field"])
    evidence = [f"{key}={value}" for key, value in stats.items()]
    if raw_value is None:
        return check["failure_label"], False, evidence

    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return check["failure_label"], False, evidence

    passed = value >= check["stats_threshold"]
    return (check["success_label"], True, evidence) if passed else (check["failure_label"], False, evidence)


def _extract_detail(check: dict, messages: list[str]) -> str | None:
    """Pull an inline detail (e.g. a batch date or filename) out of the messages.

    Messages are already sorted most-recent-first, so this returns the detail from the
    first (i.e. latest) message that actually matches - not just the very first message,
    since a shared log stream can interleave unrelated lines.
    """
    pattern = check.get("detail_regex")
    if not pattern:
        return None

    for message in messages:
        match = re.search(pattern, message)
        if match:
            return match.group(1)
    return None


def _get_logs_client(session, log_group: str, all_regions: list[str], region_cache: dict) -> tuple[object | None, str | None]:
    """Return a (logs_client, region) for this log group, discovering and caching its region."""
    if log_group not in region_cache:
        region_cache[log_group] = find_log_group_region(session, log_group, all_regions)

    region = region_cache[log_group]
    if region is None:
        return None, None
    return session.client("logs", region_name=region), region


def evaluate_check(check: dict, session, all_regions: list[str], region_cache: dict) -> tuple[str, bool | None, str | None, list[str] | None]:
    """Run one check's Logs Insights query and return (status_label, passed, detail, evidence).

    `passed` is None for checks that have no query configured yet. `detail` is an optional
    extra bit of context (e.g. a batch date or filename) pulled from the latest message.
    `evidence` is the raw log line(s) (or resource summary, for AWS-API checks) backing the
    result, shown in the HTML report's expandable "View log evidence" panel.
    """
    if check.get("check_type") == "aws_api":
        func = CHECK_FUNCTIONS[check["func"]]
        status_label, passed, detail = func(session, all_regions, check.get("name_filter", ""))
        evidence = detail.split("; ") if detail else None
        return status_label, passed, detail, evidence

    if not check["query"] or not check["log_group"]:
        return "Not Configured", None, None, None

    logs_client, _region = _get_logs_client(session, check["log_group"], all_regions, region_cache)
    if logs_client is None:
        return check["failure_label"], False, None, None

    lookback_minutes = check.get("lookback_minutes", config.QUERY_LOOKBACK_MINUTES)
    results = run_query(logs_client, check["log_group"], check["query"], lookback_minutes)

    if check.get("result_type") == "stats":
        status_label, passed, evidence = _evaluate_stats_check(check, results)
        return status_label, passed, None, evidence

    messages = extract_messages(results)

    if not messages:
        return check["failure_label"], False, None, None

    evidence = messages[:5]
    has_failure = any(keyword in message.lower() for message in messages for keyword in _FAILURE_KEYWORDS)
    if has_failure:
        return check["failure_label"], False, None, evidence

    return check["success_label"], True, _extract_detail(check, messages), evidence


def run_checks(session, all_regions: list[str]) -> list[dict]:
    """Run every configured check and return results in their declared order."""
    results = []
    region_cache: dict[str, str | None] = {}
    for check in config.CHECKS:
        try:
            status_label, passed, detail, evidence = evaluate_check(check, session, all_regions, region_cache)
        except Exception:
            logger.exception("Check %s raised an unexpected error", check["name"])
            status_label, passed, detail, evidence = check["failure_label"], False, None, None
        results.append({**check, "status_label": status_label, "passed": passed, "detail": detail, "evidence": evidence})
    return results


def format_row(result: dict) -> tuple[str, str]:
    """Apply a check's optional inline detail to its name or status, per detail_target."""
    name = result["name"]
    status = result["status_label"]
    detail = result.get("detail")
    if detail:
        if result.get("detail_target") == "name":
            name = f"{name} ({detail})"
        else:
            status = f"{status} ({detail})"
    return name, status


def compute_overall_status(results: list[dict]) -> str:
    """Return 'UNHEALTHY' if any check explicitly failed, else 'HEALTHY'."""
    return "UNHEALTHY" if any(result["passed"] is False for result in results) else "HEALTHY"


def print_report(results: list[dict]) -> None:
    """Print results grouped by category, matching the required report layout."""
    categories = list(dict.fromkeys(result["category"] for result in results))

    for category in categories:
        print(category)
        print("-" * len(category))

        for result in results:
            if result["category"] != category:
                continue
            name, status = format_row(result)
            print(f"{name:<28}{status}")

        print()

    print(f"Overall Status : {compute_overall_status(results)}")


# Row status accepted by report_template.html / styles.css.
_ROW_STATUS = {True: "ok", False: "error", None: "warning"}


def build_sections(results: list[dict]) -> list[dict]:
    """Convert check results into the {title, columns, rows} shape used by the HTML report."""
    sections = []
    for category in dict.fromkeys(result["category"] for result in results):
        rows = []
        for result in results:
            if result["category"] != category:
                continue
            name, status = format_row(result)
            rows.append({"status": _ROW_STATUS[result["passed"]], "cells": [name, status], "evidence": result.get("evidence")})
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
