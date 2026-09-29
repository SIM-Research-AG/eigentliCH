"""Reporting: one write boundary, and the prose brief.

Every artefact this programme writes goes through `export`, so the regime vintage, the ReturnSet vintage,
the model-derived label and the disclaimer are attached where the file is written rather than depending on
each caller remembering them.
"""

from pcp.reporting.brief import render_brief
from pcp.reporting.export import export_result, result_payload, write_csv, write_json

__all__ = ["export_result", "render_brief", "result_payload", "write_csv", "write_json"]
