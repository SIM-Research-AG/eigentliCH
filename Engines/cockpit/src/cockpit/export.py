"""Excel exports for the CIO, written with the standard library.

openpyxl is outside the allowlist and would be the only reason to add a dependency, so the
workbook is written directly: an .xlsx is a zip of a handful of XML parts (DECISIONS.md C-04).
The exports lay out what the engines published and compute nothing: every number in a sheet
is a number an engine endpoint returned.

The HoNI workbook covers what the old ``HoNI_Export.xlsx`` offered (national score by year and
country, one sheet per country with its indices) and adds the sectors, capital saturation,
the latest-year overview, peer statistics, coverage, calibration and provenance.
"""

from __future__ import annotations

import io
import math
import re
import zipfile
from datetime import datetime, timezone
from typing import Any, Iterable, Optional, Sequence
from xml.sax.saxutils import escape

NOTICE = "Model-derived research output. Not investment advice."

# Style ids in styles.xml below.
PLAIN, HEADER, NUM2, NUM4, WRAP, TITLE, PCT = 0, 1, 2, 3, 4, 5, 6


class Sheet:
    def __init__(self, name: str):
        self.name = name
        self.rows: list[list[tuple[Any, int]]] = []
        self.widths: dict[int, float] = {}
        self.freeze: Optional[tuple[int, int]] = None

    def row(self, values: Sequence[Any] = (), style: int = PLAIN,
            styles: Optional[Sequence[int]] = None) -> "Sheet":
        cells = []
        for i, v in enumerate(values):
            s = styles[i] if styles is not None and i < len(styles) else style
            cells.append((v, s))
        self.rows.append(cells)
        return self

    def blank(self) -> "Sheet":
        return self.row([])

    def width(self, col: int, w: float) -> "Sheet":
        self.widths[col] = w
        return self


class Workbook:
    def __init__(self) -> None:
        self.sheets: list[Sheet] = []

    def sheet(self, name: str) -> Sheet:
        name = _sheet_name(name, {s.name for s in self.sheets})
        s = Sheet(name)
        self.sheets.append(s)
        return s

    def to_bytes(self) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", _content_types(len(self.sheets)))
            z.writestr("_rels/.rels", _ROOT_RELS)
            z.writestr("xl/workbook.xml", _workbook(self.sheets))
            z.writestr("xl/_rels/workbook.xml.rels", _workbook_rels(len(self.sheets)))
            z.writestr("xl/styles.xml", _STYLES)
            for i, s in enumerate(self.sheets, start=1):
                z.writestr(f"xl/worksheets/sheet{i}.xml", _sheet_xml(s))
        return buf.getvalue()


# ---------------------------------------------------------------------------
# HoNI
# ---------------------------------------------------------------------------

SECTOR_LABELS = {"financial": "Financial Economy", "international": "International Resilience",
                 "real": "Real Economy"}


def _label(index: str) -> str:
    return index.replace("_", " ")


