"""Pipeline package — MLOps modules for the Smart Water Analytics portfolio.

Modules:
    logger       Structured JSON logging with run_id tracing
    schema       Pandera schemas for every pipeline artifact
    validators   Dataframe and JSON validation helpers
    data_quality Outlier detection and missing-value handling
    sql_loader   Load JSON outputs into a queryable SQLite database
    drift        KS-test / chi-square data drift detection
    orchestrator Stage-based pipeline runner with checkpoints
"""

__all__ = [
    "logger",
    "schema",
    "validators",
    "data_quality",
    "sql_loader",
    "drift",
    "orchestrator",
]
