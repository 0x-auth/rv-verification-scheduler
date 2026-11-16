"""The frozen core. Three verbs and one record.

    recognize(source)        -> what class is this module in?   (cheap, no search)
    resolve(fingerprint)     -> has this exact structure been run before?
    record(fp, pred, out)    -> write down what the tool actually did

Everything else (languages and stores) plugs in through the registry
below. This file should not need to change to add any of them.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from importlib.metadata import entry_points
from typing import Optional

SCHEMA = "rvsched/1"

ENGINES = ("FORMAL", "SIMULATION", "HYBRID_SPLIT")
STATUSES = ("proved", "failed", "timeout", "unknown")


@dataclass
class Verdict:
    """What a recognizer predicts. No solving happened to get it."""
    engine: str
    confidence: float
    reason: str
    recognizer: str
    metrics: dict = field(default_factory=dict)


@dataclass
class Outcome:
    """What a real tool did. This is ground truth."""
    engine: str
    status: str               # proved | failed | timeout | unknown
    seconds: Optional[float] = None
    evidence: Optional[str] = None   # URL or path to the log / proof


@dataclass
class Record:
    """One line of history for one structure. The protocol's unit."""
    fingerprint: str
    module: str
    prediction: Verdict
    outcome: Optional[Outcome] = None
    schema: str = SCHEMA
    created: float = field(default_factory=time.time)

    @property
    def miss(self) -> Optional[bool]:
        """True if the prediction disagreed with reality, None if no outcome."""
        if self.outcome is None or self.outcome.status == "unknown":
            return None
        p, o = self.prediction.engine, self.outcome
        if p == "FORMAL":
            return o.engine == "FORMAL" and o.status == "timeout"
        if p == "SIMULATION":
            return o.engine == "FORMAL" and o.status in ("proved", "failed")
        return False  # HYBRID_SPLIT hedges by design

    def to_dict(self) -> dict:
        d = asdict(self)
        d["miss"] = self.miss
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Record":
        if not str(d.get("schema", "")).startswith("rvsched/"):
            raise ValueError(f"not an rvsched record: {d.get('schema')!r}")
        out = d.get("outcome")
        return cls(
            fingerprint=d["fingerprint"],
            module=d["module"],
            prediction=Verdict(**d["prediction"]),
            outcome=Outcome(**out) if out else None,
            schema=d["schema"],
            created=d.get("created", 0.0),
        )


# ---------------------------------------------------------------- registry --
# A language is an object with three methods:
#   split(text)                    -> [(module_name, module_source), ...]
#   recognize(module_source[, units]) -> Verdict
#   fingerprint(modules: dict)     -> {module_name: fingerprint or None}
#     (None = unstable: depends on something outside the input; never cached)
# A store is a class with .get(fp) -> Record|None, .put(Record), .all()
_LANGUAGES: dict[str, object] = {}
_STORES: dict[str, type] = {}
_loaded = False


def language(name: str):
    """Decorator: register a language ('verilog', ...)."""
    def wrap(obj):
        _LANGUAGES[name] = obj() if isinstance(obj, type) else obj
        return obj
    return wrap


def store(scheme: str):
    """Decorator: register a store for a location scheme ('dir', 'https')."""
    def wrap(cls):
        _STORES[scheme] = cls
        return cls
    return wrap


def _load_plugins() -> None:
    """Built-ins first, then anything installed under the entry-point groups
    'rvsched.languages' and 'rvsched.stores'. Third parties extend here."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    from . import verilog, stores  # noqa: F401  (registers built-ins)
    for group in ("rvsched.languages", "rvsched.stores"):
        try:
            eps = entry_points(group=group)
        except TypeError:                      # Python 3.9
            eps = entry_points().get(group, [])
        for ep in eps:
            ep.load()


def get_language(name: str):
    _load_plugins()
    if name not in _LANGUAGES:
        raise KeyError(f"no language {name!r}; have {sorted(_LANGUAGES)}")
    return _LANGUAGES[name]


def open_store(location: str):
    """'path/to/dir' -> dir store; 'https://...' -> read-only URL store."""
    _load_plugins()
    scheme = location.split("://", 1)[0] if "://" in location else "dir"
    if scheme not in _STORES:
        raise KeyError(f"no store for {scheme!r}; have {sorted(_STORES)}")
    return _STORES[scheme](location)


# ------------------------------------------------------------------- verbs --
def recognize(source: str, lang: str = "verilog", units: Optional[dict] = None) -> Verdict:
    """units (optional): every unit visible, so a language can look inside
    instantiated children. Languages that ignore it still conform."""
    lng = get_language(lang)
    return lng.recognize(source, units) if units is not None else lng.recognize(source)


def resolve(fingerprint: str, st) -> Optional[Record]:
    """None means the void: this structure has never been seen."""
    return st.get(fingerprint)


def record(fingerprint: str, module: str, prediction: Verdict,
           outcome: Optional[Outcome], st) -> Record:
    if outcome is not None:
        if outcome.status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}")
        if outcome.engine not in ENGINES:
            raise ValueError(f"engine must be one of {ENGINES}")
    r = Record(fingerprint=fingerprint, module=module,
               prediction=prediction, outcome=outcome)
    st.put(r)
    return r


def decide(prediction: Verdict, known: Optional[Record]) -> dict:
    """Recorded truth beats prediction. This is where the learning lives."""
    if known and known.outcome and known.outcome.status != "unknown":
        o = known.outcome
        if o.engine == "FORMAL" and o.status == "proved":
            return {"action": "SKIP", "engine": "FORMAL",
                    "reason": "this exact structure was already proved",
                    "evidence": o.evidence}
        if o.engine == "FORMAL" and o.status == "failed":
            return {"action": "KNOWN_FAIL", "engine": "FORMAL",
                    "reason": "this exact structure already failed formal; fix the design first",
                    "evidence": o.evidence}
        if o.engine == "FORMAL" and o.status == "timeout":
            return {"action": "RUN", "engine": "SIMULATION",
                    "reason": "formal timed out on this exact structure before",
                    "evidence": o.evidence}
    return {"action": "RUN", "engine": prediction.engine,
            "reason": prediction.reason, "evidence": None}
