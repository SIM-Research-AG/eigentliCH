"""Freeze the Scenario_SAA.m reference values for the scenario Regimes (dev only; AGG-22).

    python golden/build_scenario_golden.py [--template PATH]

Reads ``Scenario_SAA.m`` (default: ``golden/scenario_saa/Scenario_SAA.m``, a verbatim copy of
``SIM_Tech/Master_Controller/Scenario_SAA.m`` v0.1), checks its sha256, parses the kernels and the
four target mixes out of the .m text (and copies macrofield's frozen ids, kernels
and mixes beside them, read only, for the TB-21 cross-check), and evaluates the target ``MRS(T,:)`` and the gradual
transformation by a literal transcription of the .m statements (MATLAB's 1-based indices kept as
written; there is no MATLAB on the build machine). It deliberately does not import
``aggregation.scenario``: the test compares that module against these frozen numbers.

Starts: ``uniform`` (every state 1/25), ``ramp`` (``1:25`` normalised) and ``rand`` (the .m file's
``MRS_start=rand(1,25); MRS_start=MRS_start/sum(MRS_start)``, drawn once here with numpy seed
20260929 and frozen with the result). Writes ``golden/scenario_saa/scenario_saa.json``.

Refreeze only with a reason, recorded in DECISIONS.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
OUT = HERE / "scenario_saa"
#: macrofield's freeze of the same template (TB-21), read only, for the cross-check of ids and values.
MACROFIELD = HERE.parents[1] / "macrofield" / "golden" / "scenario_saa" / "scenario_saa.json"
EXPECTED_SHA256 = "37071593f9958cc422e092a03ed0950fd13693af71e4a57f0e39f465d7c7f4de"
POLICY_BY_CASE = {1: "depression", 2: "hyperinflation", 3: "stagflation", 4: "deferral"}


def _vector(text: str, name: str) -> list[float]:
    m = re.search(rf"^{name}=\[([^\]]+)\]/100;", text, re.M)
    if not m:
        raise SystemExit(f"{name} not found in the template")
    return [float(v) for v in m.group(1).split()]


def _mixes(text: str) -> dict[int, list[float]]:
    out = {}
    for case, body in re.findall(r"case (\d)\s*\n(.*?)(?=\n\s*case \d|\nend\n)", text, re.S):
        m = re.search(r"M1\(:\)=\[([^\]]+)\];", body)
        out[int(case)] = [float(v) for v in m.group(1).split()]
    return out


def matlab_scenario(binom: list[float], binom_bust: list[float], m1: list[float], start: np.ndarray,
                    T: int) -> tuple[np.ndarray, np.ndarray]:
    """``Scenario_SAA.m`` lines "MRS = zeros(T, 25)" to the end of the transformation loop."""
    Binom = np.array(binom) / 100
    Binom_Bust = np.array(binom_bust) / 100
    Binom_Boom = np.flip(Binom_Bust)                                   # fliplr
    M1 = np.flip(np.array(m1))                                         # M1=fliplr(M1)
    MRS = np.zeros((T, 25))
    MRS[T - 1, :] = (np.concatenate([M1[0] * Binom_Bust, np.zeros(15)])
                     + np.concatenate([np.zeros(2), M1[1] * Binom, np.zeros(9)])
                     + np.concatenate([np.zeros(9), M1[2] * Binom, np.zeros(2)])
                     + np.concatenate([np.zeros(15), M1[3] * Binom_Boom]))
    target = MRS[T - 1, :].copy()
    MRS_start = start.copy()
    for i in range(1, T + 1):                                          # for i = 1:T
        difference = MRS[T - 1, :] - MRS_start
        step = difference / (T - i + 1)
        MRS_start = MRS_start + step
        MRS_start = MRS_start / np.sum(MRS_start)
        MRS[i - 1, :] = MRS_start
    return target, MRS


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", type=Path, default=OUT / "Scenario_SAA.m")
    args = ap.parse_args()
    raw = args.template.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != EXPECTED_SHA256:
        raise SystemExit(f"template sha256 {digest} is not v0.1 ({EXPECTED_SHA256})")
    text = raw.decode("utf-8", errors="replace").replace("\r\n", "\n")
    T = int(re.search(r"^T=(\d+);", text, re.M).group(1))
    binom, binom_bust = _vector(text, "Binom"), _vector(text, "Binom_Bust")
    mixes = _mixes(text)

    rng = np.random.default_rng(20260929)
    rand = rng.random(25)
    starts = {"uniform": np.full(25, 1 / 25), "ramp": np.arange(1, 26) / np.arange(1, 26).sum(),
              "rand": rand / rand.sum()}
    policies = {}
    for case, m1 in sorted(mixes.items()):
        paths = {}
        target = None
        for name, start in starts.items():
            target, mrs = matlab_scenario(binom, binom_bust, m1, start, T)
            paths[name] = mrs.tolist()
        policies[POLICY_BY_CASE[case]] = {"case": case, "target_mix": m1, "target": target.tolist(),
                                          "paths": paths}
    payload = {
        "source": "SIM_Tech/Master_Controller/Scenario_SAA.m (v0.1, Nicolas Buerkler)",
        "sha256": digest,
        "frozen_on": "2026-09-29",
        "note": ("kernels and target mixes parsed from the .m text; the target MRS(T,:) and the gradual "
                 "transformation evaluated by a literal numpy transcription of its statements (no MATLAB "
                 "on the build machine). target sums to 0.99 as in the .m file; every path row sums to 1"),
        "months": T,
        "mix_order": ["boom", "recovery", "contraction", "bust"],
        "kernels": {"binom": binom, "binom_bust": binom_bust},
        "starts": {k: v.tolist() for k, v in starts.items()},
        "policies": policies,
    }
    if MACROFIELD.is_file():
        mf = json.loads(MACROFIELD.read_text(encoding="utf-8"))
        payload["macrofield"] = {
            "file": "Macro/engines/macrofield/golden/scenario_saa/scenario_saa.json",
            "sha256_of_template": mf["sha256"],
            "kernels": mf["kernels"],
            "policies": {k: {"case": v["case"], "target_mix": v["target_mix"]} for k, v in mf["policies"].items()},
        }
    (OUT / "scenario_saa.json").write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(f"wrote {OUT / 'scenario_saa.json'}: {len(policies)} policies, {len(starts)} starts, T={T}")


if __name__ == "__main__":
    main()
