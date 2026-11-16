"""A period that is not over yet must stop at TODAY - using today's date only to pick the period is not enough.

16-Nov (office PC): "ho is or new customer of this month" got a query that picked the sales month with
sales_month = (SELECT sales_month FROM dim_calendar WHERE full_date = CURRENT_DATE) and then counted the
invoices up to the month's end (20-Nov): 1,088 new customers instead of 967 up to today. The check
(agent.periods_not_over) was skipped because CURRENT_DATE was in the SQL at all (stops_at_today). Now today's date
must be an UPPER bound (agent.cut_at_today), and a period picked by today's date counts as "not over" too
(agent.current_periods).

Run with:  python -m pytest -q portal/tests/test_period_today.py
"""
import datetime

import pytest

from portal.rag import agent
from portal.tests.test_agent import mysql, use_fake_ai  # noqa: F401
from portal.tests.test_graph import DATA_START, steps  # noqa: F401

pytestmark = pytest.mark.django_db  # agent.ask() saves a Question

TODAY = datetime.date(2026, 11, 16)

# the query of 16-Nov, as the AI wrote it on the office PC (shortened, the same shape)
OFFICE_SQL = """WITH this_month AS (
  SELECT sales_month, sales_period_start AS period_from, sales_period_end AS period_to
  FROM dim_calendar
  WHERE sales_month = (SELECT sales_month FROM dim_calendar WHERE full_date = CURRENT_DATE)
  LIMIT 1
), first_purchase AS (
  SELECT il.customer_id, MIN(il.invoice_date) AS first_invoice_date,
    SUM(CASE WHEN il.invoice_date BETWEEN tm.period_from AND tm.period_to THEN il.net_taxable_value ELSE 0 END)
      AS sales_in_month
  FROM fact_invoice_lines AS il JOIN this_month AS tm ON 1 = 1
  GROUP BY il.customer_id
)
SELECT tm.sales_month AS sales_month, tm.period_from, tm.period_to, cu.customer_name, fp.first_invoice_date,
  ROUND(fp.sales_in_month, 2) AS sales_in_month_inr, COUNT(*) OVER () AS new_customers
FROM first_purchase AS fp
JOIN dim_customers AS cu ON cu.customer_id = fp.customer_id
JOIN this_month AS tm ON 1 = 1
WHERE fp.first_invoice_date BETWEEN tm.period_from AND tm.period_to AND fp.customer_id <> -1
ORDER BY fp.sales_in_month DESC"""
FIXED_SQL = OFFICE_SQL.replace("GROUP BY il.customer_id", "WHERE il.invoice_date <= CURDATE()\n  GROUP BY il.customer_id")


# ---------- today as an upper bound ----------

@pytest.mark.parametrize("sql", [
    "SELECT 1 FROM t WHERE d <= CURDATE()",
    "SELECT 1 FROM t WHERE d < CURRENT_DATE",
    "SELECT 1 FROM t WHERE d BETWEEN '2026-04-01' AND CURDATE()",
    "SELECT 1 FROM t WHERE CURDATE() >= d",
    "SELECT 1 FROM t WHERE d <= NOW()",
    "SELECT 1 FROM t WHERE d <= DATE(NOW())",
    "SELECT LEAST(sales_period_end, CURDATE()) AS so_far_to FROM dim_calendar WHERE full_date = CURDATE()",
    FIXED_SQL,
])
def test_today_as_an_upper_bound_cuts_the_rows(sql):
    assert agent.cut_at_today(sql)


@pytest.mark.parametrize("sql", [
    "SELECT 1 FROM t WHERE full_date = CURRENT_DATE",     # today only picks something
    "SELECT 1 FROM t WHERE d >= CURDATE()",                # from today on: the future
    "SELECT 1 FROM t",
    OFFICE_SQL,
])
def test_today_used_only_to_pick_does_not_cut(sql):
    assert not agent.cut_at_today(sql)


def test_an_unreadable_sql_falls_back_to_the_old_word_check():
    assert agent.cut_at_today("SELECT ( CURDATE") is True
    assert agent.cut_at_today("SELECT ( nothing") is False


# ---------- the period picked by today's date ----------

