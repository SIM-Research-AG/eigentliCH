"""Run every submission-loaded member through the running application and record what it answers.

The same act as `tools/run_cases.py` and deliberately a separate file. That one names its ten members in
a list, with the passwords they were given on 4 September; this one discovers whoever
`tools/load_submission.py` has loaded, so a run after loading fifty more does not mean editing a literal.

**Nothing here interprets.** It signs in the way a member signs in, performs the first-login password
change the way a member performs it (A43 refuses every member route with a 403 until it happens), calls
the member-facing routes the product actually serves, puts the member's OWN question to the Know, and
writes the raw payloads. Reading them is a separate act — `tools/render_client_reports.py`.

Usage, with the server already running:

    python -m uvicorn eigentlich.api.main:app --port 8896      # from backend/
    python tools/run_new_clients.py --since 2026-09-20 > reports/new-clients-run.txt

`--since` selects by the submission file's date, which is how the fifty of 20 September 2026 are
distinguished from the ten that came before them.
"""

from __future__ import annotations

import argparse
import datetime
import io
import json
import pathlib
import sys
import urllib.error
import urllib.request

REPO = pathlib.Path(__file__).resolve().parent.parent
OUT = REPO / "reports"
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "tools"))

BASE = "http://127.0.0.1:8896"

#: One password for the whole run, set on first login. Documented here rather than derived, because a
#: report that cannot be reproduced is not evidence — and these are local demonstration accounts whose
#: passwords A53 says may be written down.
NEW_PASSWORD = "eigentlich erstlauf vom zwanzigsten september"

#: Every member-facing GET a report reads, ordered as a reader would want them.
READS = [
    ("befund", "/api/befund?language=de"),
    ("goals", "/api/goals?language=de"),
    ("positions", "/api/positions"),
    ("actions", "/api/actions"),
    ("decisions", "/api/decisions"),
    ("onboarding", "/api/onboarding?language=de"),
    ("feed", "/api/feed"),
    ("learning", "/api/learning?language=de"),
    ("vault", "/api/vault"),
    ("data_classes", "/api/settings/data-classes"),
    ("consents", "/api/settings/consents"),
    ("regime", "/api/regime"),
]


def call(path: str, *, token: str | None = None, body: dict | None = None, method: str | None = None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, method=method or ("POST" if data else "GET"))
    if data:
        request.add_header("content-type", "application/json")
    if token:
        request.add_header("authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as refused:
        raw = refused.read().decode("utf-8", "replace")
        try:
            return refused.code, json.loads(raw)
        except json.JSONDecodeError:
            return refused.code, {"raw": raw[:400]}
    except Exception as broke:  # noqa: BLE001 - the report records whatever went wrong, verbatim
        return 0, {"error": f"{type(broke).__name__}: {broke}"}


def sign_in(email: str, password: str):
    status, body = call("/api/session", body={"email": email, "password": password})
    if status in (200, 201) and body.get("token"):
        return body["token"], f"{status}"
    return None, f"{status} {json.dumps(body, ensure_ascii=False)[:160]}"


def loaded_members(since: datetime.date | None) -> list[dict]:
    """Members this build created from a submission, newest submission first.

    Read from the database rather than from the directory, because the question is "who is in the
    system", and four of the fifty are in the directory and not in the system.
    """
    from eigentlich.db import make_engine, make_session_factory
    from eigentlich.models import Credential, Member
    from sqlalchemy import select

    from load_submission import _names, _person

    wanted = None
    if since is not None:
        wanted = {
            _names(_person(path))[0]
            for path in (REPO / "client" / "submissions").glob("eigentlich-onboarding-*.json")
            if datetime.date.fromtimestamp(path.stat().st_mtime) >= since
        }

    out = []
    with make_session_factory(make_engine())() as db:
        rows = db.execute(
            select(Member, Credential).join(Credential, Credential.member_id == Member.id)
        ).all()
        for member, credential in rows:
            local = credential.email.split("@", 1)[0]
            if wanted is not None and local not in wanted:
                continue
            out.append({
                "member_id": member.id,
                "display_name": member.display_name,
                "email": credential.email,
                "local": local,
                "must_change": credential.must_change,
                "onboarding_completed": member.onboarding_completed_at is not None,
            })
    return sorted(out, key=lambda r: r["display_name"])


def submission_for(local: str) -> dict:
    """The member's own submission, matched by the slug their address was derived from."""
    from load_submission import _names, _person

    for path in sorted((REPO / "client" / "submissions").glob("eigentlich-onboarding-*.json")):
        if _names(_person(path))[0] == local:
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {}
    return {}


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):  # pragma: no cover
            pass

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--since", help="only members whose submission file is dated on or after this")
    parser.add_argument("--out", default=str(OUT / "new-clients.json"))
    args = parser.parse_args(argv)

    since = datetime.date.fromisoformat(args.since) if args.since else None
    people = loaded_members(since)
    print(f"{len(people)} member(s) to run\n")

    index: dict[str, dict] = {}
    for number, person in enumerate(people, 1):
        local = person["local"]
        print(f"===== [{number}/{len(people)}] {person['display_name']}  <{person['email']}>")
        record = dict(person)

        first_login = f"erstanmeldung-{local}-bitte-aendern"
        token, note = sign_in(person["email"], first_login)
        if token is None:
            token, note = sign_in(person["email"], NEW_PASSWORD)
        record["sign_in"] = note
        if token is None:
            print(f"  SIGN-IN FAILED: {note}")
            index[local] = record
            continue

        status, who = call("/api/session", token=token)
        record["session"] = {"status": status, "body": who}
        if isinstance(who, dict) and who.get("must_change"):
            code, _ = call("/api/password", token=token,
                           body={"current": first_login, "new": NEW_PASSWORD})
            record["password_changed_by_this_run"] = code in (200, 201)
            token, _ = sign_in(person["email"], NEW_PASSWORD)
            print(f"  must_change -> password changed ({code})")

        for name, path in READS:
            code, body = call(path, token=token)
            record[name] = {"status": code, "body": body}
            print(f"  {'ok ' if code == 200 else str(code):4} {name}")

        raw = (submission_for(local).get("raw") or {})
        question = raw.get("main_question")
        record["main_question"] = question
        if question:
            code, answer = call("/api/know/ask", token=token,
                                body={"question": question, "language": "de"})
            record["know_ask"] = {"status": code, "body": answer}
            print(f"  {code}  know/ask <- the member's own question")

        index[local] = record

    target = pathlib.Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    with io.open(target, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(index, handle, ensure_ascii=False, indent=1)
    print(f"\nwrote {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
