"""Four general checks of 20-Nov (the local model skipped prompt rules more often than Groq) - none of them knows a
question, a customer, a month or a number:

A. a list cut at the 500-row limit told as the total ("there were 500 active customers ... all 500"; 707 were active):
   the answer is rewritten once (answer_verify check 5). The cut is now also seen in the Ask flow: the SQL guard's
   LIMIT 500 meant MySQL never sent a 501st row, so result.truncated stayed False (lc/graph.run_sql).
B. a CHAR(1) 'Y' / 'N' column compared with 1 / 0 / TRUE / FALSE ("cu.is_active = 1" -> 0 active customers): the SQL
   goes back to the AI (agent.yes_no_numbers; the columns come from docs/data_dictionary.md).
C. a financial year's date limits taken from MIN(sales_period_start) / MAX(sales_period_end) - two FYs overlapped by
   a month (439 customers instead of 489): the SQL goes back to the AI (agent.fy_from_sales_periods).
D. a month of the rows that ends after the invoice data's last date (sales month Nov 2026 with data up to
   31-Oct-2026) told as a full month: the answer is rewritten once (answer_verify check 6).
Correct SQL and correct answers are never flagged. The AI and MySQL are fakes (no Groq call).
Run with:  python -m pytest -q portal/tests/test_general_checks.py
"""
import datetime
from decimal import Decimal

import pytest

from portal import answer_verify
from portal.rag import agent, warehouse
from portal.tests.test_agent import mysql, use_fake_ai  # noqa: F401

pytestmark = pytest.mark.django_db  # agent.ask() saves a Question

DATA_END = datetime.date(2026, 10, 31)


def result_of(sql, columns, rows, truncated=False, text="question"):
    return agent.AskResult(text=text, status="ok", sql=sql, columns=columns, rows=rows, truncated=truncated)


# ---------- A. the 500-row limit told as the total ----------

LIST_SQL = ("SELECT cu.customer_code, cu.customer_name FROM fact_invoice_lines il JOIN dim_customers cu "
            "ON cu.customer_id = il.customer_id GROUP BY cu.customer_code, cu.customer_name ORDER BY cu.customer_name")
LIST_COLUMNS = ["customer_code", "customer_name"]
LIST_ROWS = [[f"C{n:05d}", f"Customer {n}"] for n in range(500)]
# the 20-Nov answer, word for word (but the names)
CAP_ANSWER = ("In sales month Oct 2026 (21-Sep-2026 to 20-Oct-2026), there were 500 active customers. The list is "
              "ordered alphabetically by customer name. The full table contains all 500 customer records.")
MORE_ANSWER = ("More than 500 customers were invoiced in sales month Oct 2026 - the table shows the first 500 "
               "(the list is cut at the 500-row limit); ask \"How many active customers ...?\" for the exact number.")


@pytest.mark.parametrize("answer", [CAP_ANSWER, "The full table contains all 500 customer records.",
                                    "We have 500 customers in this list.", "A total of 500 customers bought."])
def test_a_cut_list_told_as_500_is_flagged(answer):
    correction, _facts = answer_verify.problems(result_of(LIST_SQL, LIST_COLUMNS, LIST_ROWS, truncated=True), answer)

    assert "the query stopped at the 500-row limit: the data has MORE than 500 rows, so 500 is not the total" in correction
    assert "Say the list has more than 500 rows" in correction and "How many ... ?" in correction


@pytest.mark.parametrize("answer", [
    MORE_ANSWER,
    "The table shows the first 500 customers, ordered by name.",
    "There are 500+ customers in the list.",
    "The list has at least 500 customers.",
    "The top 500 customers are listed, starting with Customer 0.",
    "Customer 0 bought for INR 500 only.",
    "The query stopped at 500 rows, so the list goes on.",
])
def test_a_cut_list_told_as_more_than_500_is_not_flagged(answer):
    assert answer_verify.problems(result_of(LIST_SQL, LIST_COLUMNS, LIST_ROWS, truncated=True), answer) == ("", "")


