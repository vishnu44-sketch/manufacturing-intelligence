"""Ask NOP's own tables in MySQL (APP_DB_NAME): Django's MySQL driver must not break warehouse.py."""
import sys

import pymysql
import pytest
from django.db import connection

from portal.rag import warehouse

GROUP_BY_ERROR = ("WITH fy AS (SELECT MIN(full_date) AS fy_start FROM dim_calendar WHERE financial_year = '2627') "
                  "SELECT fy.fy_start, COUNT(*) FROM fy JOIN fact_invoice_lines il ON il.invoice_date >= fy.fy_start")


@pytest.mark.django_db
def test_pymysql_errors_are_loaded_once():
    """28-Oct: PyMySQL as Django's driver loaded a second copy of pymysql.err."""
    connection.ensure_connection()          # loads Django's database driver
    assert pymysql.err is sys.modules["pymysql.err"]
    assert pymysql.err.MySQLError is pymysql.MySQLError
    if "MySQLdb" in sys.modules:
        assert sys.modules["MySQLdb.err"] is pymysql.err


@pytest.mark.django_db
def test_a_mysql_error_of_the_ai_sql_is_a_query_error():
    """... so the AI gets MySQL's message and fixes its SQL (3 tries), instead of 'Something went wrong'."""
    connection.ensure_connection()          # Django's MySQL driver is loaded, as in the running app
    try:
        warehouse.allowed_tables()
    except Exception as exc:
        pytest.skip(f"read-only MySQL not available: {exc}")
    with pytest.raises(warehouse.QueryError, match="1140"):
        warehouse.run_select(GROUP_BY_ERROR)