def test_the_office_query_is_this_sales_month_not_over_and_the_fixed_one_is_fine():
    assert agent.current_periods(OFFICE_SQL) == ["This sales month"]
    assert agent.periods_not_over(OFFICE_SQL, TODAY) == ["This sales month"]
    assert agent.periods_not_over(FIXED_SQL, TODAY) == []


@pytest.mark.parametrize("column, label", [
    ("financial_year", "This FY"), ("month_year", "This calendar month"), ("fiscal_quarter", "This quarter"),
])
def test_other_periods_picked_by_today(column, label):
    sql = (f"SELECT SUM(il.net_taxable_value) FROM fact_invoice_lines il JOIN dim_calendar c ON c.date_id = "
           f"il.invoice_date_id WHERE c.{column} = (SELECT {column} FROM dim_calendar WHERE full_date = CURDATE())")
    assert agent.periods_not_over(sql, TODAY) == [label]


def test_a_named_period_still_works_as_before():
    fy = ("SELECT SUM(il.net_taxable_value) FROM fact_invoice_lines il JOIN dim_calendar c "
          "ON c.date_id = il.invoice_date_id WHERE c.financial_year = '2627'")
    assert agent.periods_not_over(fy, TODAY) == ["Financial year 2627 (FY 2026-27)"]
    assert agent.periods_not_over(fy + " AND il.invoice_date <= CURRENT_DATE", TODAY) == []
    # a past period is over: nothing to say
    assert agent.periods_not_over(fy.replace("'2627'", "'2526'"), TODAY) == []


# ---------- in the graph: sent back once, the fixed query runs ----------

ROWS = {"columns": ["sales_month", "customer_name", "new_customers"],
        "rows": [["Nov 2026", "Sunrise Precision Components Ltd", 967]], "truncated": False}
ANSWER = "So far in sales month Nov 2026 (up to 16-Nov-2026), 967 customers bought for the first time."


def test_the_16_nov_query_is_sent_back_and_the_query_up_to_today_is_answered(monkeypatch, mysql, user, steps):
    mysql.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [(f"```sql\n{OFFICE_SQL}\n```", 3000), (f"```sql\n{FIXED_SQL}\n```", 3100),
                                     (ANSWER, 800)])

    result = agent.ask("ho is or new customer of this month", user)

    assert steps == DATA_START + ["write_sql", "check_sql", "retry", "write_sql", "check_sql", "run_sql", "explain"]
    assert len(mysql.calls) == 1 and agent.cut_at_today(mysql.calls[0])  # the 17-20 Nov rows never counted
    sent_back = fake.calls[1][-1]["content"]
    assert "This sales month is not over yet" in sent_back and "<= CURDATE()" in sent_back
    assert result.status == "ok" and result.answer == ANSWER and result.tries == 2


def test_last_month_picked_from_today_is_over_and_not_sent_back():
    """05-Nov / 16-Nov "what is our last month sales": today's calendar row only finds the month BEFORE it."""
    last_month = """WITH last_month AS (
  SELECT p.sales_month, p.sales_period_start, p.sales_period_end
  FROM dim_calendar AS t JOIN dim_calendar AS p ON p.full_date = t.sales_period_start - INTERVAL '1' DAY
  WHERE t.full_date = CURRENT_DATE
)
SELECT lm.sales_month, ROUND(SUM(il.net_taxable_value), 2) AS net_sales_inr
FROM last_month AS lm LEFT JOIN fact_invoice_lines AS il
  ON il.invoice_date BETWEEN lm.sales_period_start AND lm.sales_period_end
GROUP BY lm.sales_month"""
    assert agent.current_periods(last_month) == []
    assert agent.periods_not_over(last_month, TODAY) == []
    # but picking the columns of today's own row is "this month"
    assert agent.current_periods(last_month.replace("SELECT p.sales_month", "SELECT t.sales_month")) == [
        "This sales month"]


def test_no_example_sql_of_the_docs_is_sent_back_as_not_over():
    """The example SQL in docs/sql_examples.md are the right way: none of them may be refused by this check."""
    from pathlib import Path

    from portal.lc.docs import load_docs

    examples = [c for c in load_docs(Path(__file__).resolve().parents[2] / "docs") if c["kind"] == "example"]
    assert examples
    flagged = [c["heading"] for c in examples if agent.periods_not_over(agent.strip_fences(c["text"]), TODAY)
               and agent.current_periods(agent.strip_fences(c["text"]))]
    assert flagged == []
