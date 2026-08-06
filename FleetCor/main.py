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
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

import config
from bootstrap import bootstrap, list_all_regions
from lib.html_report import render_report
from lib.logs_insights import extract_messages, extract_stats, find_log_group_region, run_query

logger = logging.getLogger(__name__)

# Keywords in a log message that indicate a check should be treated as failed.
_FAILURE_KEYWORDS = ("fail", "error", "exception", "unavailable", "timeout")


def _evaluate_stats_check(check: dict, results: list[list[dict]]) -> tuple[str, bool]:
    """Evaluate a `stats`-style query (e.g. UI availability percentage) against a threshold."""
    stats = extract_stats(results)
    raw_value = stats.get(check["stats_field"])
    if raw_value is None:
        return check["failure_label"], False

    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return check["failure_label"], False

    passed = value >= check["stats_threshold"]
    return (check["success_label"], True) if passed else (check["failure_label"], False)


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


def evaluate_check(check: dict, session, all_regions: list[str], region_cache: dict) -> tuple[str, bool | None, str | None]:
    """Run one check's Logs Insights query and return (status_label, passed, detail).

    `passed` is None for checks that have no query configured yet. `detail` is an optional
    extra bit of context (e.g. a batch date or filename) pulled from the latest message.
    """
    if not check["query"] or not check["log_group"]:
        return "Not Configured", None, None

    logs_client, _region = _get_logs_client(session, check["log_group"], all_regions, region_cache)
    if logs_client is None:
        return check["failure_label"], False, None

    lookback_minutes = check.get("lookback_minutes", config.QUERY_LOOKBACK_MINUTES)
    results = run_query(logs_client, check["log_group"], check["query"], lookback_minutes)

    if check.get("result_type") == "stats":
        status_label, passed = _evaluate_stats_check(check, results)
        return status_label, passed, None

    messages = extract_messages(results)

    if not messages:
        return check["failure_label"], False, None

    has_failure = any(keyword in message.lower() for message in messages for keyword in _FAILURE_KEYWORDS)
    if has_failure:
        return check["failure_label"], False, None

    return check["success_label"], True, _extract_detail(check, messages)


def run_checks(session, all_regions: list[str]) -> list[dict]:
    """Run every configured check and return results in their declared order."""
    results = []
    region_cache: dict[str, str | None] = {}
    for check in config.CHECKS:
        try:
            status_label, passed, detail = evaluate_check(check, session, all_regions, region_cache)
        except Exception:
            logger.exception("Check %s raised an unexpected error", check["name"])
            status_label, passed, detail = check["failure_label"], False, None
        results.append({**check, "status_label": status_label, "passed": passed, "detail": detail})
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


def print_report(results: list[dict]) -> None:
    """Print results grouped by category, matching the required report layout."""
    categories = list(dict.fromkeys(result["category"] for result in results))
    overall_healthy = True

    for category in categories:
        print(category)
        print("-" * len(category))

        for result in results:
            if result["category"] != category:
                continue
            name, status = format_row(result)
            print(f"{name:<28}{status}")
            if result["passed"] is False:
                overall_healthy = False

        print()

    print(f"Overall Status : {'HEALTHY' if overall_healthy else 'UNHEALTHY'}")


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
            rows.append({"status": _ROW_STATUS[result["passed"]], "cells": [name, status]})
        sections.append({"title": category, "columns": [category, "Status"], "rows": rows})
    return sections


def main() -> None:
    logging.basicConfig(level=logging.INFO)

    aws_ctx = bootstrap(account_id=config.AWS_ACCOUNT_ID, role_name=config.AWS_ROLE_NAME)
    all_regions = list_all_regions(aws_ctx.session)

    results = run_checks(aws_ctx.session, all_regions)
    print_report(results)

    output_path = Path(__file__).resolve().parent / config.OUTPUT_DIR / config.REPORT_FILENAME
    render_report(
        client_name=config.CLIENT_NAME,
        client_logo=config.CLIENT_LOGO,
        account_id=aws_ctx.account_id,
        sections=build_sections(results),
        output_path=output_path,
    )
    logger.info("Report written to %s", output_path)


if __name__ == "__main__":
    main()
