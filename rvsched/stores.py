"""Where records live. The store holds addresses (evidence URLs, verdicts),
never proofs or designs: the empty-center pattern from 0x-auth/void.

Layout, identical on disk and over HTTP, so a directory committed to git is
readable from anywhere through its raw URL:

    <root>/<first 2 hex>/<hex>.jsonl     one JSON record per line, append-only
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterator, Optional

from .core import Record, store


def _key(fingerprint: str) -> str:
    h = fingerprint.split(':', 1)[-1]
    if len(h) < 8 or not all(c in '0123456789abcdef' for c in h):
        raise ValueError(f"bad fingerprint: {fingerprint!r}")
    return f"{h[:2]}/{h}.jsonl"


def _latest(lines: list[str]) -> Optional[Record]:
    """Newest record that carries a real outcome; else newest record."""
    recs = [Record.from_dict(json.loads(l)) for l in lines if l.strip()]
    if not recs:
        return None
    with_outcome = [r for r in recs if r.outcome and r.outcome.status != "unknown"]
    return (with_outcome or recs)[-1]


@store("dir")
class DirStore:
    def __init__(self, location: str):
        self.root = Path(location)

    def get(self, fingerprint: str) -> Optional[Record]:
        p = self.root / _key(fingerprint)
        return _latest(p.read_text().splitlines()) if p.exists() else None

    def put(self, r: Record) -> None:
        p = self.root / _key(r.fingerprint)
        p.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(r.to_dict(), sort_keys=True) + "\n"
        with open(p, "a") as f:          # single small append: atomic enough
            f.write(line)
            f.flush()
            os.fsync(f.fileno())

    def all(self) -> Iterator[Record]:
        for p in sorted(self.root.glob("??/*.jsonl")):
            for l in p.read_text().splitlines():
                if l.strip():
                    yield Record.from_dict(json.loads(l))


@store("https")
class HttpStore:
    """Read-only. Point it at the raw URL of a committed store directory, e.g.
    https://raw.githubusercontent.com/<owner>/<repo>/main/.rvsched"""
    def __init__(self, location: str, timeout: float = 10.0):
        self.base = location.rstrip("/")
        self.timeout = timeout

    def get(self, fingerprint: str) -> Optional[Record]:
        try:
            with urllib.request.urlopen(f"{self.base}/{_key(fingerprint)}",
                                        timeout=self.timeout) as resp:
                return _latest(resp.read().decode().splitlines())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise

    def put(self, r: Record) -> None:
        raise PermissionError("https store is read-only; record locally and commit")

    def all(self) -> Iterator[Record]:
        return iter(())