def honi_workbook(artefact: dict[str, Any], peers: Optional[dict[str, Any]],
                  ranges: Optional[dict[str, Any]], run: Optional[dict[str, Any]],
                  trends: Optional[dict[str, Any]] = None,
                  register: Optional[list[dict[str, Any]]] = None) -> Workbook:
    a = artefact
    years: list[int] = list(a["years"])
    countries: list[dict[str, str]] = list(a["countries"])
    names = [c["name"] for c in countries]
    indices = list(a["index_scores"].keys())
    prov = a.get("provenance") or {}
    last = len(years) - 1
    wb = Workbook()

    readme = wb.sheet("Read me").width(0, 28).width(1, 90)
    readme.row(["Health of Nations Index: CIO export"], TITLE)
    readme.row([a.get("notice") or NOTICE], WRAP)
    readme.blank()
    for k, v in [("Artefact", a["artefact_id"]), ("Snapshot", prov.get("snapshot_id")),
                 ("Data as of", prov.get("as_of")), ("Years", f"{years[0]} to {years[-1]}"),
                 ("Countries", ", ".join(f"{c['code']} {c['name']}" for c in countries)),
                 ("Calibration", f"{prov.get('calibration_version')} ({prov.get('calibration_hash')})"),
                 ("Engine", prov.get("engine_version")), ("Idempotency key", prov.get("idempotency_key")),
                 ("Label", prov.get("label")), ("Exported", _now())]:
        readme.row([k, v], styles=[HEADER, PLAIN])
    readme.blank()
    readme.row(["How to read it"], HEADER)
    for line in [
        "Scores run from 1 (worst) to 5 (best) and are relative by construction: in every year the "
        "best country in the peer set scores 5 and the worst 1. Changing the peer set changes every "
        "country's history.",
        "A blank cell is missing data. A missing index is excluded and its sector re-weighted; it is "
        "never scored as 1. A sector needs at least 3 of its 5 indices, the national score all three sectors.",
        "Capital saturation is total debt over GDP (corporate, government, household, plus financial "
        "sector debt). The capital saturation theory's balanced zone is 2.5 to 3.5.",
        "Every figure in this workbook was published by the honi engine; the cockpit computes nothing.",
    ]:
        readme.row(["", line], WRAP)
    if run and run.get("warnings"):
        readme.blank()
        readme.row(["Warnings on the run"], HEADER)
        for w in run["warnings"]:
            readme.row(["", w], WRAP)

    # Latest year overview, as the CIO reads it for the optimiser bounds.
    ov = wb.sheet(f"Overview {years[-1]}").width(1, 22)
    ov.freeze = (1, 2)
    head = ["Code", "Country", "HoNI", "Financial", "International", "Real",
            "Capital saturation", f"HoNI {years[-2]}" if len(years) > 1 else "HoNI prior"]
    head += [_label(i) for i in indices]
    ov.row(head, HEADER)
    order = sorted(range(len(countries)), key=lambda j: _sort_key(a["national"][last][j]))
    for j in order:
        prior = a["national"][last - 1][j] if last > 0 else None
        ov.row([countries[j]["code"], names[j], a["national"][last][j],
                *(a["sectors"][s][last][j] for s in SECTOR_LABELS),
                a["capital_saturation"][last][j], prior,
                *(a["index_scores"][i][last][j] for i in indices)],
               styles=[PLAIN, PLAIN] + [NUM2] * (6 + len(indices)))

    def matrix_sheet(title: str, m: list[list[Any]], note: str) -> None:
        s = wb.sheet(title)
        s.freeze = (2, 1)
        s.row([note], WRAP)
        s.row(["Year", *names], HEADER)
        for i, y in enumerate(years):
            s.row([y, *m[i]], styles=[HEADER] + [NUM2] * len(names))

    matrix_sheet("HoNI Score", a["national"], "National HoNI score, 1 to 5, years by countries.")
    for key, label in SECTOR_LABELS.items():
        matrix_sheet(label, a["sectors"][key], f"{label} sector score, 1 to 5, rescaled across the peer set each year.")
    matrix_sheet("Capital saturation", a["capital_saturation"], "Total debt as a multiple of GDP.")

    # One sheet per country, as the old export had: scores, then the raw values behind them.
    for j, c in enumerate(countries):
        s = wb.sheet(c["name"])
        s.freeze = (2, 1)
        s.row([f"{c['name']} ({c['code']}): scores 1 to 5, then the raw index values"], TITLE)
        s.row(["Year", "HoNI", *(SECTOR_LABELS[k].split()[0] for k in SECTOR_LABELS), "Capital saturation",
               *(_label(i) for i in indices), *(f"raw: {_label(i)}" for i in indices)], HEADER)
        for i, y in enumerate(years):
            s.row([y, a["national"][i][j], *(a["sectors"][k][i][j] for k in SECTOR_LABELS),
                   a["capital_saturation"][i][j], *(a["index_scores"][x][i][j] for x in indices),
                   *(a["index_raw"][x][i][j] for x in indices)],
                  styles=[HEADER] + [NUM2] * (5 + len(indices)) + [NUM4] * len(indices))

    if trends:
        t = wb.sheet(f"Trends {trends['window']}y")
        t.freeze = (2, 3)
        t.width(1, 18).width(2, 30)
        t.row([f"Trend and level over {trends['window']} years ({trends['first_year']} to {trends['year']}), "
               f"change against {trends['base_year']}, computed by honi (/trends). A slope or z-score needs "
               f"{trends['min_obs']} years with a value; blank means it could not be computed."], WRAP)
        t.row(["Code", "Country", "Series", "Sector", f"Value {trends['year']}", f"Value {trends['base_year']}",
               "Change", "Slope per year", "Level z", "Years with a value"], HEADER)
        for j, c in enumerate(trends["countries"]):
            for srs in trends["series"]:
                fmt = NUM4 if srs["basis"] == "raw" else NUM2
                t.row([c["code"], c["name"], srs["label"], srs.get("sector") or "", srs["latest"][j], srs["base"][j],
                       srs["change"][j], srs["slope"][j], srs["level_z"][j], srs["n"][j]],
                      styles=[PLAIN] * 4 + [fmt, fmt, fmt, NUM4, NUM2, PLAIN])
        t.blank()
        for k, v in trends.get("definitions", {}).items():
            t.row([k, v], styles=[HEADER, WRAP])

    if register:
        # The link from each economy to the instruments that carry it (fmre register).
        e = wb.sheet("Exposed instruments").width(1, 18).width(2, 32)
        e.freeze = (1, 0)
        e.row(["Code", "Country", "Instrument", "Role", "Asset class", "Currency", "Exposure"], HEADER)
        for c in countries:
            for r in register:
                codes = list(r.get("countries") or [])
                if c["code"] in codes:
                    others = [x for x in codes if x != c["code"]]
                    e.row([c["code"], c["name"], r["name"], r.get("role"), r.get("asset_class"), r.get("currency"),
                           "this economy only" if not others else "with " + ", ".join(others)])

    if peers:
        p = wb.sheet("Peer stats")
        p.freeze = (1, 0)
        p.row(["Index", "Year", "Basis", "n", "Min", "P25", "Median", "P75", "Max"], HEADER)
        for r in peers.get("rows", []):
            fmt = NUM2 if r["basis"] == "score" else NUM4
            p.row([_label(r["index"]), r["year"], r["basis"], r["n"], r["min"], r["p25"], r["median"],
                   r["p75"], r["max"]], styles=[PLAIN, PLAIN, PLAIN, PLAIN] + [fmt] * 5)
        p.width(0, 28)

    cov = a.get("coverage") or {}
    s = wb.sheet("Coverage").width(0, 30).width(1, 34)
    s.row(["Coverage of this artefact"], TITLE)
    for k in ["country_years", "index_cells", "index_cells_missing", "sectors_reweighted",
              "sectors_unscored", "national_unscored"]:
        s.row([k.replace("_", " "), cov.get(k)], styles=[HEADER, PLAIN])
    s.blank()
    s.row(["Series with gaps", "Series", "Missing months", "Of"], HEADER)
    for r in cov.get("missing_series", []):
        s.row([r["country"], r["series_id"], r["missing_months"], r["total_months"]])
    s.blank()
    s.row(["Sectors dropped or re-weighted", "Year", "Sector", "Scored", "Indices missing"], HEADER)
    for r in cov.get("dropped", []):
        s.row([r["country"], r["year"], r["sector"], "yes" if r["scored"] else "no",
               ", ".join(r["indices_missing"])])
    s.blank()
    s.row(["Filled from public sources", "Series", "Source", "First", "Last"], HEADER)
    for r in cov.get("public_fills", []):
        s.row([r["country"], r["series_id"], r["source"], r["first"], r["last"]])
    if cov.get("excluded"):
        s.blank()
        s.row(["Excluded on datafeed findings", "Index", "Reason"], HEADER)
        for r in cov["excluded"]:
            s.row([r["country"], r["index"], r["reason"]])

    if ranges:
        s = wb.sheet("Calibration").width(0, 28).width(7, 70)
        s.row([f"Calibration {ranges.get('calibration_version')}: raw value to score"], TITLE)
        s.row(["Index", "Sector", "Function", "Min", "Mid", "Max", "Weight", "Definition"], HEADER)
        for r in ranges.get("indices", []):
            lo, mid, hi = r["range"]
            s.row([_label(r["index"]), r["sector"], r["kind"], lo, mid, hi, r.get("weight"),
                   r.get("definition", "")], styles=[PLAIN] * 3 + [NUM4] * 3 + [NUM2, WRAP])
        s.row(["Ramp: 1 at min, 2.5 at mid, 5 at max. Tent: 5 at mid, 1 at and beyond either end."], WRAP)
    return wb


