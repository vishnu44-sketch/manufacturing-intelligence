"""The question notes our code works out BEFORE an AI call (portal/question_notes.py).

20-Nov-2026 (the company's local model, 95 golden questions): "this financial year" questions were filtered as the
PREVIOUS financial year (c.financial_year = '2526' while FY 2026-27 = '2627' was running). Now the SQL request gets
a short "For this question:" block with the FY of today and its code (and the last N complete sales months, a month
the data end cuts, the product codes), and the answer request a "For this answer:" block (forecast amounts in Cr,
product codes). Nothing is fixed: the tests use two different "today"s (20-Nov-2026 and 05-Apr-2027) and data ends.
A question that needs no note gets none - its request is exactly as before.

No test calls the AI or MySQL: the AI is test_agent's FakeAI, the data end a function given here.
Run with:  python -m pytest -q portal/tests/test_question_notes.py
"""
from datetime import date

import pytest

from portal import question_notes as qn
from portal.lc import calls, prompts
from portal.lc.calls import LcRequest
from portal.rag import agent
from portal.tests.test_agent import ANSWER, ROWS, mysql, use_fake_ai  # noqa: F401

NOV_20 = date(2026, 11, 20)
APR_5 = date(2027, 4, 5)
DATA_END = date(2026, 10, 31)


def ends(day):
    """A data end function (what qn.data_end gives) that says `day`."""
    return lambda: day


def never():
    raise AssertionError("the data end was asked for a question that needs no data")


@pytest.fixture(autouse=True)
def fresh_cache():
    qn.clear_cache()
    yield
    qn.clear_cache()


# ---------- "this year" = the financial year of today ----------

@pytest.mark.parametrize("question", [
    "How many customers make up half of our sales this financial year?",
    "Who is our biggest customer in Japan this financial year?",
    "How much of this year's sales is booked to an unknown customer?",
    "What are our total sales so far?",
    "current year sales by state",
    "YTD sales by sale type",
])
def test_this_year_gets_the_fy_of_today_and_its_code(question):
    lines = qn.sql_notes(question, NOV_20, never)
    assert lines[0].startswith("- this year / this financial year = FY 2026-27 (01-Apr-2026 to 31-Mar-2027")
    assert "c.financial_year = '2627'" in lines[0]
    assert "Last year = FY 2025-26 (01-Apr-2025 to 31-Mar-2026): c.financial_year = '2526'" in lines[0]
    assert "never use '2526' for this year" in lines[0]


def test_another_today_gives_another_fy():
    """Nothing is fixed: on 05-Apr-2027 this year is FY 2027-28 ('2728') and '2627' is last year."""
    line = qn.sql_notes("How many customers make up half of our sales this financial year?", APR_5, never)[0]
    assert "FY 2027-28 (01-Apr-2027 to 31-Mar-2028" in line and "c.financial_year = '2728'" in line
    assert "Last year = FY 2026-27" in line and "never use '2627' for this year" in line
    assert "2526" not in line


@pytest.mark.parametrize("day, label", [(date(2027, 2, 10), "FY 2026-27"), (date(2027, 3, 31), "FY 2026-27"),
                                        (date(2027, 4, 1), "FY 2027-28"), (date(2030, 6, 1), "FY 2030-31")])
def test_jan_to_mar_belong_to_the_fy_that_began_last_april(day, label):
    assert f"= {label} (" in qn.sql_notes("sales this year", day, never)[0]


def test_a_split_by_month_also_gets_the_sales_year_code():
    line = qn.sql_notes("How much GST did we collect each month this financial year?", NOV_20, never)[0]
    assert "Split by sales month: c.sales_year = '2627' (sales months Apr 2026 to Mar 2027)" in line
    assert "c.sales_year = '2728'" in qn.sql_notes("monthly sales this year", APR_5, never)[0]
    assert "sales_year" not in qn.sql_notes("sales this year", NOV_20, never)[0]


def test_last_year_alone_gets_the_fy_line_too():
    line = qn.sql_notes("Which of last year's top 20 customers bought the most?", NOV_20, never)[0]
    assert "Last year = FY 2025-26" in line and "c.financial_year = '2526'" in line


