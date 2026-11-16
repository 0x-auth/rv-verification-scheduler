"""rvsched: decide formal vs simulation before you spend the compute,
and never pay twice for the same structure."""
__version__ = "0.1.0"

from .core import (SCHEMA, Outcome, Record, Verdict, decide, get_language,  # noqa: F401
                   language, open_store, recognize, record, resolve, store)
