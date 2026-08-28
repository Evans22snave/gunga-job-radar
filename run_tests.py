"""
Manual test runner - Run integration tests and diagnostics

This script executes all tests and diagnostics in sequence.
"""

import logging
import os
import sys

from dotenv import load_dotenv

from database.db import Database
from diagnostics import run_full_diagnostics
from tests import run_all_tests

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(message)s"
    ),
)

logger = logging.getLogger("Test Runner")


def main() -> int:
    """Run all tests and diagnostics."""

    logger.info("")
    logger.info("=" * 70)
    logger.info("GUNGA JOB RADAR — FULL TEST & DIAGNOSTIC RUN")
    logger.info("=" * 70)
    logger.info("")

    # Load environment
    load_dotenv()

    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        logger.error("❌ DATABASE_URL not set")
        return 1

    logger.info("✅ Environment loaded")
    logger.info("")

    try:

        # Initialize database
        logger.info("Initializing database...")
        from database.schema import initialize_database

        initialize_database(database_url)
        logger.info("✅ Database schema ready")
        logger.info("")

        # Create database connection
        database = Database(database_url)

        # Run integration tests
        logger.info("Starting integration tests...")
        logger.info("")
        run_all_tests(database)
        logger.info("")

        # Run diagnostics
        logger.info("Starting full diagnostics...")
        logger.info("")
        run_full_diagnostics(database)
        logger.info("")

        logger.info("=" * 70)
        logger.info("✅ ALL TESTS AND DIAGNOSTICS COMPLETED SUCCESSFULLY")
        logger.info("=" * 70)
        logger.info("")

        return 0

    except Exception as exc:
        logger.exception("❌ Test run failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
