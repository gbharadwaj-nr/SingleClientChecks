"""
FleetCor AWS Daily Health Check.

Runs a set of CloudWatch Logs Insights queries (RDS, EC2, UI, DXV, AML Batch,
Batch Files, Bad Records, ACQ Flags), prints a console health report, and renders
the same standard client HTML report used by the other client folders.

Add new checks by appending an entry to config.CHECKS - no other code changes
are required as long as the check follows the same {log_group, query, labels} shape.
"""

import logging
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

import config
from bootstrap import bootstrap
from lib.html_report import render_report
from lib.logs_insights import extract_messages, extract_stats, run_query

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


def evaluate_check(check: dict, logs_client) -> tuple[str, bool | None]:
    """Run one check's Logs Insights query and return (status_label, passed).

    `passed` is None for checks that have no query configured yet.
    """
    if not check["query"] or not check["log_group"]:
        return "Not Configured", None

    lookback_minutes = check.get("lookback_minutes", config.QUERY_LOOKBACK_MINUTES)
    results = run_query(logs_client, check["log_group"], check["query"], lookback_minutes)

    if check.get("result_type") == "stats":
        return _evaluate_stats_check(check, results)

    messages = extract_messages(results)

    if not messages:
        return check["failure_label"], False

    has_failure = any(keyword in message.lower() for message in messages for keyword in _FAILURE_KEYWORDS)
    if has_failure:
        return check["failure_label"], False

    return check["success_label"], True


def run_checks(logs_client) -> list[dict]:
    """Run every configured check and return results in their declared order."""
    results = []
    for check in config.CHECKS:
        try:
            status_label, passed = evaluate_check(check, logs_client)
        except Exception:
            logger.exception("Check %s raised an unexpected error", check["name"])
            status_label, passed = check["failure_label"], False
        results.append({**check, "status_label": status_label, "passed": passed})
    return results


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
            print(f"{result['name']:<20}{result['status_label']}")
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
        rows = [
            {"status": _ROW_STATUS[result["passed"]], "cells": [result["name"], result["status_label"]]}
            for result in results
            if result["category"] == category
        ]
        sections.append({"title": category, "columns": ["Check", "Result"], "rows": rows})
    return sections


def main() -> None:
    logging.basicConfig(level=logging.WARNING)

    aws_ctx = bootstrap(account_id=config.AWS_ACCOUNT_ID, role_name=config.AWS_ROLE_NAME)
    logs_client = aws_ctx.session.client("logs", region_name=config.AWS_REGION)

    results = run_checks(logs_client)
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