def test_500_rows_that_were_not_cut_are_never_flagged():
    assert answer_verify.problems(result_of(LIST_SQL, LIST_COLUMNS, LIST_ROWS), CAP_ANSWER) == ("", "")


@pytest.mark.parametrize("sql, cut", [
    (LIST_SQL, True),                                   # no LIMIT: the guard put LIMIT 500 on it
    (LIST_SQL + " LIMIT 1000", True),                   # a bigger LIMIT: lowered to 500
    (LIST_SQL + " LIMIT 500;", True),                   # the cap itself
    (LIST_SQL + " LIMIT 50", False),                    # the AI's own smaller list
    ("SELECT x FROM t WHERE y IN (SELECT y FROM u LIMIT 5)", True),  # a LIMIT inside, none at the end
])
def test_cut_at_row_limit(sql, cut):
    assert agent.cut_at_row_limit(sql) is cut


def test_the_ask_flow_sees_the_cut_list_and_rewrites_the_500_answer(monkeypatch, mysql, user):  # noqa: F811
    mysql.results = [{"columns": LIST_COLUMNS, "rows": LIST_ROWS, "truncated": False}]  # what MySQL really says
    fake = use_fake_ai(monkeypatch, [f"```sql\n{LIST_SQL}\n```", CAP_ANSWER, MORE_ANSWER])

    result = agent.ask("Active customers in Oct 2026", user)

    assert result.truncated and result.answer == MORE_ANSWER and len(fake.calls) == 3
    assert "the query stopped at 500 rows, there are more" in fake.calls[1][-1]["content"]   # the answer's note
    assert "500 is not the total" in fake.calls[2][-1]["content"]                             # the correction


def test_the_ask_flow_with_the_ais_own_small_limit_is_not_cut(monkeypatch, mysql, user):  # noqa: F811
    rows = LIST_ROWS[:20]
    mysql.results = [{"columns": LIST_COLUMNS, "rows": rows, "truncated": False}]
    use_fake_ai(monkeypatch, [f"```sql\n{LIST_SQL} LIMIT 20\n```", "The 20 customers are listed."])

    result = agent.ask("20 customers by name", user)

    assert result.status == "ok" and not result.truncated


# ---------- B. 'Y' / 'N' columns compared with 1 / TRUE ----------

def test_the_yes_no_columns_come_from_the_data_dictionary():
    columns = agent.yes_no_columns()
    assert "is_active" in columns["dim_customers"] and "is_active" in columns["dim_products"]
    assert "is_weekend" in columns["dim_calendar"]
    assert "customer_name" not in columns["dim_customers"]


@pytest.mark.parametrize("sql, wrong", [
    ("SELECT COUNT(*) FROM dim_customers cu WHERE cu.is_active = 1", "cu.is_active = 1"),
    ("SELECT COUNT(*) FROM dim_customers cu WHERE cu.is_active <> 0", "cu.is_active <> 0"),
    ("SELECT COUNT(*) FROM dim_customers cu WHERE cu.is_active = TRUE", "cu.is_active = TRUE"),
    ("SELECT COUNT(*) FROM dim_customers cu WHERE cu.is_active = '1'", "cu.is_active = '1'"),
    ("SELECT COUNT(*) FROM dim_products WHERE is_active IN (1)", "is_active IN (1)"),
    ("SELECT COUNT(*) FROM dim_customers cu WHERE cu.is_active IS TRUE", "cu.is_active IS TRUE"),
    ("SELECT COUNT(*) FROM dim_customers cu WHERE cu.is_active AND cu.country = 'India'",
     "cu.is_active on its own as a condition"),
    ("SELECT COUNT(DISTINCT il.customer_id) FROM fact_invoice_lines il JOIN dim_customers cu "
     "ON cu.customer_id = il.customer_id AND cu.is_active = 1", "cu.is_active = 1"),
    ("SELECT COUNT(*) FROM dim_calendar c WHERE c.is_weekend = 0", "c.is_weekend = 0"),
])
def test_a_yes_no_column_compared_with_a_number_is_found(sql, wrong):
    assert agent.yes_no_numbers(sql)[1] == wrong