@pytest.mark.parametrize("question", [
    "Which product category sold the most quantity in FY 2026-27?",   # a named FY
    "sales in FY 2025-26 so far",
    "sales of 2026 so far",                                            # a named calendar year
    "sales this calendar year",
    "total sales in 2026",
    "top customer in Japan",                                           # no period at all
    "What will our sales be in the next 3 months?",
    "is the data up to date?",
])
def test_no_fy_line_when_the_user_named_the_year_or_no_year(question):
    assert not any("financial_year" in line for line in qn.sql_notes(question, NOV_20, ends(DATA_END)))


def test_so_far_of_a_month_is_the_month_not_the_year():
    lines = qn.sql_notes("What are our sales this month so far?", NOV_20, ends(DATA_END))
    assert lines == ["- this month = sales month Nov 2026 (21-Oct-2026 to 20-Nov-2026), so far = up to today; "
                     "Nov 2026 has data only up to 31-Oct-2026 (incomplete)."]


# ---------- months and quarters: from today and the data end ----------

def test_the_last_3_months_are_the_last_3_complete_sales_months_up_to_the_data_end():
    lines = qn.sql_notes("Which customers have not bought anything in the last 3 months?", NOV_20, ends(DATA_END))
    assert lines == ["- the last 3 months = the last 3 complete sales months up to the data end: Aug 2026 to Oct 2026 "
                     "(21-Jul-2026 to 20-Oct-2026; the invoice data ends 31-Oct-2026): "
                     "c.sales_month IN ('Aug 2026', 'Sep 2026', 'Oct 2026')."]


def test_the_last_months_move_with_today_and_the_data():
    """05-Apr-2027 with data to 20-Mar-2027: Mar 2027 (ends 20-Mar) is complete - Jan to Mar 2027."""
    line = qn.sql_notes("sales in the last 3 months", APR_5, ends(date(2027, 3, 20)))[0]
    assert "Jan 2027 to Mar 2027 (21-Dec-2026 to 20-Mar-2027" in line
    # data after today (a demo load): up to today, not the data end
    line = qn.sql_notes("sales in the last 2 months", NOV_20, ends(date(2027, 3, 20)))[0]
    assert "up to today: Oct 2026 to Nov 2026 (21-Sep-2026 to 20-Nov-2026" in line


def test_past_months_without_a_number_are_3_and_12_months_get_dates_only():
    assert "Aug 2026 to Oct 2026" in qn.sql_notes("sales in the past months", NOV_20, ends(DATA_END))[0]
    line = qn.sql_notes("net sales of the last 12 months", NOV_20, ends(DATA_END))[0]
    assert "Nov 2025 to Oct 2026 (21-Oct-2025 to 20-Oct-2026" in line and "IN (" not in line


def test_the_last_months_without_a_data_end_count_up_to_today():
    line = qn.sql_notes("sales in the last 3 months", NOV_20, ends(None))[0]
    assert "up to today: Sep 2026 to Nov 2026" in line and "data ends" not in line


def test_last_month_and_the_quarters():
    assert qn.sql_notes("last month sales", NOV_20, ends(DATA_END)) == [
        "- last month = sales month Oct 2026 (21-Sep-2026 to 20-Oct-2026)."]
    lines = qn.sql_notes("sales last quarter and this quarter", NOV_20, ends(DATA_END))
    assert lines[0].startswith("- this quarter = Q3 of FY 2026-27 (01-Oct-2026 to 31-Dec-2026; calendar dates): "
                               "c.financial_year = '2627' AND c.fiscal_quarter = 3")
    assert lines[0].endswith("has data only up to 31-Oct-2026 (incomplete).")
    assert lines[1] == ("- last quarter = Q2 of FY 2026-27 (01-Jul-2026 to 30-Sep-2026; calendar dates): "
                        "c.financial_year = '2627' AND c.fiscal_quarter = 2.")
    # 05-Apr-2027: Q1 of FY 2027-28, the last quarter is Q4 of FY 2026-27 (Jan-Mar 2027)
    lines = qn.sql_notes("sales last quarter", APR_5, ends(date(2027, 3, 20)))
    assert lines == ["- last quarter = Q4 of FY 2026-27 (01-Jan-2027 to 31-Mar-2027; calendar dates): "
                     "c.financial_year = '2627' AND c.fiscal_quarter = 4; Q4 of FY 2026-27 has data only up to "
                     "20-Mar-2027 (incomplete)."]


