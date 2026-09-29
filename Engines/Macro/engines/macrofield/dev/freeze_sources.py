"""Freeze the raw source files the engine runs on into ``data/raw``. Development only.

The engine never fetches. It reads a frozen snapshot, verified against ``data/raw/MANIFEST.json``,
so a run is reproducible bit for bit and the data need is stated rather than implied. This tool
builds that snapshot once; the Data Feed engine replaces it later (README, "Data need").

Where the old ``macrofield`` build already holds a file, that exact file is copied, so the golden
reconciliation compares like with like. Everything else is fetched live from the published,
keyless endpoint. Every file lands in the manifest with its SHA-256, size, URL, retrieval date and
origin, and a snapshot is never edited: re-running into a non-empty folder is refused.

    python dev/freeze_sources.py                      # into data/raw
    python dev/freeze_sources.py --out some/folder    # anywhere else
    python dev/freeze_sources.py --base data/archive/SNP-... --out data/raw_new
                                                      # a new snapshot: the base's files copied
                                                      # verbatim with their provenance, plus any
                                                      # file the base lacks
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import shutil
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]

#: The old build's download cache. Copied from, never written to.
LEGACY_CACHE = Path(
    r"C:\Users\nicol\Desktop\SIM_NAS\Projects\eigentliCH\engines\Macro_Model\macrofield\data\cache"
)

WORLD_BANK_INDICATORS = (
    "NY.GDP.MKTP.CD",      # output, current USD
    "NE.GDI.FTOT.ZS",      # gross fixed capital formation, % of GDP
    "NY.GDP.MKTP.KD.ZG",   # real output growth, %
    "NY.GNS.ICTR.ZS",      # gross national savings, % of GDP
    "GC.NLD.TOTL.GD.ZS",   # general government net lending, % of GDP
    "SP.POP.TOTL",         # population
)

#: World Bank country codes for every economy in the HoNI universe.
WORLD_BANK_COUNTRIES = ("USA", "DEU", "GBR", "CHE", "CHN", "IND", "BRA", "JPN",
                        "IDN", "MYS", "THA", "ESP", "EMU", "PHL", "BGD", "VNM")

#: The request window the old build used. Kept identical so its cached payloads are the same
#: documents a fresh request would return on that date.
WB_START, WB_END = 1960, 2026

#: Genreith's German series and the denominators for them (calibration 1.2.0 onwards).
BUNDESBANK = {
    "bundesbank/BBBK1_M_OU0308.csv":
        "https://api.statistiken.bundesbank.de/rest/data/BBBK1/M.OU0308?format=csv&lang=en",
    "bundesbank/BBBK1_M_OU0115.csv":
        "https://api.statistiken.bundesbank.de/rest/data/BBBK1/M.OU0115?format=csv&lang=en",
}
#: The JST download link is named .xlsx but serves a Stata release 118 file; it is stored under
#: the name of what it is.
JST = {"jst/JSTdatasetR6.dta": "https://www.macrohistory.net/app/download/9834512469/JSTdatasetR6.xlsx"}
LCU_GDP_COUNTRIES = ("DEU",)
#: IMF DataMapper (keyless), whole panels: WEO fiscal balance and government debt, Global Debt
#: Database private and government debt (calibration 1.3.0 onwards). WEO panels include the
#: IMF's forecasts; the engine cuts them at the calibration's last actual year.
IMF = {f"imf/{ind}.json": f"https://www.imf.org/external/datamapper/api/v1/{ind}"
       for ind in ("GGXCNL_NGDP", "GGXWDG_NGDP", "PVD_LS", "GG_DEBT_GDP")}

BIS_URL = "https://data.bis.org/static/bulk/WS_TC_csv_flat.zip"
PWT_URL = "https://dataverse.nl/api/access/datafile/354095"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def legacy_index() -> dict[str, dict]:
    path = LEGACY_CACHE / "index.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def legacy_file(index: dict[str, dict], url_fragment: str) -> tuple[Path, dict] | None:
    """The cached payload whose URL contains the fragment, if exactly one does."""
    hits = [e for e in index.values() if url_fragment in e["url"]]
    if not hits:
        return None
    digests = {e["sha256"] for e in hits}
    if len(digests) > 1:
        raise SystemExit(f"legacy cache holds conflicting payloads for {url_fragment}: {digests}")
    entry = hits[0]
    return LEGACY_CACHE / entry["filename"], entry


def fetch(url: str, target: Path) -> None:
    response = httpx.get(url, timeout=180, follow_redirects=True,
                         headers={"User-Agent": "sim-tech macrofield freeze_sources"})
    response.raise_for_status()
    if not response.content:
        raise SystemExit(f"empty body from {url}")
    target.write_bytes(response.content)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "raw")
    parser.add_argument("--base", type=Path, default=None,
                        help="an existing snapshot folder whose files are carried over verbatim")
    args = parser.parse_args(argv)

    out: Path = args.out
    if out.exists() and any(p.name != ".gitkeep" for p in out.iterdir()):
        print(f"{out} is not empty. A snapshot is never edited; freeze into a new folder.",
              file=sys.stderr)
        return 2
    out.mkdir(parents=True, exist_ok=True)

    index = legacy_index()
    today = dt.date.today().isoformat()
    files: list[dict] = []

    def record(relative: str, url: str, retrieved_on: str, origin: str) -> None:
        path = out / relative
        files.append({"path": relative, "sha256": sha256(path), "bytes": path.stat().st_size,
                      "url": url, "retrieved_on": retrieved_on, "origin": origin})
        print(f"  {origin:<16} {relative}")

    def take(relative: str, url: str, fragment: str) -> None:
        target = out / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        cached = legacy_file(index, fragment)
        if cached is not None:
            shutil.copyfile(cached[0], target)
            record(relative, cached[1]["url"], cached[1]["retrieved_on"], "macrofield cache")
        else:
            fetch(url, target)
            record(relative, url, today, "live fetch")

    carried: set[str] = set()
    if args.base is not None:
        base = json.loads((args.base / "MANIFEST.json").read_text(encoding="utf-8"))
        for entry in base["files"]:
            source = args.base / entry["path"]
            if sha256(source) != entry["sha256"]:
                print(f"{entry['path']} in the base does not match its manifest", file=sys.stderr)
                return 3
            target = out / entry["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            files.append(dict(entry))
            carried.add(entry["path"])
        print(f"  {len(carried)} files carried over from {args.base}")

    def take_new(relative: str, url: str, fragment: str) -> None:
        if relative not in carried:
            take(relative, url, fragment)

    take_new("bis/WS_TC_csv_flat.zip", BIS_URL, BIS_URL)
    take_new("pwt/pwt1001.xlsx", PWT_URL, PWT_URL)
    for country in WORLD_BANK_COUNTRIES:
        for indicator in WORLD_BANK_INDICATORS:
            url = (f"https://api.worldbank.org/v2/country/{country}/indicator/{indicator}"
                   f"?date={WB_START}:{WB_END}&format=json&per_page=20000")
            take_new(f"worldbank/{country}/{indicator}.json", url, url)
    for country in LCU_GDP_COUNTRIES:
        url = (f"https://api.worldbank.org/v2/country/{country}/indicator/NY.GDP.MKTP.CN"
               f"?date={WB_START}:{WB_END}&format=json&per_page=20000")
        take_new(f"worldbank/{country}/NY.GDP.MKTP.CN.json", url, url)
    for relative, url in {**BUNDESBANK, **JST, **IMF}.items():
        take_new(relative, url, url)

    files.sort(key=lambda f: f["path"])
    manifest = {
        "description": "Frozen raw sources for the macrofield engine. Never edited; a new "
                       "freeze is a new snapshot.",
        "frozen_on": today,
        "files": files,
    }
    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    print(f"{len(files)} files frozen into {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
