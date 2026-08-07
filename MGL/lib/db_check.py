"""SQL Database Validation check for MGL: SERVER_STATES mismatch detection.

Connects using config.DB_* (sourced from environment variables only - never hardcoded)
and runs a single static query (no user input, so no SQL-injection surface). Supports
postgres (psycopg2) and mysql (PyMySQL) since those are the only DB drivers already in
requirements.txt; if MGL's actual database is a different engine (e.g. Oracle/Sybase),
add the appropriate driver package and a branch in _connect().
"""

import logging

import config

logger = logging.getLogger(__name__)

_QUERY = "SELECT * FROM SERVER_STATES WHERE CURRENT_STATE <> NEW_STATE"


def _is_configured() -> bool:
    return all([config.DB_HOST, config.DB_PORT, config.DB_NAME, config.DB_USER, config.DB_PASSWORD])


def _connect():
    if config.DB_ENGINE == "mysql":
        import pymysql
        return pymysql.connect(
            host=config.DB_HOST, port=int(config.DB_PORT), db=config.DB_NAME,
            user=config.DB_USER, password=config.DB_PASSWORD, connect_timeout=10,
        )
    import psycopg2
    return psycopg2.connect(
        host=config.DB_HOST, port=int(config.DB_PORT), dbname=config.DB_NAME,
        user=config.DB_USER, password=config.DB_PASSWORD, connect_timeout=10,
    )


def run_database_validation() -> dict:
    """Run the SERVER_STATES mismatch check. Returns Warning if unconfigured, never raises."""
    if not _is_configured():
        return {
            "status": "Warning",
            "detail": (
                "Database connection not configured - set MGL_DB_HOST/MGL_DB_PORT/MGL_DB_NAME/"
                "MGL_DB_USER/MGL_DB_PASSWORD (and optionally MGL_DB_ENGINE=postgres|mysql) as "
                "Jenkins secret-bound environment variables"
            ),
        }

    try:
        connection = _connect()
    except Exception:
        logger.exception("Failed to connect to the MGL database at %s:%s/%s", config.DB_HOST, config.DB_PORT, config.DB_NAME)
        return {"status": "Failed", "detail": f"Could not connect to database {config.DB_HOST}/{config.DB_NAME} (see logs for details)"}

    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(_QUERY)
                rows = cursor.fetchall()
    except Exception:
        logger.exception("SERVER_STATES query failed against %s/%s", config.DB_HOST, config.DB_NAME)
        return {"status": "Failed", "detail": f"SERVER_STATES query failed against {config.DB_HOST}/{config.DB_NAME} (see logs for details)"}
    finally:
        connection.close()

    if not rows:
        return {"status": "Healthy", "detail": "No SERVER_STATES mismatches (CURRENT_STATE = NEW_STATE for all rows)"}
    return {"status": "Warning", "detail": f"{len(rows)} SERVER_STATES row(s) with CURRENT_STATE <> NEW_STATE"}