def test_a_named_month_the_data_end_cuts():
    assert qn.sql_notes("sales in Nov 2026 by customer", NOV_20, ends(DATA_END)) == [
        "- Nov 2026 = sales month 21-Oct-2026 to 20-Nov-2026; Nov 2026 has data only up to 31-Oct-2026 (incomplete)."]
    assert qn.sql_notes("sales in Oct 2026 by customer", NOV_20, ends(DATA_END)) == []       # complete
    # an older month: no data query at all (the answer's data_coverage_notes tell its dates)
    assert qn.sql_notes("sales in Aug 2026 by customer", NOV_20, never) == []
    assert qn.sql_notes("forecast for Aug 2027", NOV_20, never) == []
    assert qn.sql_notes("sales in calendar month Nov 2026", NOV_20, never) == []


def test_questions_without_these_words_never_ask_for_the_data_end():
    for question in ("top customer in Japan", "sales this year", "Which 5 products sold the most in FY 2026-27?",
                     "What will our sales be in the next 3 months?", "stock value by warehouse"):
        qn.sql_notes(question, NOV_20, never)


# ---------- products ----------

@pytest.mark.parametrize("question, wanted", [
    ("What are the top 10 products by quantity sold this year?", True),
    ("Which items had the biggest increase in stock value between 30-Jun-2026 and 31-Oct-2026?", True),
    ("list the products we sold to Sakura Pump", True),
    ("Which product category sold the most quantity in FY 2026-27?", False),
    ("give me product category wise total revenue in sep 2026", False),
    ("How many items have zero stock right now?", False),
    ("Which products are bought together most often?", False),
    ("top customers in Japan", False),
])
def test_a_list_of_products_gets_the_product_code_line(question, wanted):
    lines = qn.sql_notes(question, NOV_20, ends(DATA_END))
    assert any("p.product_code next to p.product_description" in line for line in lines) is wanted


# ---------- 23-Nov: stock held, profit of one period ----------

@pytest.mark.parametrize("question, wanted", [
    ("What are the top 10 products by quantity sold this year, and how much stock do we have of each?", True),
    ("How many units of FG00542 are on open sales orders, and how much of it do we have in stock?", True),
    ("What is our inventory value by warehouse?", True),
    ("Which items will run out of stock soon?", False),             # ml_stock_runout
    ("top customers in Japan", False),
    ("net sales this year", False),
])
def test_a_stock_question_gets_the_stock_report_line(question, wanted):
    lines = qn.sql_notes(question, NOV_20, ends(DATA_END))
    found = [line for line in lines if "SELECT sl.report_date" in line]
    assert bool(found) is wanted
    if wanted:
        assert "never from dim_products.in_stock_qty" in found[0]
        assert "SELECT DISTINCT report_date" not in found[0]          # only for the last N reports


@pytest.mark.parametrize("question, wanted", [
    ("How many of our active customers have not bought anything from us this financial year?", True),
    ("list inactive customers who bought in Oct 2026", True),
    ("How many customers bought in Oct 2026?", False),
    ("Which items are active?", False),
])
def test_active_customers_are_the_masters_is_active(question, wanted):
    lines = qn.sql_notes(question, NOV_20, ends(DATA_END))
    assert any("dim_customers.is_active = 'Y'" in line and "document_type = 'INVOICE'" in line
               for line in lines) is wanted


@pytest.mark.parametrize("question, wanted", [
    ("Which finished goods had no sales between 01-May-2026 and 31-Oct-2026?", True),
    ("which products were not sold in FY 2025-26", True),
    ("raw materials that have not been invoiced since April", True),
    ("Which items were in stock on 31-Oct-2026 but had no sales between 01-May-2026 and 31-Oct-2026?", False),
    ("Which finished goods have stock but no sales in the last 90 days?", False),
    ("Which customers bought in Jan 2026 but have bought nothing since Oct 2026?", False),   # no items
    ("top 5 products in Oct 2026", False),
])
def test_items_with_no_sales_are_every_item_of_the_master(question, wanted):
    lines = qn.sql_notes(question, NOV_20, ends(DATA_END))
    assert any("every item of the product master" in line and "COUNT(*) OVER ()" in line for line in lines) is wanted