@pytest.mark.parametrize("sql", [
    "SELECT COUNT(*) FROM dim_customers cu WHERE cu.is_active = 'Y'",
    "SELECT COUNT(*) FROM dim_customers cu WHERE cu.is_active IN ('Y', 'N')",
    "SELECT COUNT(*) FROM dim_customers cu WHERE cu.is_active <> 'N' AND cu.customer_id <> -1",
    "SELECT COUNT(*) FROM fact_invoice_lines il WHERE il.customer_id = 1",
    "SELECT SUM(CASE WHEN cu.is_active = 'Y' THEN 1 ELSE 0 END) AS active FROM dim_customers cu",
    "SELECT is_active, COUNT(*) FROM dim_customers GROUP BY is_active",
    "not sql at all (",
])
def test_correct_yes_no_filters_are_not_flagged(sql):
    assert agent.yes_no_numbers(sql) is None


YES_NO_BAD = ("```sql\nSELECT COUNT(DISTINCT il.customer_id) AS active_customers FROM fact_invoice_lines il\n"
              "JOIN dim_calendar c ON c.date_id = il.invoice_date_id\n"
              "JOIN dim_customers cu ON cu.customer_id = il.customer_id\n"
              "WHERE c.sales_month = 'Oct 2026' AND cu.is_active = 1\n```")
YES_NO_GOOD = YES_NO_BAD.replace("cu.is_active = 1", "cu.is_active = 'Y'")


def test_a_yes_no_number_goes_back_to_the_ai_and_the_fixed_sql_runs(monkeypatch, mysql, user):  # noqa: F811
    mysql.results = [{"columns": ["active_customers"], "rows": [[707]], "truncated": False}]
    fake = use_fake_ai(monkeypatch, [YES_NO_BAD, YES_NO_GOOD, "707 active customers were invoiced."])

    result = agent.ask("How many active customers did we invoice in October 2026?", user)

    assert result.status == "ok" and result.tries == 2 and len(mysql.calls) == 1
    assert "cu.is_active = 'Y'" in mysql.calls[0]
    retry_message = fake.calls[1][-1]["content"]
    assert "cu.is_active is CHAR(1) with the text values 'Y' / 'N'" in retry_message
    assert "cu.is_active = 1 does not pick the rows you mean" in retry_message


# ---------- C. financial-year limits from the sales periods ----------

FY_LIMITS_SQL = ("SELECT COUNT(DISTINCT il.customer_id) AS customers FROM fact_invoice_lines il\n"
                 "WHERE il.invoice_date BETWEEN (SELECT MIN(sales_period_start) FROM dim_calendar "
                 "WHERE financial_year = '2425')\n"
                 "AND (SELECT MAX(sales_period_end) FROM dim_calendar WHERE financial_year = '2425')\n"
                 "AND il.customer_id NOT IN (SELECT il2.customer_id FROM fact_invoice_lines il2 WHERE il2.invoice_date "
                 "BETWEEN (SELECT MIN(sales_period_start) FROM dim_calendar WHERE financial_year = '2526') AND "
                 "(SELECT MAX(sales_period_end) FROM dim_calendar WHERE financial_year = '2526'))")
FY_DIRECT_SQL = ("SELECT COUNT(DISTINCT il.customer_id) AS customers FROM fact_invoice_lines il\n"
                 "JOIN dim_calendar c ON c.date_id = il.invoice_date_id WHERE c.financial_year = '2425'\n"
                 "AND il.customer_id NOT IN (SELECT il2.customer_id FROM fact_invoice_lines il2 JOIN dim_calendar c2 "
                 "ON c2.date_id = il2.invoice_date_id WHERE c2.financial_year = '2526')")


