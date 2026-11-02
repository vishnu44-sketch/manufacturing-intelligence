"""SQL guard checks: only one read-only SELECT on ai_gold tables may ever run.

Pure unit tests - no MySQL, no network: every test passes its own list of allowed tables.
Run with:  python -m pytest -q portal/tests/test_guard.py
"""
import pytest

from portal.rag.sql_guard import MAX_ROWS, GuardError, check_sql

# the ai_gold tables the tests pretend exist
TABLES = {"dim_customers", "dim_calendar", "dim_sales_people", "fact_invoice_lines"}


def check(sql):
    """check_sql() with the test tables (no MySQL needed)."""
    return check_sql(sql, TABLES)


def one_line(sql):
    """The cleaned SQL on one line with single spaces - easier to compare."""
    return " ".join(sql.split())


# ---------- writes, DDL and other statements are refused ----------

WRITE_AND_OTHER_STATEMENTS = {
    "INSERT": "INSERT INTO dim_customers (customer_id) VALUES (99)",
    "UPDATE": "UPDATE dim_customers SET customer_name = 'x'",
    "DELETE": "DELETE FROM dim_customers",
    "REPLACE": "REPLACE INTO dim_customers (customer_id) VALUES (99)",
    "CREATE": "CREATE TABLE stolen (id INT)",
    "DROP": "DROP TABLE dim_customers",
    "ALTER": "ALTER TABLE dim_customers ADD COLUMN x INT",
    "TRUNCATE": "TRUNCATE TABLE dim_customers",
    "GRANT": "GRANT ALL ON *.* TO 'x'@'%'",
    "SET": "SET SESSION TRANSACTION READ WRITE",
    "CALL": "CALL some_procedure()",
    "LOAD DATA": "LOAD DATA INFILE 'C:/temp/x.csv' INTO TABLE dim_customers",
    "HANDLER": "HANDLER dim_customers OPEN",
    "DO": "DO SLEEP(5)",
}


@pytest.mark.parametrize("sql", WRITE_AND_OTHER_STATEMENTS.values(),
                         ids=WRITE_AND_OTHER_STATEMENTS.keys())
def test_anything_but_select_is_refused(sql):
    """Writes, table changes, grants, SET, CALL, LOAD DATA, HANDLER and DO never pass."""
    with pytest.raises(GuardError):
        check(sql)


def test_a_write_says_why_it_was_refused():
    """The refusal reason is plain English (it goes back to the AI and to the admin)."""
    with pytest.raises(GuardError, match="Only SELECT queries are allowed - DELETE is not"):
        check("DELETE FROM dim_customers")


@pytest.mark.parametrize("sql", [
    "SELECT 1 FROM dim_customers; DROP TABLE dim_customers",
    "SELECT customer_name FROM dim_customers; SELECT customer_id FROM dim_customers",
])
def test_more_than_one_statement_is_refused(sql):
    """A second statement after a ';' is never allowed - even a harmless one."""
    with pytest.raises(GuardError, match="Only one SQL statement"):
        check(sql)


# ---------- SELECT tricks are refused ----------

@pytest.mark.parametrize("sql", [
    "SELECT * FROM dim_customers INTO OUTFILE 'C:/temp/x.csv'",
    "SELECT * FROM dim_customers INTO DUMPFILE 'C:/temp/x.bin'",
    "select * from dim_customers\ninto\n  outfile 'C:/temp/x.csv'",
])
def test_writing_to_a_file_is_refused(sql):
    """SELECT ... INTO OUTFILE / DUMPFILE would write a file on the MySQL server."""
    with pytest.raises(GuardError, match="INTO OUTFILE / DUMPFILE"):
        check(sql)


@pytest.mark.parametrize("sql", [
    "SELECT customer_name INTO @x FROM dim_customers",
    "SELECT @x FROM dim_customers",
    "SELECT @@version",
])
def test_mysql_variables_are_refused(sql):
    """No @variables or @@server settings - not to read, not to fill."""
    with pytest.raises(GuardError):
        check(sql)


@pytest.mark.parametrize("sql", [
    "SELECT * FROM dim_customers FOR UPDATE",
    "SELECT * FROM dim_customers LOCK IN SHARE MODE",
    "SELECT * FROM dim_customers FOR SHARE",
])
def test_locking_reads_are_refused(sql):
    """FOR UPDATE / LOCK IN SHARE MODE would lock rows for other users."""
    with pytest.raises(GuardError, match="Locking reads"):
        check(sql)


@pytest.mark.parametrize("function", ["SLEEP(5)", "BENCHMARK(1000000, MD5('x'))",
                                      "LOAD_FILE('C:/secret.txt')", "GET_LOCK('x', 10)"])
