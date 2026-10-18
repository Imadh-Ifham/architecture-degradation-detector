"""Baseline models.

The baseline's output, ``StaticFlag``, is stored with the analysis run, so it crosses the
``AnalysisRunRepository`` port and lives in ``app/domain/analysis_run.py``. Its rules are
configuration (``C3Config.baseline``). Nothing is local to this folder yet.
"""