@pytest.mark.parametrize("sql", [
    FY_LIMITS_SQL,
    "WITH fy AS (SELECT MIN(sales_period_start) AS s, MAX(sales_period_end) AS e FROM dim_calendar "
    "WHERE financial_year = '2425') SELECT COUNT(*) FROM fact_invoice_lines il CROSS JOIN fy "
    "WHERE il.invoice_date BETWEEN fy.s AND fy.e",
    "SELECT SUM(il.net_taxable_value) FROM fact_invoice_lines il WHERE il.invoice_date >= (SELECT sales_period_start "
    "FROM dim_calendar WHERE financial_year = '2425' ORDER BY full_date LIMIT 1)",
])
def test_fy_limits_from_the_sales_periods_are_found(sql):
    assert agent.fy_from_sales_periods(sql) is True


@pytest.mark.parametrize("sql", [
    FY_DIRECT_SQL,
    # a FY total that shows its dates (fy_period_dates turns them into full_date)
    "SELECT MIN(c.sales_period_start) AS period_from, MAX(c.sales_period_end) AS period_to, "
    "SUM(il.net_taxable_value) FROM fact_invoice_lines il JOIN dim_calendar c ON c.date_id = il.invoice_date_id "
    "WHERE c.financial_year = '2627'",
    # a FY split into sales months
    "SELECT c.sales_month, MIN(c.sales_period_start) AS s, SUM(il.net_taxable_value) FROM fact_invoice_lines il "
    "JOIN dim_calendar c ON c.date_id = il.invoice_date_id WHERE c.financial_year = '2627' GROUP BY c.sales_month",
    # a sales year: its limits ARE the sales periods
    "SELECT SUM(il.net_taxable_value) FROM fact_invoice_lines il WHERE il.invoice_date BETWEEN (SELECT "
    "MIN(sales_period_start) FROM dim_calendar WHERE sales_year = '2526') AND (SELECT MAX(sales_period_end) "
    "FROM dim_calendar WHERE sales_year = '2526')",
    # one sales month picked in the WHERE
    "SELECT SUM(il.net_taxable_value) FROM fact_invoice_lines il WHERE il.invoice_date >= (SELECT "
    "MIN(sales_period_start) FROM dim_calendar WHERE financial_year = '2627' AND sales_month = 'Apr 2026')",
    # the last complete sales month as a limit, next to a FY filter
    "SELECT COUNT(*) FROM fact_invoice_lines il JOIN dim_calendar c ON c.date_id = il.invoice_date_id "
    "WHERE c.financial_year = '2627' AND il.invoice_date <= (SELECT MAX(sales_period_end) FROM dim_calendar "
    "WHERE sales_period_end <= CURRENT_DATE)",
    "not sql at all (",
])
def test_correct_fy_and_sales_period_sql_is_not_flagged(sql):
    assert agent.fy_from_sales_periods(sql) is False


def test_fy_limits_from_the_sales_periods_go_back_to_the_ai(monkeypatch, mysql, user):  # noqa: F811
    mysql.results = [{"columns": ["customers"], "rows": [[489]], "truncated": False}]
    fake = use_fake_ai(monkeypatch, [f"```sql\n{FY_LIMITS_SQL}\n```", f"```sql\n{FY_DIRECT_SQL}\n```",
                                     "489 customers bought in FY 2024-25 but not in FY 2025-26."])

    result = agent.ask("How many customers bought in FY 2024-25 but not in FY 2025-26?", user)

    assert result.status == "ok" and result.tries == 2 and len(mysql.calls) == 1
    assert "c.financial_year = '2425'" in mysql.calls[0]
    retry_message = fake.calls[1][-1]["content"]
    assert "two financial years overlap by a month" in retry_message
    assert "c.financial_year = '<the FY>'" in retry_message


