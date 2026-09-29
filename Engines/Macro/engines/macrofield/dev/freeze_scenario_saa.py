"""Freeze ``Scenario_SAA.m`` (the R-005 template) into ``golden/scenario_saa/scenario_saa.json``. Dev only.

    python dev/freeze_scenario_saa.py [path/to/Scenario_SAA.m]

Default source: ``SIM_Tech/Master_Controller/Scenario_SAA.m`` under the SIM_NAS root (read only).
The script

1. copies the file verbatim to ``golden/scenario_saa/Scenario_SAA.m`` and records its SHA-256,
2. **parses** every parameter out of the .m text (per ``case``: the target mix ``M1``, the
   scalar assignments before ``inflation``, ``defaults`` and ``valuations``, the ``linspace`` /
   ``ones`` of the valuations, the kernels ``Binom`` and ``Binom_Bust``), so no value is typed
   by hand,
3. evaluates the paths with a **literal transcription** of the .m statements (loops and all,
   written independently of ``src/macrofield/resolution.py``), and writes both.

No MATLAB or Octave is installed on the build machine, so the paths are the transcription's
evaluation in numpy (``linspace`` as numpy computes it); the test compares the engine with them
to 1e-15. The parameters are the .m file's own literals, compared exactly. Engine 09
(``scenario``) is to read the same file.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "golden" / "scenario_saa"
DEFAULT = ROOT.parents[4] / "SIM_Tech" / "Master_Controller" / "Scenario_SAA.m"
IDS = {1: "depression", 2: "hyperinflation", 3: "stagflation", 4: "deferral"}
NUMBER = r"-?\d+(?:\.\d+)?"


def _vector(text: str) -> list[float]:
    return [float(v) for v in re.findall(NUMBER, text)]


def parse(source: str) -> dict:
    src = source.replace("\r\n", "\n")
    months = int(re.search(r"^T\s*=\s*(\d+)", src, re.M).group(1))
    binom = _vector(re.search(r"^Binom\s*=\s*\[([^\]]*)\]", src, re.M).group(1))
    bust = _vector(re.search(r"^Binom_Bust\s*=\s*\[([^\]]*)\]", src, re.M).group(1))
    comment = re.search(r"s\s*=\s*(\d+);\s*%\s*(.*)", src)
    blocks = re.split(r"^\s*case\s+(\d+)\s*$", src.split("switch s", 1)[1].split("\nend\nM1", 1)[0], flags=re.M)
    cases = {}
    for number, body in zip(blocks[1::2], blocks[2::2]):
        n = int(number)
        mix = _vector(re.search(r"M1\(:\)\s*=\s*\[([^\]]*)\]", body).group(1))
        scope: dict[str, float] = {}
        captured: dict[str, dict[str, float]] = {}
        for statement in re.split(r"[;\n]", body):
            statement = statement.split("%", 1)[0].strip()
            m = re.fullmatch(rf"(\w+)\s*=\s*({NUMBER})", statement)
            if m:
                scope[m.group(1)] = float(m.group(2))
                continue
            m = re.fullmatch(r"(\w+)\s*=\s*(.+)", statement)
            if m and m.group(1) in ("inflation", "defaults", "valuations") and m.group(1) not in captured:
                captured[m.group(1)] = dict(scope)
                if m.group(1) == "valuations":
                    captured["valuations_expr"] = {"expr": m.group(2)}
        form = ("sigmoid_reversed" if "fliplr(endVal + range" in body else
                "sigmoid" if "startVal + range ./ (1 + exp" in body else
                "exponential" if "exp(log(endVal / startVal)" in body else
                "hump" if "peakPosition" in body else None)
        expr = captured["valuations_expr"]["expr"]
        ramp = re.search(rf"linspace\(({NUMBER}),({NUMBER}),(\d+)\)", expr.replace(" ", ""))
        if ramp:
            valuations = {"start": float(ramp.group(1)), "end": float(ramp.group(2)),
                          "ramp_months": int(ramp.group(3))}
        else:  # ones(1,T): flat at one
            valuations = {"start": 1.0, "end": 1.0, "ramp_months": months}
        constant_defaults = re.search(r"defaults\s*=\s*ones\(size\(times\)\)", body) is not None
        cases[n] = {"mix": mix, "inflation_form": form, "inflation": captured["inflation"],
                    "defaults": None if constant_defaults else captured["defaults"],
                    "valuations": valuations}
    return {"months": months, "binom": binom, "binom_bust": bust,
            "selected_case": int(comment.group(1)), "case_comment": comment.group(2).strip(),
            "cases": cases}


def transcribe(months: int, case: dict) -> dict[str, list[float]]:
    """The .m statements, literally."""
    times = np.linspace(0, 1, months)
    p, form = case["inflation"], case["inflation_form"]
    if form == "sigmoid_reversed":
        startVal, endVal, midpoint, steepness = p["startVal"], p["endVal"], p["midpoint"], p["steepness"]
        range_ = startVal - endVal
        inflation = np.fliplr([endVal + range_ / (1 + np.exp(-steepness * (times - midpoint)))])[0]
    elif form == "sigmoid":
        startVal, endVal, midpoint, steepness = p["startVal"], p["endVal"], p["midpoint"], p["steepness"]
        range_ = endVal - startVal
        inflation = startVal + range_ / (1 + np.exp(-steepness * (times - midpoint)))
    elif form == "exponential":
        startVal, endVal, power = p["startVal"], p["endVal"], p["power"]
        inflation = startVal * np.exp(np.log(endVal / startVal) * times ** power)
    else:
        startVal, peakVal, peakPosition = p["startVal"], p["peakVal"], p["peakPosition"]
        range_ = peakVal - startVal
        sigma1 = peakPosition / 2.5
        sigma2 = (1 - peakPosition) / 2.5
        inflation = np.zeros(times.shape)
        for i in range(len(times)):
            t = times[i]
            if t <= peakPosition:
                inflation[i] = startVal + range_ * np.exp(-0.5 * ((t - peakPosition) / sigma1) ** 2)
            else:
                inflation[i] = startVal + range_ * np.exp(-0.5 * ((t - peakPosition) / sigma2) ** 2)
    if case["defaults"] is None:
        defaults = np.ones(times.shape)
    else:
        d = case["defaults"]
        startVal, endVal, inflectionPoint, steepness = d["startVal"], d["endVal"], d["inflectionPoint"], d["steepness"]
        totalChange = startVal - endVal
        defaults = np.zeros(times.shape)
        for i in range(len(times)):
            t = times[i]
            if t <= inflectionPoint:
                defaults[i] = startVal - totalChange * (t / inflectionPoint) ** (1 / steepness) * 0.3
            else:
                t_norm = (t - inflectionPoint) / (1 - inflectionPoint)
                valueAtInflection = startVal - totalChange * 0.3
                remainingChange = valueAtInflection - endVal
                defaults[i] = valueAtInflection - remainingChange * t_norm ** steepness
    v = case["valuations"]
    if v["start"] == v["end"] == 1.0 and v["ramp_months"] == months:
        valuations = np.ones(months)
    else:
        valuations = np.concatenate([np.linspace(v["start"], v["end"], v["ramp_months"]),
                                     v["end"] * np.ones(months - v["ramp_months"])])
    return {"inflation": [float(x) for x in inflation], "defaults": [float(x) for x in defaults],
            "valuations": [float(x) for x in valuations]}


def main() -> None:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    raw = source.read_bytes()
    GOLDEN.mkdir(exist_ok=True)
    shutil.copyfile(source, GOLDEN / "Scenario_SAA.m")
    parsed = parse(raw.decode("utf-8"))
    out = {
        "source": "SIM_Tech/Master_Controller/Scenario_SAA.m (v0.1, Nicolas Buerkler)",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "frozen_on": "2026-09-28",
        "note": ("parameters parsed from the .m text; paths evaluated by a literal numpy "
                 "transcription of its statements (no MATLAB on the build machine)"),
        "months": parsed["months"],
        "selected_case": parsed["selected_case"], "case_comment": parsed["case_comment"],
        "kernels": {"binom": parsed["binom"], "binom_bust": parsed["binom_bust"]},
        "policies": {},
    }
    for n, case in sorted(parsed["cases"].items()):
        out["policies"][IDS[n]] = {"case": n, "target_mix": case["mix"],
                                   "inflation_form": case["inflation_form"],
                                   "inflation_parameters": case["inflation"],
                                   "defaults_parameters": case["defaults"],
                                   "valuations_parameters": case["valuations"],
                                   **transcribe(parsed["months"], case)}
    (GOLDEN / "scenario_saa.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {GOLDEN / 'scenario_saa.json'} from {source} ({out['sha256'][:12]})")


if __name__ == "__main__":
    main()
