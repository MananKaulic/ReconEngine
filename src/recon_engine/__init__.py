"""recon_engine: a rule-based position reconciliation engine (prototype).

Everything in this package is pure (no Streamlit, no network I/O beyond
reading files the caller points at). See report.run_reconciliation for the
single entry point that runs the full pipeline.
"""
from .config import Config
from .report import build_excel_report, breaks_to_dataframe, run_reconciliation, validation_issues_to_dataframe

__all__ = [
    "Config",
    "run_reconciliation",
    "breaks_to_dataframe",
    "validation_issues_to_dataframe",
    "build_excel_report",
]