def _sort_key(v: Any) -> tuple[int, float]:
    # Highest score first, missing last. Ordering only; no figure is changed.
    return (1, 0.0) if v is None else (0, -float(v))


# ---------------------------------------------------------------------------
# Instruments (Fund Map engine)
# ---------------------------------------------------------------------------

PERF_FIELDS = [("months", "Months", PLAIN), ("first_period", "First", PLAIN), ("last_period", "Last", PLAIN),
               ("annualised_log_return", "Ann. log return", PCT), ("annualised_volatility", "Ann. volatility", PCT),
               ("return_over_volatility", "Return / vol", NUM2), ("max_drawdown", "Max drawdown", PCT),
               ("best_month", "Best month", PCT), ("worst_month", "Worst month", PCT), ("hit_rate", "Hit rate", PCT)]


def instruments_workbook(register: list[dict[str, Any]], performance: dict[str, Any],
                         classification: Optional[dict[str, Any]], overlap: Optional[dict[str, Any]],
                         return_set: Optional[dict[str, Any]], axis: Optional[dict[str, Any]],
                         shortlist: Optional[dict[str, Any]] = None,
                         trends: Optional[dict[str, Any]] = None) -> Workbook:
    wb = Workbook()
    perf = {r["instrument_id"]: r for r in performance.get("instruments", [])}
    flags = {r["instrument_id"]: r for r in (classification or {}).get("instruments", [])}
    picks = {r["instrument_id"]: r for r in (shortlist or {}).get("rows", [])}

    readme = wb.sheet("Read me").width(0, 24).width(1, 100)
    readme.row(["Instrument universe: CIO export"], TITLE)
    readme.row([NOTICE], WRAP)
    readme.blank()
    for k, v in [("Calibration", performance.get("calibration_id")),
                 ("HoNI artefact", (trends or {}).get("artefact_id", "not linked")),
                 ("Return set", (return_set or {}).get("return_set_id")),
                 ("Registered", performance.get("registered")),
                 ("With history", performance.get("with_history")),
                 ("Shortlist", (shortlist or {}).get("decision_id", "none saved")),
                 ("Exported", _now())]:
        readme.row([k, v], styles=[HEADER, PLAIN])
    readme.blank()
    for line in [performance.get("unit_note"), performance.get("caveat"),
                 "Profiles are annualised log returns per state of the 25-state axis (crisis to boom), "
                 "each with the method that produced it. The engine publishes no mean, variance or covariance."]:
        if line:
            readme.row(["", line], WRAP)

    s = wb.sheet("Universe")
    s.freeze = (1, 2)
    s.width(1, 30)
    head = ["Id", "Name", "Role", "Asset class", "Region", "Geography", "Countries", "Currency", "Liquidity", "Ticker",
            "Profile coverage", "Borrowed from", "Proxy", *(h for _, h, _ in PERF_FIELDS),
            "Equity beta", "Crisis mean", "Classification flag"]
    if shortlist:
        head += ["CIO decision", "CIO note"]
    s.row(head, HEADER)
    for r in register:
        p = perf.get(r["instrument_id"], {})
        m = p.get("performance") or {}
        f = flags.get(r["instrument_id"], {})
        row = [r["instrument_id"], r["name"], r.get("role"), r.get("asset_class"), r.get("region_scope"),
               r.get("region_geo"), ", ".join(r.get("countries") or []) or "no single economy",
               r.get("currency"), r.get("liquidity"), r.get("ticker"),
               p.get("coverage"), p.get("borrowed_from"), p.get("proxy_symbol"),
               *(m.get(k) for k, _, _ in PERF_FIELDS), f.get("equity_beta"), f.get("crisis_mean"), f.get("flag")]
        styles = [PLAIN] * 13 + [st for _, _, st in PERF_FIELDS] + [NUM2, PCT, PLAIN]
        if shortlist:
            pick = picks.get(r["instrument_id"], {})
            row += [pick.get("decision"), pick.get("note")]
            styles += [PLAIN, PLAIN]
        s.row(row, styles=styles)

    if trends:
        # One row per instrument and economy, with that economy's published HoNI figures.
        national = next(x for x in trends["series"] if x["key"] == "national")
        col = {c["code"]: j for j, c in enumerate(trends["countries"])}
        names = {c["code"]: c["name"] for c in trends["countries"]}
        s = wb.sheet("HoNI exposure").width(0, 30).width(2, 18)
        s.freeze = (2, 1)
        s.row([f"HoNI of every economy an instrument is exposed to: score in {trends['year']}, change against "
               f"{trends['base_year']} and level z over {trends['window']} years, as honi publishes them "
               f"(artefact {trends['artefact_id']})."], WRAP)
        s.row(["Instrument", "Code", "Country", "Role", f"HoNI {trends['year']}", f"HoNI {trends['base_year']}",
               "Change", "Level z", "Exposure"], HEADER)
        for r in register:
            codes = list(r.get("countries") or [])
            for code in codes:
                j = col.get(code)
                vals = [national[k][j] if j is not None else None for k in ("latest", "base", "change", "level_z")]
                s.row([r["name"], code, names.get(code, code), r.get("role"), *vals,
                       "single economy" if len(codes) == 1 else f"one of {len(codes)}"],
                      styles=[PLAIN] * 4 + [NUM2] * 4 + [PLAIN])

    if return_set:
        states = [st["state"] for st in return_set["role_profiles"][0]["states"]]
        grid = (axis or {}).get("state_axis") or [None] * len(states)
        roles = return_set["role_profiles"]
        s = wb.sheet("Role profiles")
        s.row(["State", "Axis", *(r["role"] for r in roles), *(f"method: {r['role']}" for r in roles)], HEADER)
        for k, st in enumerate(states):
            s.row([st, grid[k], *(r["states"][k]["value"] for r in roles),
                   *(r["states"][k]["method"] for r in roles)],
                  styles=[PLAIN, NUM2] + [PCT] * len(roles) + [PLAIN] * len(roles))
        profiles = return_set["instrument_profiles"]
        names = {r["instrument_id"]: r["name"] for r in register}
        s = wb.sheet("Instrument profiles")
        s.freeze = (1, 2)
        s.row(["State", "Axis", *(names.get(p["key"], p["key"]) for p in profiles)], HEADER)
        for k, st in enumerate(states):
            s.row([st, grid[k], *(p["states"][k]["value"] for p in profiles)],
                  styles=[PLAIN, NUM2] + [PCT] * len(profiles))
        s = wb.sheet("Profile methods")
        s.freeze = (1, 1)
        s.row(["State", *(names.get(p["key"], p["key"]) for p in profiles)], HEADER)
        for k, st in enumerate(states):
            s.row([st, *(p["states"][k]["method"] for p in profiles)])

    if overlap:
        s = wb.sheet("Register integrity").width(0, 34).width(1, 34)
        s.row(["Instruments sharing a ticker"], TITLE)
        for r in overlap.get("ticker_collisions", []):
            s.row([r["ticker"], ", ".join(r["instruments"])])
        for key, title in [("register_defect", "Register defects"), ("proxy_artefact", "Proxy artefacts"),
                           ("economic_overlap", "Economic overlap")]:
            s.blank()
            s.row([title, "", "Correlation", "Shared months", "Proxy"], HEADER)
            for r in overlap.get(key, []):
                s.row([r.get("a"), r.get("b"), r.get("correlation"), r.get("shared_months"), r.get("proxy")],
                      styles=[PLAIN, PLAIN, NUM4, PLAIN, PLAIN])
        if classification:
            s.blank()
            s.row(["Classification flags", "Flag", "Explanation"], HEADER)
            for r in classification.get("instruments", []):
                if r.get("flag"):
                    s.row([r["name"], r["flag"], r.get("explanation")], styles=[PLAIN, PLAIN, WRAP])
    return wb