def test_dangerous_functions_are_refused(function):
    """Functions that wait, read server files or take locks are blocked."""
    with pytest.raises(GuardError, match="is not allowed"):
        check(f"SELECT {function} FROM dim_customers")


def test_a_dangerous_function_hidden_in_a_subquery_is_refused():
    """The guard looks at every part of the query, not only the first SELECT."""
    with pytest.raises(GuardError, match="SLEEP"):
        check("SELECT * FROM dim_customers WHERE customer_id = (SELECT SLEEP(3))")


# ---------- only ai_gold tables ----------

@pytest.mark.parametrize("table", ["nop_gold.fact_invoice", "information_schema.tables",
                                   "mysql.user", "performance_schema.threads", "sys.version",
                                   "`mysql`.`user`"])
def test_other_databases_are_refused(table):
    """Only ai_gold may be read - not the real NOP gold, not MySQL's own databases."""
    with pytest.raises(GuardError, match="Only the ai_gold database may be read"):
        check(f"SELECT * FROM {table}")


def test_another_database_hidden_in_a_subquery_is_refused():
    with pytest.raises(GuardError, match="not 'mysql'"):
        check("SELECT * FROM dim_customers WHERE customer_id IN (SELECT 1 FROM mysql.user)")


def test_ai_gold_written_in_front_of_the_table_is_fine():
    assert "ai_gold.dim_customers" in check("SELECT customer_name FROM ai_gold.dim_customers")


def test_unknown_table_is_refused():
    """A table that is not in ai_gold (here: 'customers') is refused by name."""
    with pytest.raises(GuardError, match="Unknown table 'customers'"):
        check("SELECT * FROM customers")


# ---------- comments ----------

@pytest.mark.parametrize("sql", [
    "SELECT /*! SLEEP(5) */ 1 FROM dim_customers",                      # MySQL RUNS /*! ... */
    "SELECT customer_name FROM dim_customers /*!50000 UNION SELECT user FROM mysql.user */",
    "SELECT /*+ MAX_EXECUTION_TIME(999999) */ * FROM dim_customers",    # a hint could lift the time limit
])
def test_special_comments_are_refused(sql):
    with pytest.raises(GuardError, match="Special MySQL comments"):
        check(sql)


def test_plain_comments_are_removed():
    """Normal -- and /* */ comments are dropped: the SQL that runs is written again without them."""
    cleaned = check("SELECT customer_name FROM dim_customers -- note\nWHERE customer_id > 0 /* why */")
    assert "--" not in cleaned and "/*" not in cleaned
    assert one_line(cleaned) == "SELECT customer_name FROM dim_customers WHERE customer_id > 0 LIMIT 500"


# ---------- what IS allowed ----------

def test_sql_code_fences_are_stripped():
    """The AI often wraps its SQL in ```sql ... ``` - the guard takes the SQL out of the block."""
    cleaned = check("```sql\nSELECT customer_name FROM dim_customers;\n```")
    assert "`" not in cleaned
    assert one_line(cleaned) == "SELECT customer_name FROM dim_customers LIMIT 500"


def test_cte_names_are_allowed():
    """A WITH name is not an ai_gold table, but the query defines it itself - so it is fine."""
    cleaned = check("WITH top_c AS (SELECT customer_id FROM dim_customers) SELECT * FROM top_c")
    assert "FROM top_c" in one_line(cleaned)


def test_union_is_allowed():
    cleaned = check("SELECT customer_name FROM dim_customers "
                    "UNION SELECT sales_person_name FROM dim_sales_people")
    assert "UNION" in cleaned
    assert one_line(cleaned).endswith("LIMIT 500")


# ---------- the 500-row cap ----------

def test_limit_500_is_added_when_missing():
    assert one_line(check("SELECT customer_name FROM dim_customers")).endswith(f"LIMIT {MAX_ROWS}")


@pytest.mark.parametrize("sql, ending", [
    ("SELECT customer_name FROM dim_customers LIMIT 100000", "LIMIT 500"),
    ("SELECT customer_name FROM dim_customers LIMIT 10, 1000", "LIMIT 500 OFFSET 10"),
])
def test_limit_above_500_is_lowered(sql, ending):
    assert one_line(check(sql)).endswith(ending)


def test_limit_below_500_is_kept():
    assert one_line(check("SELECT customer_name FROM dim_customers LIMIT 5")).endswith("LIMIT 5")


def test_limit_must_be_a_plain_number():
    with pytest.raises(GuardError, match="LIMIT must be a plain whole number"):
        check("SELECT customer_name FROM dim_customers LIMIT -1")


def test_empty_sql_is_refused():
    with pytest.raises(GuardError, match="No SQL"):
        check("   ")
