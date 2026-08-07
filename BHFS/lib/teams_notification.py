"""Sends the executive health-check summary to a Microsoft Teams channel via webhook."""

import json
import logging
import os
import urllib.request

logger = logging.getLogger(__name__)

_STATUS_COLORS = {"HEALTHY": "1A9E6A", "DEGRADED": "E8A33D", "UNHEALTHY": "D13B3B"}


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
        "sections": [
            {
                "activityTitle": f"Overall Status: {overall_status}",
                "activitySubtitle": f"Account {account_id} | Generated {generated_at}",
            },
            *(
                {
                    "activityTitle": section["title"],
                    "facts": [{"name": row["cells"][0], "value": row["cells"][1]} for row in section["rows"]],
                }
                for section in sections
            ),
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