# ---------------------------------------------------------------------------
# A saved CIO decision
# ---------------------------------------------------------------------------

def decision_workbook(decision: dict[str, Any]) -> Workbook:
    wb = Workbook()
    s = wb.sheet("Decision").width(0, 22).width(1, 60)
    s.row([decision["title"]], TITLE)
    s.row([NOTICE], WRAP)
    s.blank()
    for k, v in [("Decision", decision["decision_id"]), ("Kind", decision["kind"].replace("_", " ")),
                 ("Saved", decision["saved_at"]), ("Author", decision.get("author")),
                 ("Note", decision.get("note")),
                 *((f"Basis: {k}", v) for k, v in (decision.get("basis") or {}).items())]:
        s.row([k, v], styles=[HEADER, WRAP])
    rows = decision["rows"]
    s = wb.sheet("Rows")
    if decision["kind"] == "optimiser_bounds":
        s.row(["Code", "Country", "Minimum %", "Maximum %", "Note"], HEADER)
        for r in rows:
            s.row([r["code"], r.get("name"), r.get("min_pct"), r.get("max_pct"), r.get("note")],
                  styles=[PLAIN, PLAIN, NUM2, NUM2, WRAP])
    else:
        s.row(["Instrument", "Name", "Role", "Decision", "Note"], HEADER)
        for r in rows:
            s.row([r["instrument_id"], r.get("name"), r.get("role"), r.get("decision"), r.get("note")])
    s.width(1, 30).width(4, 60)
    return wb