def test_exact_dates_are_used_as_given():
    """23-Nov: "between 01-May-2026 and 31-Oct-2026" was widened to 21-Apr-2026 to 20-Nov-2026 (the sales periods)."""
    line = qn.exact_dates_line("Which finished goods had no sales between 01-May-2026 and 31-Oct-2026?")
    assert line.startswith("- 01-May-2026 and 31-Oct-2026 are exact calendar dates: use them as given "
                           "('2026-05-01', '2026-10-31' on invoice_date")
    assert "never widen them to the sales periods" in line
    assert qn.exact_dates_line("stock value on 2026-06-30 by warehouse").startswith(
        "- 30-Jun-2026 is an exact calendar date: use it as given ('2026-06-30'")
    assert "05-Feb-2027" in qn.exact_dates_line("invoices of 5 February 2027")
    for question in ("Show net sales month by month from Jan 2026 to Oct 2026", "sales in FY 2026-27",
                     "top 5 customers in Aug 2026", "orders on 31-Feb-2026"):           # no day / not a real day
        assert qn.exact_dates_line(question) == ""
    assert any("exact calendar date" in line for line in qn.sql_notes("sales on 01-Oct-2026", NOV_20, ends(DATA_END)))


def test_the_last_stock_reports_are_the_distinct_report_dates():
    """23-Nov: "between the last two stock reports" took ORDER BY report_date LIMIT 2 of the ledger rows (the newest
    date twice, every drop 0)."""
    for question in ("Which products' stock dropped the most between the last two stock reports?",
                     "stock value of each item in the latest 3 stock reports"):
        line = next(line for line in qn.sql_notes(question, NOV_20, never) if "stock report" in line)
        assert "SELECT DISTINCT report_date FROM fact_stock_ledger ORDER BY report_date DESC LIMIT N" in line
    line = next(line for line in qn.sql_notes("stock value by warehouse", NOV_20, never) if "stock report" in line)
    assert "DISTINCT" not in line


@pytest.mark.parametrize("question, wanted", [
    ("what is our profit margin this year", True),
    ("gross profit of Sakura Pump in Oct 2026", True),
    ("profit % last year and this year", False),                    # between two periods: the revenue growth
    ("profit growth vs FY 2025-26", False),
    ("What is our cost of goods sold now?", False),                  # COGS is in the stock report
    ("net sales this year", False),
])
def test_a_profit_of_one_period_gets_the_not_in_data_line(question, wanted):
    lines = qn.sql_notes(question, NOV_20, ends(DATA_END))
    assert any("profit / margin is not in ss_gold" in line and "NO_DATA" in line for line in lines) is wanted


# ---------- the answer request ----------

FORECAST_TABLE = ("sales_month | forecast_inr | low_inr | high_inr | mape_pct\n"
                  "Nov 2026 | 534,887,655.19 | 498,487,638.37 | 571,287,672.01 | 4.16\n"
                  "Dec 2026 | 520,000,000.00 | 480,000,000.00 | 560,000,000.00 | 4.16")


def test_a_forecast_answer_gets_the_cr_rule_with_an_example_from_its_own_rows():
    lines = qn.answer_notes("What will our sales be next month?", "SELECT * FROM ml_sales_forecast", FORECAST_TABLE)
    assert lines == ["- Write forecast amounts rounded in Cr (e.g. 534,887,655.19 = about INR 53.5 Cr, range 49.8 - "
                     "57.1 Cr) - the exact numbers are in the table."]
    assert "Write forecast amounts rounded in Cr" in agent.ML_RESULTS_NOTE        # the rule's own text, reused
    # forecast words without forecast_inr rows: the rule as written in ML_RESULTS_NOTE
    line = qn.answer_notes("predict our sales", "SELECT 1", "net_sales_inr\n12.00")[0]
    assert line.startswith("- Write forecast amounts rounded in Cr (e.g. 123,456,789.00 = about INR 12.3 Cr")