# ---------- D. a month after the data end ----------

MONTHS_SQL = ("SELECT c.sales_month, MIN(c.sales_period_start) AS sales_period_start, MAX(c.sales_period_end) AS "
              "sales_period_end, ROUND(SUM(il.net_taxable_value), 2) AS net_sales_inr FROM fact_invoice_lines il "
              "JOIN dim_calendar c ON c.date_id = il.invoice_date_id GROUP BY c.sales_year, c.sales_period_no, "
              "c.sales_month ORDER BY MIN(c.sales_period_start)")
MONTHS_COLUMNS = ["sales_month", "sales_period_start", "sales_period_end", "net_sales_inr"]


def month_row(year, month, amount):
    end = datetime.date(year, month, 20)
    start = datetime.date(year - (month == 1), (month - 2) % 12 + 1, 21)
    return [end.strftime("%b %Y"), start, end, Decimal(amount)]


# 23-Nov: Jun raised from 1,111,111 to 1,311,111 so the made-up answer "lowest in Nov 2026" is true for these rows (the new range check 10 rightly flagged it)
MONTHS_ROWS = [month_row(2026, m, f"{a}.00") for m, a in ((6, 1311111), (7, 2222222), (8, 3333333), (9, 4444444),
                                                         (10, 5555555), (11, 1234567))]
PART_ANSWER = ("Net sales were highest in Oct 2026 (INR 5,555,555.00) and lowest in Nov 2026 (INR 1,234,567.00).")


@pytest.fixture
def data_end(monkeypatch):
    monkeypatch.setattr(agent, "invoice_data_dates", lambda: (datetime.date(2025, 12, 21), DATA_END))


def test_a_month_after_the_data_end_told_as_full_is_flagged(data_end):
    correction, _facts = answer_verify.problems(result_of(MONTHS_SQL, MONTHS_COLUMNS, MONTHS_ROWS), PART_ANSWER)

    assert ("Nov 2026 (21-Oct-2026 to 20-Nov-2026) has data only up to 31-Oct-2026 - the invoice data ends there, so "
            "it is an incomplete month (11 of its 31 days)") in correction
    assert "e.g. \"Nov 2026 has data only up to 31-Oct-2026 (incomplete month)\"" in correction


@pytest.mark.parametrize("answer", [
    PART_ANSWER + " Nov 2026 is an incomplete month.",
    PART_ANSWER.replace("lowest in Nov 2026", "lowest in Nov 2026 so far"),
    PART_ANSWER + " The invoice data runs up to 31-Oct-2026.",
    PART_ANSWER + " November 2026 is only partial.",
])
def test_a_month_after_the_data_end_told_as_incomplete_is_not_flagged(data_end, answer):
    assert answer_verify.problems(result_of(MONTHS_SQL, MONTHS_COLUMNS, MONTHS_ROWS), answer) == ("", "")


def test_months_up_to_the_data_end_are_not_flagged(data_end):
    rows = MONTHS_ROWS[:-1]
    answer = "Net sales were highest in Oct 2026 (INR 5,555,555.00) and lowest in Jun 2026 (INR 1,311,111.00)."
    assert answer_verify.problems(result_of(MONTHS_SQL, MONTHS_COLUMNS, rows), answer) == ("", "")


def test_the_part_month_check_is_only_for_invoice_rows(data_end):
    forecast_sql = MONTHS_SQL.replace("fact_invoice_lines il", "fact_invoice_lines il, ml_sales_forecast f")
    assert answer_verify.problems(result_of(forecast_sql, MONTHS_COLUMNS, MONTHS_ROWS), PART_ANSWER) == ("", "")
    orders_sql = MONTHS_SQL.replace("fact_invoice_lines", "fact_sales_order_lines")
    assert answer_verify.problems(result_of(orders_sql, MONTHS_COLUMNS, MONTHS_ROWS), PART_ANSWER) == ("", "")


