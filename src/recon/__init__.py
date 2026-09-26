"""Multi-entity revenue reconciliation engine (synthetic-data demo)."""

from .generate import generate
from .reconcile import reconcile, ReconResult
from .report import write_outputs

__all__ = ["generate", "reconcile", "ReconResult", "write_outputs"]
__version__ = "0.1.0"
