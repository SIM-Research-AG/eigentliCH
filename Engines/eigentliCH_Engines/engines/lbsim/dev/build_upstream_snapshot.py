"""Freeze the upstream payloads the Monte Carlo tests read (``golden/upstream``), from the running engines, read only.

Run with the family interpreter while pcp 8007, aggregation 8004 and fmre 8006 answer::

    ..\\..\\.venv\\Scripts\\python -X utf8 dev/build_upstream_snapshot.py

GET requests only. What is written, exactly as served except for one reduction:

* ``allocation.json``: pcp's bench Allocation ``PCP-5304eca69cc0e867`` on the Default Regime (client ``bench``).
* ``regime_<key>.json``: aggregation's base Regime and its four scenario Regimes, reduced to what lbsim reads: the
  header, ``dates``, ``provenance`` and ``economies`` with ``code`` and ``distribution`` of the economies the
  Allocation weights (CH, EU, US). The blend reads only those, so every blended distribution is exactly what the
  full payload gives (the sha256 lbsim records is of course the reduced payload's).
* ``scenarios.json`` (the list, filtered to this base) and ``policies.json``.
* ``return_set_<key>.json`` (nominal, CHF, instruments, no blocks) and ``inflation_<key>.json`` per Regime.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parents[1]
OUT = HERE / "golden" / "upstream"
ALLOCATION = "PCP-5304eca69cc0e867"


def get(url: str, params: dict | None = None):
    r = httpx.get(url, params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def write(name: str, payload) -> None:
    (OUT / name).write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    alloc = get(f"http://127.0.0.1:8007/allocation/{ALLOCATION}")
    write("allocation.json", alloc)
    base_id = alloc["regime_id"]
    weights = alloc["provenance"]["regime_weights"]
    listing = [r for r in get("http://127.0.0.1:8004/scenarios") if r["base_regime_id"] == base_id]
    write("scenarios.json", listing)
    write("policies.json", get("http://127.0.0.1:8004/scenarios/policies"))
    regimes = {"base": base_id, **{r["policy"]: r["regime_id"] for r in listing}}
    for key, rid in regimes.items():
        reg = get(f"http://127.0.0.1:8004/regime/{rid}")
        reg["economies"] = [{"code": e["code"], "distribution": e["distribution"]} for e in reg["economies"]
                            if e["code"] in weights]
        reg = {k: reg[k] for k in ("contract_version", "artefact_id", "regime_id", "n_states", "dates",
                                   "economies", "provenance")}
        write(f"regime_{key}.json", reg)
        write(f"return_set_{key}.json", get("http://127.0.0.1:8006/v1/return-set", {
            "regime_id": rid, "currency": "CHF", "include_instruments": "true", "include_blocks": "false"}))
        write(f"inflation_{key}.json", get("http://127.0.0.1:8006/v1/inflation", {"currency": "CHF",
                                                                                   "regime_id": rid}))
        print(key, rid)
    write("manifest.json", {"built_by": "dev/build_upstream_snapshot.py", "allocation": ALLOCATION,
                            "regimes": regimes, "reduced": "regime economies to the Allocation's weights "
                            + ", ".join(sorted(weights))})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