def test_a_calendar_month_ends_on_its_last_day(data_end):
    columns = ["month_year", "net_sales_inr"]
    rows = [["Sep 2026", Decimal("4444444.00")], ["Oct 2026", Decimal("5555555.00")]]
    answer = "Net sales were INR 4,444,444.00 in Sep 2026 and INR 5,555,555.00 in Oct 2026."
    assert answer_verify.problems(result_of(MONTHS_SQL, columns, rows), answer) == ("", "")   # Oct ends 31-Oct
    later = rows + [["Nov 2026", Decimal("1234567.00")]]
    correction, _facts = answer_verify.problems(result_of(MONTHS_SQL, columns, later),
                                                answer + " Nov 2026 had INR 1,234,567.00.")
    assert "Nov 2026 (01-Nov-2026 to 30-Nov-2026) is after the invoice data, which ends on 31-Oct-2026" in correction


def test_unknown_data_dates_leave_the_other_checks_running(monkeypatch):
    def broken():
        raise RuntimeError("MySQL is away")

    monkeypatch.setattr(agent, "invoice_data_dates", broken)
    assert answer_verify.problems(result_of(MONTHS_SQL, MONTHS_COLUMNS, MONTHS_ROWS), PART_ANSWER) == ("", "")
    correction, _facts = answer_verify.problems(result_of(MONTHS_SQL, MONTHS_COLUMNS, MONTHS_ROWS),
                                                PART_ANSWER + " The total was INR 99,999,999.00.")
    assert "99,999,999.00" in correction                               # check 2 still ran


def test_the_part_month_answer_is_rewritten_once(monkeypatch, mysql, data_end):  # noqa: F811
    fixed = PART_ANSWER + " Nov 2026 has data only up to 31-Oct-2026 (incomplete month)."
    fake = use_fake_ai(monkeypatch, [PART_ANSWER, fixed])

    answer = agent.explain(result_of(MONTHS_SQL, MONTHS_COLUMNS, MONTHS_ROWS, text="Net sales by month"))

    assert answer == fixed and len(fake.calls) == 2
    assert "Nov 2026 has data only up to 31-Oct-2026" in fake.calls[1][-1]["content"]


# ---------- E. (23-Nov) the 2nd / Nth newest period taken from rows that repeat it ----------

LAST_TWO_BAD = ("WITH r AS (SELECT report_date FROM fact_stock_ledger sl JOIN dim_stock_movement_types t "
                "ON t.movement_type_id = sl.movement_type_id WHERE t.movement_type = 'Closing balance' "
                "ORDER BY sl.report_date DESC LIMIT 2)\n"
                "SELECT sl.product_id, SUM(sl.cumulative_value) AS v FROM fact_stock_ledger sl "
                "WHERE sl.report_date IN (SELECT report_date FROM r) GROUP BY sl.product_id")
LAST_TWO_GOOD = LAST_TWO_BAD.replace("SELECT report_date FROM fact_stock_ledger sl JOIN",
                                     "SELECT DISTINCT report_date FROM fact_stock_ledger sl JOIN")


@pytest.mark.parametrize("sql, part", [
    (LAST_TWO_BAD, "LIMIT 2"),
    ("SELECT SUM(cumulative_value) FROM fact_stock_ledger WHERE report_date = (SELECT report_date FROM "
     "fact_stock_ledger ORDER BY report_date DESC LIMIT 1 OFFSET 1)", "LIMIT 1 OFFSET 1"),
    ("SELECT SUM(net_taxable_value) FROM fact_invoice_lines WHERE invoice_date IN (SELECT invoice_date FROM "
     "fact_invoice_lines ORDER BY invoice_date DESC LIMIT 3)", "LIMIT 3"),
    ("SELECT SUM(il.net_taxable_value) FROM fact_invoice_lines il JOIN dim_calendar c ON c.date_id = "
     "il.invoice_date_id WHERE c.sales_month IN (SELECT sales_month FROM dim_calendar WHERE full_date <= CURDATE() "
     "ORDER BY full_date DESC LIMIT 6)", "LIMIT 6"),
])
def test_a_period_picked_from_repeating_rows_is_found(sql, part):
    found = agent.repeated_period_values(sql)
    assert found is not None and found[1].endswith(part)


