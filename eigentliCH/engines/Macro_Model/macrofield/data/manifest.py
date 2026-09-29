"""The data manifest and the raw-pull cache.

Brief section 2 requires that provenance records be written to a data manifest, that raw pulls be
cached and checked for staleness, and that an offline mode run reproducibly from that cache without
live network access. Brief section 7 requires offline runs to be bit-reproducible.

Two artefacts, kept separate on purpose:

- The **cache** holds raw payloads exactly as retrieved, keyed by a hash of the request. It is the
  reproducibility guarantee: an offline run reads bytes that a live run wrote, so the parse path is
  identical and nothing depends on the network.
- The **manifest** holds the provenance of every series that was loaded, with its coverage and gaps.
  It is the audit record, and it is what a reader consults to check where a number came from.

Bit-reproducibility needs one more thing beyond caching, which is that nothing in the written artefacts
depends on wall-clock time or dictionary iteration order. Keys are sorted, and retrieval dates come
from the cache entry rather than from `today`, so re-serialising an unchanged manifest produces
identical bytes.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from macrofield.data.provenance import ProvenanceRecord, Series

#: Version of the manifest format, so a stale manifest can be recognised rather than misread.
MANIFEST_VERSION = 1


class CacheError(RuntimeError):
    """Raised when the cache cannot satisfy a request."""


class OfflineError(CacheError):
    """Raised when an offline run needs a payload the cache does not hold."""


def request_key(source: str, identifier: str, **parameters: Any) -> str:
    """Return a stable cache key for a request.

    The key is a hash of the source, identifier and sorted parameters, so the same logical request
    always maps to the same entry regardless of the order keyword arguments were passed in.
    """
    payload = json.dumps(
        {"source": source, "identifier": identifier, "parameters": parameters},
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    safe_source = "".join(c if c.isalnum() else "_" for c in source.lower())
    safe_identifier = "".join(c if c.isalnum() else "_" for c in identifier.lower())[:48]
    return f"{safe_source}__{safe_identifier}__{digest}"


@dataclass(frozen=True)
class CacheEntry:
    """One cached raw payload.

    Attributes:
        key: The request key.
        retrieved_on: When the payload was fetched. Read from the entry, never from the clock, so that
            an offline run reproduces the original retrieval date.
        url: The URL it came from.
        content_type: How to parse the payload, for example "json" or "csv".
        path: Where the payload sits on disk.
    """

    key: str
    retrieved_on: dt.date
    url: str
    content_type: str
    path: Path

    def age_days(self, today: dt.date | None = None) -> int:
        """Age in days, against a supplied date so tests need not depend on the clock."""
        reference = today or dt.date.today()
        return (reference - self.retrieved_on).days

    def is_stale(self, staleness_days: int, today: dt.date | None = None) -> bool:
        return self.age_days(today) > staleness_days


class Cache:
    """A directory of cached raw pulls with an index.

    The index is a JSON file recording what each payload is and when it was fetched. Payloads are
    stored as separate files so that a large CSV does not have to be parsed to read the index.
    """

    INDEX_NAME = "index.json"

    def __init__(self, directory: Path, offline: bool = False) -> None:
        self.directory = Path(directory)
        self.offline = offline
        self._index: dict[str, dict[str, Any]] = {}
        self._load_index()

    # --- index handling ---

    @property
    def index_path(self) -> Path:
        return self.directory / self.INDEX_NAME

    def _load_index(self) -> None:
        if self.index_path.exists():
            with self.index_path.open("r", encoding="utf-8") as handle:
                self._index = json.load(handle)
        else:
            self._index = {}

    def _write_index(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        with self.index_path.open("w", encoding="utf-8") as handle:
            json.dump(self._index, handle, indent=2, sort_keys=True)
            handle.write("\n")

    # --- reading and writing payloads ---

    def entry(self, key: str) -> CacheEntry | None:
        """Return the entry for a key, or None if it is not cached."""
        record = self._index.get(key)
        if record is None:
            return None
        return CacheEntry(
            key=key,
            retrieved_on=dt.date.fromisoformat(record["retrieved_on"]),
            url=record["url"],
            content_type=record["content_type"],
            path=self.directory / record["filename"],
        )

    def has(self, key: str) -> bool:
        entry = self.entry(key)
        return entry is not None and entry.path.exists()

    def read(self, key: str) -> tuple[bytes, CacheEntry]:
        """Read a cached payload.

        Raises:
            CacheError: If the key is absent or its payload file is missing.
        """
        entry = self.entry(key)
        if entry is None:
            raise CacheError(f"nothing cached under key {key!r}")
        if not entry.path.exists():
            raise CacheError(
                f"the index records key {key!r} but its payload file {entry.path} is missing. The "
                f"cache is inconsistent; delete the index entry and refresh."
            )
        return entry.path.read_bytes(), entry

    def write(
        self,
        key: str,
        payload: bytes,
        url: str,
        content_type: str,
        retrieved_on: dt.date | None = None,
    ) -> CacheEntry:
        """Store a raw payload and index it."""
        self.directory.mkdir(parents=True, exist_ok=True)
        filename = f"{key}.{content_type}"
        path = self.directory / filename
        path.write_bytes(payload)
        stamp = retrieved_on or dt.date.today()
        self._index[key] = {
            "url": url,
            "content_type": content_type,
            "retrieved_on": stamp.isoformat(),
            "filename": filename,
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        self._write_index()
        return CacheEntry(key, stamp, url, content_type, path)

    def verify(self, key: str) -> bool:
        """Check a payload against the digest recorded when it was written.

        Guards the reproducibility claim: a cache whose bytes have changed since they were indexed
        cannot deliver an identical offline run, and that must be detectable.
        """
        record = self._index.get(key)
        if record is None:
            return False
        path = self.directory / record["filename"]
        if not path.exists():
            return False
        return hashlib.sha256(path.read_bytes()).hexdigest() == record.get("sha256")

    def stale_keys(self, staleness_days: int, today: dt.date | None = None) -> list[str]:
        """Return the cached keys older than the staleness threshold."""
        return sorted(
            key
            for key in self._index
            if (entry := self.entry(key)) is not None and entry.is_stale(staleness_days, today)
        )

    def require_offline(self, key: str, description: str) -> None:
        """Raise a clear error when an offline run needs an uncached payload.

        Raises:
            OfflineError: Always, when called.
        """
        raise OfflineError(
            f"offline mode is enabled but {description} is not cached (key {key!r}). Run once with "
            f"data.offline set to false to populate the cache, or narrow the requested window to what "
            f"the cache already holds. The brief requires a run that needs an unavailable input to "
            f"fail loudly rather than guess."
        )


@dataclass
class Manifest:
    """The audit record of every series a run loaded.

    Attributes:
        entries: Series entries keyed by "economy/quantity".
        config_sources: The configuration files the run was assembled from.
        notes: Run-level notes, for example that offline mode was used.
    """

    entries: dict[str, dict[str, Any]] = field(default_factory=dict)
    config_sources: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def record(self, economy: str, series: Series) -> None:
        """Add a series to the manifest."""
        self.entries[f"{economy}/{series.name}"] = series.as_manifest_entry()

    def record_all(self, economy: str, series: Iterable[Series]) -> None:
        for item in series:
            self.record(economy, item)

    def as_dict(self) -> dict[str, Any]:
        """Render for serialisation. Keys are sorted so output is byte-stable."""
        return {
            "manifest_version": MANIFEST_VERSION,
            "config_sources": sorted(self.config_sources),
            "notes": list(self.notes),
            "series": {key: self.entries[key] for key in sorted(self.entries)},
        }

    def write(self, path: Path) -> None:
        """Write the manifest as JSON.

        No timestamp is written, so re-serialising an unchanged manifest produces identical bytes,
        which is what makes an offline run bit-reproducible.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(self.as_dict(), handle, indent=2, sort_keys=False)
            handle.write("\n")

    @classmethod
    def read(cls, path: Path) -> "Manifest":
        """Read a manifest from disk.

        Raises:
            ValueError: If the manifest was written by a different format version.
        """
        with Path(path).open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        version = payload.get("manifest_version")
        if version != MANIFEST_VERSION:
            raise ValueError(
                f"manifest at {path} is version {version}, this build expects {MANIFEST_VERSION}. "
                f"Regenerate it rather than reading it."
            )
        return cls(
            entries=dict(payload.get("series") or {}),
            config_sources=list(payload.get("config_sources") or []),
            notes=list(payload.get("notes") or []),
        )

    def provenance_of(self, economy: str, quantity: str) -> ProvenanceRecord:
        """Return the provenance of a recorded series.

        Raises:
            KeyError: If the series is not in the manifest.
        """
        key = f"{economy}/{quantity}"
        if key not in self.entries:
            raise KeyError(f"{key!r} is not in the manifest. Recorded: {sorted(self.entries)}")
        return ProvenanceRecord.from_dict(self.entries[key]["provenance"])

    def summary(self) -> dict[str, Any]:
        """A short summary for the run report."""
        with_gaps = [
            key for key, entry in self.entries.items() if entry["gaps"]["missing_count"] > 0
        ]
        reliabilities: dict[str, int] = {}
        for entry in self.entries.values():
            level = entry["provenance"]["reliability"]
            reliabilities[level] = reliabilities.get(level, 0) + 1
        return {
            "series_count": len(self.entries),
            "series_with_gaps": sorted(with_gaps),
            "reliability_counts": dict(sorted(reliabilities.items())),
            "sources": sorted({e["provenance"]["source"] for e in self.entries.values()}),
        }
