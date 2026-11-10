"""Idempotent schema migration for multi-property support (runs automatically on startup).

Upgrades a pre-multi-property database in place:
  clarity_raw_snapshots  + property_id, clarity_project_id; unique key now includes property_id
  clarity_metrics        + property_id, clarity_project_id; lookup index includes property_id
  clarity_api_usage      + clarity_project_id; primary key is now (clarity_project_id, day)
  clarity_sync_runs      + property_id, clarity_project_id

Existing rows get property_id "" / clarity_project_id 0 here, and
app.services.clarity_projects.adopt_unassigned_rows() then assigns them to the default property
(it needs the property list and the seeded projects, which aren't available at DDL time).

SQLite can't drop constraints, so those tables are rebuilt (copy → swap) inside one transaction;
Postgres uses ALTER TABLE. Run manually with:  python -m app.migrate
"""
from __future__ import annotations

import logging

from sqlalchemy import inspect
from sqlalchemy.engine import Connection, Engine

from app.models import ClarityApiUsage, ClarityRawSnapshot

log = logging.getLogger("app.migrate")


def _columns(conn: Connection, table: str) -> set[str]:
    return {c["name"] for c in inspect(conn).get_columns(table)}


def _rebuild_sqlite(conn: Connection, table, copy_columns: list[str], extra: dict[str, str]) -> None:
    """Recreate `table` from the current model, copying `copy_columns` and filling `extra` (col -> SQL expr)."""
    name = table.name
    old = f"{name}__premigration"
    for ix in inspect(conn).get_indexes(name):
        conn.exec_driver_sql(f'DROP INDEX IF EXISTS "{ix["name"]}"')
    # legacy_alter_table stops SQLite from rewriting other tables' foreign keys to point at the renamed table.
    conn.exec_driver_sql("PRAGMA legacy_alter_table = ON")
    conn.exec_driver_sql(f'ALTER TABLE "{name}" RENAME TO "{old}"')
    conn.exec_driver_sql("PRAGMA legacy_alter_table = OFF")
    table.create(conn)
    targets = copy_columns + list(extra)
    sources = [f'"{c}"' for c in copy_columns] + list(extra.values())
    conn.exec_driver_sql(f'INSERT INTO "{name}" ({", ".join(chr(34) + c + chr(34) for c in targets)}) '
                         f'SELECT {", ".join(sources)} FROM "{old}"')
    conn.exec_driver_sql(f'DROP TABLE "{old}"')


def migrate(engine: Engine) -> list[str]:
    """Bring an existing database up to the multi-property schema. Returns the steps applied."""
    steps: list[str] = []
    with engine.begin() as conn:
        tables = set(inspect(conn).get_table_names())
        sqlite = conn.dialect.name == "sqlite"

        # -- clarity_raw_snapshots
        if "clarity_raw_snapshots" in tables and "property_id" not in _columns(conn, "clarity_raw_snapshots"):
            if sqlite:
                _rebuild_sqlite(conn, ClarityRawSnapshot.__table__,
                                ["id", "fetched_at", "snapshot_date", "dimensions", "num_of_days", "payload"],
                                {"property_id": "''", "clarity_project_id": "NULL"})
            else:
                for sql in (
                    "ALTER TABLE clarity_raw_snapshots ADD COLUMN property_id VARCHAR(32) NOT NULL DEFAULT ''",
                    "ALTER TABLE clarity_raw_snapshots ADD COLUMN clarity_project_id INTEGER",
                    "ALTER TABLE clarity_raw_snapshots DROP CONSTRAINT IF EXISTS uq_snapshot",
                    "ALTER TABLE clarity_raw_snapshots ADD CONSTRAINT uq_snapshot_property "
                    "UNIQUE (property_id, snapshot_date, dimensions, num_of_days)",
                    "CREATE INDEX IF NOT EXISTS ix_clarity_raw_snapshots_property_id ON clarity_raw_snapshots (property_id)",
                ):
                    conn.exec_driver_sql(sql)
            steps.append("clarity_raw_snapshots: added property_id/clarity_project_id, per-property unique key")

        # -- clarity_metrics (only new columns + index, so ALTER works on both dialects)
        if "clarity_metrics" in tables:
            cols = _columns(conn, "clarity_metrics")
            if "property_id" not in cols:
                conn.exec_driver_sql("ALTER TABLE clarity_metrics ADD COLUMN property_id VARCHAR(32) NOT NULL DEFAULT ''")
                steps.append("clarity_metrics: added property_id")
            if "clarity_project_id" not in cols:
                conn.exec_driver_sql("ALTER TABLE clarity_metrics ADD COLUMN clarity_project_id INTEGER")
                steps.append("clarity_metrics: added clarity_project_id")
            index_names = {ix["name"] for ix in inspect(conn).get_indexes("clarity_metrics")}
            if "ix_metrics_property_lookup" not in index_names:
                conn.exec_driver_sql("CREATE INDEX ix_metrics_property_lookup ON clarity_metrics "
                                     "(property_id, dimensions, num_of_days, snapshot_date)")
                steps.append("clarity_metrics: added per-property lookup index")
            if "ix_metrics_lookup" in index_names:
                conn.exec_driver_sql("DROP INDEX ix_metrics_lookup")

        # -- clarity_api_usage: per-project counter
        if "clarity_api_usage" in tables and "clarity_project_id" not in _columns(conn, "clarity_api_usage"):
            if sqlite:
                _rebuild_sqlite(conn, ClarityApiUsage.__table__, ["day", "calls", "exhausted", "updated_at"],
                                {"clarity_project_id": "0"})
            else:
                for sql in (
                    "ALTER TABLE clarity_api_usage ADD COLUMN clarity_project_id INTEGER NOT NULL DEFAULT 0",
                    "ALTER TABLE clarity_api_usage DROP CONSTRAINT IF EXISTS clarity_api_usage_pkey",
                    "ALTER TABLE clarity_api_usage ADD PRIMARY KEY (clarity_project_id, day)",
                ):
                    conn.exec_driver_sql(sql)
            steps.append("clarity_api_usage: counter is now per Clarity project")

        # -- clarity_sync_runs
        if "clarity_sync_runs" in tables:
            cols = _columns(conn, "clarity_sync_runs")
            if "property_id" not in cols:
                conn.exec_driver_sql("ALTER TABLE clarity_sync_runs ADD COLUMN property_id VARCHAR(32)")
                conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_clarity_sync_runs_property_id "
                                     "ON clarity_sync_runs (property_id)")
                steps.append("clarity_sync_runs: added property_id")
            if "clarity_project_id" not in cols:
                conn.exec_driver_sql("ALTER TABLE clarity_sync_runs ADD COLUMN clarity_project_id INTEGER")
                steps.append("clarity_sync_runs: added clarity_project_id")

    for s in steps:
        log.warning("Migration: %s", s)
    return steps


def main() -> None:
    from app.config import get_settings
    from app.db import init_db
    from app.main import configure_logging

    configure_logging(get_settings().log_level)
    init_db()  # migrates, then creates any missing tables
    print("Database is up to date.")


if __name__ == "__main__":
    main()