@pytest.mark.parametrize("sql", [
    LAST_TWO_GOOD,
    "SELECT report_date FROM fact_stock_ledger GROUP BY report_date ORDER BY report_date DESC LIMIT 2",
    "SELECT MAX(report_date) FROM fact_stock_ledger",
    "SELECT report_date FROM fact_stock_ledger ORDER BY report_date DESC LIMIT 1",              # the newest: fine
    "SELECT full_date FROM dim_calendar WHERE full_date <= CURDATE() ORDER BY full_date DESC LIMIT 7",   # one row a day
    "SELECT p.product_code, sl.report_date FROM fact_stock_ledger sl JOIN dim_products p ON p.product_id = "
    "sl.product_id ORDER BY sl.report_date DESC LIMIT 10",                                     # not a period pick
    "SELECT invoice_date FROM fact_invoice_lines WHERE customer_id = 5 ORDER BY invoice_date LIMIT 500",   # a list
    "SELECT report_date FROM (SELECT DISTINCT report_date FROM fact_stock_ledger) d ORDER BY report_date DESC "
    "LIMIT 1 OFFSET 1",
    "SELECT",                                                                                   # cannot be read
])
def test_distinct_periods_and_other_sql_are_not_flagged(sql):
    assert agent.repeated_period_values(sql) is None


def test_a_period_picked_from_repeating_rows_goes_back_to_the_ai(monkeypatch, mysql, user):  # noqa: F811
    # (the fake MySQL has the invoice tables: the same mistake on the invoice dates)
    bad = ("SELECT SUM(il.net_taxable_value) AS sales FROM fact_invoice_lines il WHERE il.invoice_date = "
           "(SELECT invoice_date FROM fact_invoice_lines ORDER BY invoice_date DESC LIMIT 1 OFFSET 1)")
    good = bad.replace("(SELECT invoice_date FROM", "(SELECT DISTINCT invoice_date FROM")
    mysql.results = [{"columns": ["sales"], "rows": [[Decimal("10.00")]], "truncated": False}]
    fake = use_fake_ai(monkeypatch, [f"```sql\n{bad}\n```", f"```sql\n{good}\n```", "Sales were INR 10.00."])

    result = agent.ask("What were our sales on the invoice day before the last one?", user)

    assert result.tries == 2 and len(mysql.calls) == 1
    assert "SELECT DISTINCT invoice_date" in " ".join(mysql.calls[0].split())
    assert "every invoice_date has many rows" in fake.calls[1][-1]["content"]


# ---------- F. (23-Nov) an only_full_group_by error goes back with its fix ----------

def test_an_only_full_group_by_error_gets_the_fix_naming_its_column():
    error = ("(1140) In aggregated query without GROUP BY, expression #1 of SELECT list contains nonaggregated column "
             "'fy.fy_start'; this is incompatible with sql_mode=only_full_group_by")
    hint = agent.mysql_error_hint(error)
    assert "write MIN(fy.fy_start) (or ANY_VALUE(fy.fy_start)), or add it to GROUP BY" in hint
    assert "MIN(x.y)" in agent.mysql_error_hint("(1055) Expression #2 of SELECT list is not in GROUP BY clause and "
                                                "contains nonaggregated column 'x.y' which is not functionally ...")
    assert agent.mysql_error_hint("(1054) Unknown column 'cu.region' in 'where clause'") == ""
    assert agent.mysql_error_hint(None) == ""