# ---------------------------------------------------------------------------
# XML parts
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sheet_name(name: str, taken: set[str]) -> str:
    base = re.sub(r"[\[\]:*?/\\]", " ", name).strip()[:31] or "Sheet"
    out, n = base, 2
    while out in taken:
        suffix = f" ({n})"
        out, n = base[: 31 - len(suffix)] + suffix, n + 1
    return out


def _col(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


_ILLEGAL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _cell(ref: str, value: Any, style: int) -> str:
    s = f' s="{style}"' if style else ""
    if value is None:
        return f'<c r="{ref}"{s}/>' if style else ""
    if isinstance(value, bool):
        return f'<c r="{ref}"{s} t="b"><v>{int(value)}</v></c>'
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return f'<c r="{ref}"{s}/>'
        return f'<c r="{ref}"{s}><v>{repr(value) if isinstance(value, float) else value}</v></c>'
    text = escape(_ILLEGAL.sub("", str(value)))
    return f'<c r="{ref}"{s} t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'


def _sheet_xml(sheet: Sheet) -> str:
    parts = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">']
    if sheet.freeze:
        r, c = sheet.freeze
        top = f"{_col(c)}{r + 1}"
        attrs = (f' xSplit="{c}"' if c else "") + (f' ySplit="{r}"' if r else "")
        pane = "bottomRight" if r and c else ("bottomLeft" if r else "topRight")
        parts.append(f'<sheetViews><sheetView workbookViewId="0"><pane{attrs} topLeftCell="{top}" '
                     f'activePane="{pane}" state="frozen"/></sheetView></sheetViews>')
    ncols = max((len(r) for r in sheet.rows), default=0)
    if ncols:
        cols = []
        for i in range(ncols):
            w = sheet.widths.get(i, 12 if i else 14)
            cols.append(f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>')
        parts.append("<cols>" + "".join(cols) + "</cols>")
    parts.append("<sheetData>")
    for r, cells in enumerate(sheet.rows, start=1):
        body = "".join(_cell(f"{_col(c)}{r}", v, st) for c, (v, st) in enumerate(cells))
        parts.append(f'<row r="{r}">{body}</row>')
    parts.append("</sheetData></worksheet>")
    return "".join(parts)


def _content_types(n: int) -> str:
    sheets = "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/'
                     f'vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1, n + 1))
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>' + sheets + "</Types>")


_ROOT_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
              '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
              'relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')


def _workbook(sheets: Iterable[Sheet]) -> str:
    body = "".join(f'<sheet name="{escape(s.name, {chr(34): "&quot;"})}" sheetId="{i}" r:id="rId{i}"/>'
                   for i, s in enumerate(sheets, start=1))
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f"<sheets>{body}</sheets></workbook>")