def test_a_forecast_column_with_another_name_gives_the_example_from_its_rows_too():
    """23-Nov: "my top customer in Aug 2027" selects total_forecast_inr - the rule's own example amount was copied
    into the answer ("about INR 53.5 Cr" for 537,112,731.17 = 53.7 Cr)."""
    table = ("forecast_month | total_forecast_inr | low_inr | high_inr | past_top_customer | past_sales_inr\n"
             "Aug 2027 | 537,112,731.17 | 468,224,013.40 | 606,001,448.94 | Sakura Pump | 28,239,876.00")
    line = qn.answer_notes("my top customer in Aug 2027", "SELECT ... FROM ml_sales_forecast", table)[0]
    assert "(e.g. 537,112,731.17 = about INR 53.7 Cr, range 46.8 - 60.6 Cr)" in line
    # a forecast query without a forecast amount column: the rule's example, which is no real amount
    line = qn.answer_notes("forecast months", "SELECT sales_month FROM ml_sales_forecast", "sales_month\nAug 2027")[0]
    assert "about INR 12.3 Cr" in line and "53." not in line
    # past_sales_inr is never taken as the forecast
    table = "past_top_customer | past_sales_inr\nSakura Pump | 28,239,876.00"
    assert "2.8 Cr" not in qn.answer_notes("my top customer in Aug 2027", "SELECT ... FROM ml_sales_forecast", table)[0]


QUARTER_TABLE = ("financial_year_label | fiscal_quarter | net_sales_inr\n" + "\n".join(
    f"FY 2025-26 | {q} | 1,000,000.0{q}" for q in range(1, 5)) + "\n\nData dates: ...")


@pytest.mark.parametrize("question, note, wanted", [
    ("How did our sales grow quarter by quarter over the last two financial years?", "4 row(s)", "quarter"),
    ("GST collected each month this financial year", "7 row(s)", "month"),
    ("monthly sales in FY 2026-27", "", "month"),                          # the count from the table's lines
    ("quarter by quarter sales since 2024", "11 row(s)", None),           # too many: highest / lowest + the table
    ("top customers in Oct 2026", "4 row(s)", None),                      # no split by period
    ("sales each month", "1 row(s)", None),
])
def test_a_split_by_period_with_few_rows_gets_every_period(question, note, wanted):
    lines = [line for line in qn.answer_notes(question, "SELECT ...", QUARTER_TABLE, note) if "each" in line]
    if wanted is None:
        assert lines == []
    else:
        count = note.split()[0] if note else "4"
        assert lines == [f"- the question asks for each {wanted}: give every row's {wanted} with its amount as in the "
                         f"rows (all {count} rows, short) - not only the highest and the lowest; this replaces the "
                         "'more than 4 rows' rule."]


def test_rows_with_product_codes_get_the_code_line_with_their_first_product():
    table = "product_code | product_description | qty\nFG00542 | YTH-PARTS TX-325-3A 2.2kW | 1,828"
    assert qn.answer_notes("top 10 products this year", "SELECT ...", table) == [
        "- name each product with its code, e.g. YTH-PARTS TX-325-3A 2.2kW (FG00542)."]


def test_other_answers_get_no_note():
    assert qn.answer_notes("net sales in Aug 2026", "SELECT ...", "net_sales_inr\n1,000.00") == []
    assert qn.answer_notes("top products", "SELECT ...", "(no rows)") == []


# ---------- the hook: LcRequest.inputs() ----------

SQL_VALUES = dict(schema="dim_customers: customer_id", count=1, documents="d", today="20-Nov-2026 (Friday)",
                  earlier="", question="How many customers make up half of our sales this financial year?")


def test_the_sql_block_goes_right_before_the_question(monkeypatch):
    monkeypatch.setattr(agent, "today", lambda: NOV_20)
    inputs = LcRequest("sql", SQL_VALUES).inputs()
    request = prompts.SQL_PROMPT.format_messages(**inputs)[1].content
    block, question = request.split("\nQuestion: ")
    assert block.startswith(f"ss_gold schema") and question == SQL_VALUES["question"]
    assert block.endswith(f"Today is 20-Nov-2026 (Friday).\n{qn.HEADING}\n" + qn.sql_notes(SQL_VALUES["question"],
                                                                                            NOV_20, never)[0] + "\n")


def test_a_question_without_notes_gets_the_request_exactly_as_before(monkeypatch):
    monkeypatch.setattr(agent, "today", lambda: NOV_20)
    values = {**SQL_VALUES, "question": "top customer in Japan"}
    assert LcRequest("sql", values).inputs() == {**values, "retries": []}
    answer = dict(question="net sales in Aug 2026", understood="", sql="SELECT 1", note="1 row(s)", periods="",
                  table="net_sales_inr\n1.00", documents="")
    assert LcRequest("answer", answer).inputs() == answer


