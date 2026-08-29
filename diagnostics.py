# Gunga Job Radar — Diagnostics
# Run with: python diagnostics.py
#
# This module is intentionally dependency-light. It helps diagnose
# configuration, database, Telegram, and scan-mode problems without
# running the full radar.

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("JOB_RADAR_DB_PATH", ROOT / "jobs.db"))


def mask_secret(value: str | None, visible: int = 4) -> str:
    """Mask secrets while keeping a small visible prefix."""
    if not value:
        return "(not set)"
    if len(value) <= visible:
        return "*" * len(value)
    return value[:visible] + "*" * max(4, len(value) - visible)


def env_status() -> dict[str, str]:
    """Return the status of important environment variables."""
    names = [
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "JOB_RADAR_DB_PATH",
        "DATABASE_URL",
        "SCAN_MODE",
    ]

    result: dict[str, str] = {}

    for name in names:
        value = os.getenv(name)

        if name in {"TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"}:
            result[name] = mask_secret(value)
        else:
            result[name] = value if value else "(not set)"

    return result


def check_database() -> dict[str, Any]:
    """Check whether the SQLite database exists and can be opened."""
    result: dict[str, Any] = {
        "path": str(DB_PATH),
        "exists": DB_PATH.exists(),
        "size": DB_PATH.stat().st_size if DB_PATH.exists() else 0,
        "ok": False,
        "tables": [],
        "error": None,
    }

    if not DB_PATH.exists():
        result["error"] = "Database file does not exist."
        return result

    try:
        conn = sqlite3.connect(str(DB_PATH))
        try:
            rows = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' ORDER BY name"
            ).fetchall()

            result["tables"] = [row[0] for row in rows]
            result["ok"] = True
        finally:
            conn.close()

    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"

    return result


def check_database_counts() -> dict[str, Any]:
    """Return useful row counts from common Job Radar tables."""
    result: dict[str, Any] = {
        "ok": False,
        "counts": {},
        "error": None,
    }

    if not DB_PATH.exists():
        result["error"] = "Database file does not exist."
        return result

    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row

        try:
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }

            for table in (
                "jobs",
                "job_posts",
                "sources",
                "scan_runs",
                "notifications",
            ):
                if table in tables:
                    try:
                        count = conn.execute(
                            f"SELECT COUNT(*) FROM {table}"
                        ).fetchone()[0]
                        result["counts"][table] = count
                    except Exception as exc:
                        result["counts"][table] = (
                            f"error: {type(exc).__name__}: {exc}"
                        )

            result["ok"] = True

        finally:
            conn.close()

    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"

    return result


def check_python() -> dict[str, Any]:
    """Return Python runtime information."""
    return {
        "version": sys.version,
        "executable": sys.executable,
        "platform": sys.platform,
    }


def print_section(title: str) -> None:
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


def main() -> int:
    print("GUNGA JOB RADAR — DIAGNOSTICS")

    print_section("PYTHON")
    python_info = check_python()

    print(f"Version:    {python_info['version']}")
    print(f"Executable: {python_info['executable']}")
    print(f"Platform:   {python_info['platform']}")

    print_section("ENVIRONMENT")

    for name, status in env_status().items():
        print(f"{name}: {status}")

    print_section("DATABASE")

    db = check_database()

    print(f"Path:   {db['path']}")
    print(f"Exists: {db['exists']}")
    print(f"Size:   {db['size']} bytes")
    print(f"OK:     {db['ok']}")

    if db["tables"]:
        print("Tables:")
        for table in db["tables"]:
            print(f"  - {table}")

    if db["error"]:
        print(f"Error:  {db['error']}")

    print_section("DATABASE COUNTS")

    counts = check_database_counts()

    if counts["counts"]:
        for table, count in counts["counts"].items():
            print(f"{table}: {count}")
    else:
        print("No recognised tables found.")

    if counts["error"]:
        print(f"Error: {counts['error']}")

    print_section("RESULT")

    if db["ok"]:
        print("Database check: PASS")
    else:
        print("Database check: FAIL")

    return 0 if db["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())