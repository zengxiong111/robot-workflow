"""Self-contained offline reports. No third-party assets or network requests."""

import json
from pathlib import Path


def render(report, output):
    template = Path(__file__).with_name("workflow.html").read_text(encoding="utf-8")
    # Escape all HTML delimiters inside application/json: repository data cannot close the script tag.
    payload = json.dumps(report, ensure_ascii=False).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(template.replace("__REPORT_DATA__", payload), encoding="utf-8")
