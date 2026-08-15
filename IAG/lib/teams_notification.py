"""Sends the executive health-check summary to a Microsoft Teams channel via webhook."""

import json
import logging
import os
import urllib.request

logger = logging.getLogger(__name__)

_STATUS_COLORS = {"HEALTHY": "1A9E6A", "DEGRADED": "E8A33D", "UNHEALTHY": "D13B3B"}


def _fact_value(row: dict) -> str:
    """Combine the status word with its check detail, so facts show the actual finding, not just Healthy/Warning/Failed."""
    status = row["cells"][1]
    detail = row.get("detail")
    if detail and detail != status:
        return f"{status} \u2014 {detail}"
    return status


def _section_facts(section: dict) -> list[dict]:
    """Application keeps full per-check detail; other sections (e.g. Infra Checks) collapse to one healthy/not-healthy line."""
    if section["title"] == "Application":
        return [{"name": row["cells"][0], "value": _fact_value(row)} for row in section["rows"]]
    unhealthy = [row["cells"][0] for row in section["rows"] if row.get("status") != "ok"]
    value = "Healthy" if not unhealthy else f"Not Healthy \u2014 {', '.join(unhealthy)}"
    return [{"name": section["title"], "value": value}]


def send_teams_notification(client_name: str, account_id: str, generated_at: str,
                             overall_status: str, sections: list[dict]) -> None:
    """Post an executive summary MessageCard to the Teams channel via the TEAMS_WEBHOOK env var."""
    webhook = os.getenv("TEAMS_WEBHOOK")
    if not webhook:
        logger.warning("TEAMS_WEBHOOK not set; skipping Teams notification")
        return

    message = {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "themeColor": _STATUS_COLORS.get(overall_status, "6B7280"),
        "summary": f"{client_name} AWS Daily Health Check",
        "title": f"{client_name} - AWS Daily Health Check",
        "text": f"Account {account_id} | Generated {generated_at}",
        "sections": [
            {
                "activityTitle": section["title"],
                "facts": _section_facts(section),
            }
            for section in sections
        ],
    }

    try:
        request = urllib.request.Request(
            webhook,
            data=json.dumps(message).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(request)
        logger.info("Teams notification sent successfully")
    except Exception:
        logger.exception("Failed to send Teams notification")


def send_batch_failure_alert(client_name: str, account_id: str, generated_at: str, sections: list[dict]) -> None:
    """Post a separate, clearly-flagged Teams alert only when the Application section has failures.

    Distinct from send_teams_notification()'s daily executive summary - this fires only when
    there's something actionable (a batch/application check in Warning or Failed state).
    """
    failing_rows = [
        row for section in sections if section["title"] == "Application"
        for row in section["rows"] if row.get("status") != "ok"
    ]
    if not failing_rows:
        return

    webhook = os.getenv("TEAMS_WEBHOOK")
    if not webhook:
        logger.warning("TEAMS_WEBHOOK not set; skipping batch failure alert")
        return

    message = {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "themeColor": "D13B3B",
        "summary": f"{client_name} Batch Failure Alert",
        "title": f"\U0001F6A8 {client_name} - Batch/Application Failure Alert",
        "sections": [
            {
                "activityTitle": f"{len(failing_rows)} Application check(s) need attention",
                "activitySubtitle": f"Account {account_id} | Generated {generated_at}",
                "facts": [{"name": row["cells"][0], "value": _fact_value(row)} for row in failing_rows],
            },
        ],
    }

    try:
        request = urllib.request.Request(
            webhook,
            data=json.dumps(message).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(request)
        logger.info("Batch failure alert sent successfully")
    except Exception:
        logger.exception("Failed to send batch failure alert")
