"""Build the golden reports: every case of tests/golden_cases.py over the frozen inputs.

    python dev/build_golden.py --live     # the prose case asks the real spark7; its replies are frozen
    python dev/build_golden.py            # rebuild from the frozen replies (nothing leaves the machine)

Writes ``golden/reports/<case>.json`` (the report, and for the prose case spark7's replies in order) and
``golden/reports/<case>.html`` (the page, to open in a browser). Check the diff before committing it: a
changed report is a behaviour change.
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from report.settings import load  # noqa: E402
from tests import golden_cases as gc  # noqa: E402
from tests.conftest import drop, settings_for  # noqa: E402
from tests.standin import Reply, StandIn  # noqa: E402


def transports() -> dict[str, httpx.BaseTransport]:
    files = gc.upstream_files()

    def make(engine: str) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            name = files[engine].get(request.url.path)
            return httpx.Response(200, content=(gc.INPUTS / name).read_bytes()) if name else httpx.Response(404)
        return httpx.MockTransport(handler)

    return {"pcp": make("pcp"), "lbs": make("lbs")}


def build(live: bool) -> None:
    from fastapi.testclient import TestClient

    from report.api import create_app

    gc.REPORTS.mkdir(parents=True, exist_ok=True)
    standin = StandIn().start()
    settings = settings_for(standin.url)
    model = load().model.model
    settings = replace(settings, model=replace(settings.model, model=model))
    live_settings = None
    if live:
        base = load(overrides={"model": {"warmup": {"enabled": False}}})
        live_settings = replace(base, database=settings.database)
    ids: dict[str, str] = {}
    try:
        with TestClient(create_app(settings, transports())) as client:
            live_client = None
            if live_settings is not None:
                live_client = TestClient(create_app(live_settings, transports()))
                live_client.__enter__()
            try:
                for case in gc.cases():
                    body = dict(case["request"])
                    if case.get("previous"):
                        body["previous_report_id"] = ids[case["previous"]]
                    if case.get("revision_of"):
                        body["revision_of"] = ids[case["revision_of"]]
                    replies: list[str] | None = None
                    if case.get("live"):
                        if live_client is not None:
                            service = live_client.app.state.service
                            recorded: list[str] = []
                            original = service.model.complete

                            def recording(*args, **kwargs):
                                done = original(*args, **kwargs)
                                recorded.append(done.text)
                                return done

                            service.model.complete = recording
                            r = live_client.post("/report", json=body)
                            service.model.complete = original
                            replies = recorded
                        else:
                            replies = gc.frozen(case["name"])["model_replies"]
                            standin.reset()
                            standin.queue(*(Reply(content=t, model=model) for t in replies))
                            r = client.post("/report", json=body)
                    else:
                        r = client.post("/report", json=body)
                    r.raise_for_status()
                    report = r.json()
                    ids[case["name"]] = report["artefact_id"]
                    if case.get("live") and live_client is None:
                        # An offline rebuild replays the frozen replies through the stand-in; it never rewrites
                        # the live-frozen report, whose provenance names the server that really wrote the prose.
                        print(f"{case['name']}: kept (live-frozen; rebuild it with --live)")
                        continue
                    out = {"_note": "Golden report (dev/build_golden.py).", "case": case["name"], "report": report}
                    if replies is not None:
                        out["model_replies"] = replies
                    (gc.REPORTS / f"{case['name']}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n",
                                                                     encoding="utf-8")
                    (gc.REPORTS / f"{case['name']}.html").write_text(report["html"], encoding="utf-8")
                    status = [f"{s['key']}={s['prose_status']}" for s in report["sections"]]
                    print(f"{case['name']}: {report['artefact_id']} complete={report['complete']} {' '.join(status)}")
            finally:
                if live_client is not None:
                    live_client.__exit__(None, None, None)
    finally:
        standin.stop()
        drop(settings)


if __name__ == "__main__":
    build("--live" in sys.argv[1:])
