"""Run all six real submissions through the running application and record exactly what it answers.

Nothing here interprets. It signs in as each member the way a member signs in, calls the member-facing
routes the product actually serves, puts the member's OWN question to the Know, and writes the raw
payloads to disk. The reading of those payloads is a separate act and happens somewhere else.

`must_change` refuses every member route with a 403 (A43), so the first-login password change is part of
the run rather than a workaround for it — that is what a member's first session does.
"""
import io
import json
import os
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8896"
OUT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/reports"
# Same walk as OUT above, for the same reason: an absolute path here named the estate and the build
# folder, and both were renamed on 21 September 2026 while this line went on pointing at neither.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/"

#: NOT an identifier, and not to be renamed with the rest of them. This exact string is the password
#: five member accounts have carried since the 4 September run set it, and what the database holds is
#: its hash. The rename pass of 21 September rewrote it to `eigentlich ...`, which would have made
#: every one of those sign-ins fail — silently, because the script falls through to the first-login
#: password and reports a 401 as a finding about the member rather than about itself.
NEW_PASSWORD = "andersch vergleichslauf vom vierten september"

MEMBERS = [
    ("MarvinMüller", "marvinm", "ein hinreichend langes passwort"),
    ("NinoTommasini", "ninot", NEW_PASSWORD),
    ("EliaTommasini", "eliat", NEW_PASSWORD),
    ("LevinSprenger", "levins", NEW_PASSWORD),
    ("ElioTommasini", "eliot", NEW_PASSWORD),
    ("YasminTommasini", "yasmint", NEW_PASSWORD),
    # Loaded 4 September under invented names (A140, A141). First-login passwords still stand.
    ("2026-08-05", "ueliw", None),
    ("2026-08-06 (1)", "sandrai", None),
    ("2026-08-06 (2)", "nadinec", None),
    ("2026-08-18", "retok", None),
]

#: Every member-facing GET this report reads. Ordered as a reader would want them.
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


def call(path, *, token=None, body=None, method=None):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        url, data=data, method=method or ("POST" if data else "GET")
    )
    if data:
        request.add_header("content-type", "application/json")
    if token:
        request.add_header("authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", "replace")
        try:
            return error.code, json.loads(raw)
        except ValueError:
            return error.code, {"_raw": raw}


def submission(person):
    # Also not an identifier: it is the name sixty files on disk actually carry, recorded in
    # `_MANIFEST.csv` and matched by `bookindex.py` and `test_gameplan.py`. Renaming the data is a
    # separate act from renaming the package, and it has not been done.
    path = ROOT + f"client/submissions/andersch-onboarding-{person}.json"
    return json.load(io.open(path, encoding="utf-8"))


def sign_in(local, known):
    """Returns (token, note). The note records whether a password change was part of this run."""
    first_login = f"erstanmeldung-{local}-bitte-aendern"
    for password, label in ((known, "already changed"), (first_login, "first login"),
                            (NEW_PASSWORD, "changed by this run")):
        if password is None:
            continue
        status, body = call("/api/session", body={"email": f"{local}@eigentli.local",
                                                 "password": password})
        if status in (200, 201) and body.get("token"):
            return body["token"], label
    return None, "SIGN-IN FAILED"


def main():
    os.makedirs(OUT, exist_ok=True)
    index = {}

    for person, local, known in MEMBERS:
        print(f"\n===== {person}")
        record = {"person": person, "email": f"{local}@eigentli.local"}

        token, note = sign_in(local, known)
        record["sign_in"] = note
        if token is None:
            print("  SIGN-IN FAILED")
            index[person] = record
            continue
        print(f"  signed in ({note})")

        status, who = call("/api/session", token=token)
        record["session"] = who
        if who.get("must_change"):
            code, changed = call(
                "/api/password", token=token,
                body={"current": known or f"erstanmeldung-{local}-bitte-aendern", "new": NEW_PASSWORD},
            )
            print(f"  must_change -> password changed: {code}")
            record["password_changed_by_this_run"] = code in (200, 201)
            token, _ = sign_in(local, NEW_PASSWORD)

        for name, path in READS:
            code, body = call(path, token=token)
            record[name] = {"status": code, "body": body}
            mark = "ok " if code == 200 else f"{code}"
            print(f"  {mark:4} {name}")

        # The member's own words, put to the product. `main_question` is the field
        # `tools/load_submission.py` calls "the single most useful sentence in the submission" and
        # records as having nowhere to go.
        raw = submission(person).get("raw") or {}
        question = raw.get("main_question")
        record["main_question"] = question
        if question:
            code, answer = call("/api/know/ask", token=token,
                                body={"question": question, "language": "de"})
            record["know_ask"] = {"status": code, "body": answer}
            print(f"  {code}  know/ask <- member's own question")

        index[person] = record

    with io.open(f"{OUT}/cases.json", "w", encoding="utf-8", newline="\n") as handle:
        json.dump(index, handle, ensure_ascii=False, indent=2)
    print(f"\nwrote {OUT}/cases.json")


if __name__ == "__main__":
    main()