def _workbook_rels(n: int) -> str:
    rels = "".join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/'
                   f'2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, n + 1))
    rels += (f'<Relationship Id="rId{n + 1}" Type="http://schemas.openxmlformats.org/officeDocument/'
             f'2006/relationships/styles" Target="styles.xml"/>')
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f"{rels}</Relationships>")


# cellXfs order is the style ids above: plain, header, 0.00, 0.0000, wrapped, title, 0.00%.
_STYLES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
           '<numFmts count="1"><numFmt numFmtId="164" formatCode="0.0000"/></numFmts>'
           '<fonts count="3"><font><sz val="11"/><name val="Calibri"/></font>'
           '<font><b/><sz val="11"/><name val="Calibri"/></font>'
           '<font><b/><sz val="14"/><name val="Calibri"/></font></fonts>'
           '<fills count="3"><fill><patternFill patternType="none"/></fill>'
           '<fill><patternFill patternType="gray125"/></fill>'
           '<fill><patternFill patternType="solid"><fgColor rgb="FFEAF1FB"/><bgColor indexed="64"/>'
           '</patternFill></fill></fills>'
           '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
           '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
           '<cellXfs count="7">'
           '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
           '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>'
           '<xf numFmtId="2" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
           '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
           '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1">'
           '<alignment wrapText="1" vertical="top"/></xf>'
           '<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
           '<xf numFmtId="10" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
           '</cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
           '</styleSheet>')
