"""The registry seed: ``seed/registry.yaml`` as contract objects.

Read by the bootstrap to fill empty ``country`` and ``series`` tables, and by the importer
tests. After the first bootstrap the database is the registry.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from ..contracts import Country, SeriesSpec
from ..settings import ROOT

SEED = ROOT / "seed" / "registry.yaml"


def load_seed(path: Path = SEED) -> tuple[list[Country], list[SeriesSpec]]:
    tree = yaml.safe_load(path.read_text(encoding="utf-8"))
    countries = [Country(code=c["code"], name=c["name"], iso3=c["iso3"], matlab=c.get("matlab"))
                 for c in tree["countries"]]
    series = [SeriesSpec(series_id=s["id"], category=s["category"], unit=s["unit"], period=s["period"],
                         indices=tuple(s.get("indices") or ()),
                         matlab_sheet=(s.get("matlab") or [None, None])[0],
                         matlab_column=(s.get("matlab") or [None, None])[1],
                         zero_is_a_value=bool(s.get("zero_is_a_value", False)),
                         description=str(s.get("description", "")))
              for s in tree["series"]]
    return countries, series
