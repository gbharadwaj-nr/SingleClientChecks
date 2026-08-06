"""Renders the shared HTML report template using Jinja2."""

import logging
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger(__name__)

ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "assets"


def render_report(client_name: str, client_logo: str, account_id: str,
                   sections: list[dict], output_path: Path) -> None:
    """Render report_template.html with the given data and write it to output_path."""
    env = Environment(
        loader=FileSystemLoader(str(ASSETS_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("report_template.html")

    html = template.render(
        client_name=client_name,
        client_logo=client_logo,
        account_id=account_id,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        sections=sections,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    logger.info("Rendered report to %s", output_path)