def test_the_notes_read_only_the_users_words_and_the_written_out_question(monkeypatch):
    """The app's own notes after the question (ML mode, a previous query's SQL) are not the user's words."""
    monkeypatch.setattr(agent, "today", lambda: NOV_20)
    values = {**SQL_VALUES, "question": "and for Japan?\n(Written out in full: Net sales to Japan this financial "
                                        "year)" + agent.ML_MODE_NOTE + "\n(This question may be about an earlier "
                                        "answer's own result. SELECT ... last 3 months ...)"}
    earlier = LcRequest("sql", values).inputs()["earlier"]
    assert "FY 2026-27" in earlier and "last 3 months" not in earlier


def test_the_backup_models_cut_request_keeps_the_notes(monkeypatch):
    monkeypatch.setattr(agent, "today", lambda: NOV_20)
    request = LcRequest("sql", {**SQL_VALUES, "earlier": "Earlier in this chat: ...\n"})
    smallest = calls.for_backup(request, smallest=True).inputs()
    assert smallest["earlier"].startswith(qn.HEADING) and "'2627'" in smallest["earlier"]


def test_the_answer_block_goes_at_the_very_end(monkeypatch):
    values = dict(question="What will our sales be next month?", understood="", sql="SELECT * FROM ml_sales_forecast",
                  note="2 row(s)", periods="", table=FORECAST_TABLE, documents="")
    request = prompts.EXPLAIN_PROMPT.format_messages(**LcRequest("answer", values).inputs())[1].content
    assert request.endswith(f"\n\n{qn.ANSWER_HEADING}\n- Write forecast amounts rounded in Cr (e.g. 534,887,655.19 = "
                            "about INR 53.5 Cr, range 49.8 - 57.1 Cr) - the exact numbers are in the table.")


def test_a_failure_in_the_notes_never_stops_the_question(monkeypatch):
    def broken():
        raise RuntimeError("MySQL is gone")
    monkeypatch.setattr(agent, "invoice_data_dates", broken)
    values = {**SQL_VALUES, "question": "sales in the last 3 months"}
    assert LcRequest("sql", values).inputs()["earlier"] == ""


# ---------- the data end: from the data, kept a while ----------

def test_the_data_end_comes_from_the_data_and_is_kept(monkeypatch):
    asked = []
    monkeypatch.setattr(agent, "invoice_data_dates", lambda: asked.append(1) or (date(2024, 4, 2), DATA_END))
    assert qn.data_end(NOV_20) == DATA_END and qn.data_end(NOV_20) == DATA_END and len(asked) == 1
    qn.clear_cache()
    assert qn.data_end(NOV_20) == DATA_END and len(asked) == 2


def test_no_data_end_is_not_kept(monkeypatch):
    asked = []
    monkeypatch.setattr(agent, "invoice_data_dates", lambda: asked.append(1) or None)
    assert qn.data_end(NOV_20) is None and qn.data_end(NOV_20) is None and len(asked) == 2


# ---------- in the app: the SQL call gets the block ----------

FY_SQL = ("SELECT COUNT(DISTINCT il.customer_id) AS customers FROM fact_invoice_lines il JOIN dim_calendar c "
          "ON c.date_id = il.invoice_date_id WHERE c.financial_year = '2627' AND il.invoice_date <= CURDATE()")


def test_the_sql_call_of_a_this_year_question_gets_the_fy_of_today(monkeypatch, mysql, user):
    monkeypatch.setattr(agent, "today", lambda: NOV_20)
    mysql.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [f"```sql\n{FY_SQL}\n```", ANSWER])

    result = agent.ask("How many customers bought from us this financial year?", user)

    assert result.status == "ok" and result.tries == 1
    request = fake.calls[0][-1]["content"]
    assert f"{qn.HEADING}\n- this year / this financial year = FY 2026-27" in request
    assert request.index(qn.HEADING) < request.index("\nQuestion: How many customers")
    assert qn.HEADING not in fake.calls[1][-1]["content"]                    # the answer needs no note


def test_the_sql_call_of_another_question_is_as_before(monkeypatch, mysql, user):
    monkeypatch.setattr(agent, "today", lambda: NOV_20)
    mysql.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [f"```sql\n{FY_SQL}\n```", ANSWER])

    agent.ask("How many customers are in Japan?", user)

    assert all(qn.HEADING not in message["content"] and qn.ANSWER_HEADING not in message["content"]
               for call in fake.calls for message in call)
