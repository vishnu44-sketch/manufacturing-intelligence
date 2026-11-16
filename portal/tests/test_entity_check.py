"""A ranking of customers / products / sales people / states / countries whose rows name none of them is sent back.

16-Nov (office PC): the Knowledge graph's "Ask about this" on a product asked "Top customers of Coolant pump
GX-664-1B 0.75kW (415V 50Hz)". The AI wrote a query that only added up the product's sales over ALL its 422
customers (product_description, net_sales_inr, net_quantity, matches, data_from, data_to - no customer column),
and the answer called that total "the top customer": INR 193,160,700.00 and 2,462 units. The real top customer is
Allied Castings Limited with INR 6,496,200.00 and 82 units. Now a check in our own code (agent.missing_entity,
lc/graph.run_sql) sends such a query back once; the first answer is kept when the next try is no better. The
answer prompt also says never to give a number to something the rows do not name.

The AI is the fake one of test_agent.py (FakeAI behind LangChain); MySQL and the notes search are faked.
Run with:  python -m pytest -q portal/tests/test_entity_check.py
"""
from datetime import date
from decimal import Decimal

import pytest

from portal.lc import graph
from portal.rag import agent, warehouse
from portal.tests.test_agent import earlier, mysql, use_fake_ai  # noqa: F401
from portal.tests.test_graph import DATA_START, steps  # noqa: F401

pytestmark = pytest.mark.django_db  # agent.ask() saves a Question

QUESTION = "Top customers of Coolant pump GX-664-1B 0.75kW (415V 50Hz)"
PRODUCT = "Coolant pump GX-664-1B 0.75kW (415V 50Hz)"

# the query of 16-Nov, as the AI wrote it: the product's total over all its customers
PRODUCT_TOTAL_SQL = ("```sql\nSELECT p.product_description, ROUND(SUM(il.net_taxable_value), 2) AS net_sales_inr,\n"
                     "  ROUND(SUM(il.net_quantity), 0) AS net_quantity, COUNT(*) OVER () AS matches,\n"
                     "  MIN(c.full_date) AS data_from, MAX(c.full_date) AS data_to\n"
                     "FROM fact_invoice_lines il\nJOIN dim_products p ON p.product_id = il.product_id\n"
                     "JOIN dim_calendar c ON c.date_id = il.invoice_date_id\n"
                     "WHERE p.product_description LIKE '%Coolant pump GX-664-1B%'\n"
                     "GROUP BY p.product_id, p.product_description\n```")
PRODUCT_TOTAL = {"columns": ["product_description", "net_sales_inr", "net_quantity", "matches", "data_from", "data_to"],
                 "rows": [[PRODUCT, Decimal("193160700.00"), Decimal("2462"), 1, date(2024, 12, 23),
                           date(2026, 11, 14)]],
                 "truncated": False}
WRONG_ANSWER = ("The top customer for the Coolant pump GX-664-1B 0.75kW (415V 50Hz) generated INR 193,160,700.00 "
                "in net sales and bought 2,462 units.")

# the right query: one row per customer
PER_CUSTOMER_SQL = ("```sql\nSELECT cu.customer_name, ROUND(SUM(il.net_taxable_value), 2) AS net_sales_inr,\n"
                    "  ROUND(SUM(il.net_quantity), 0) AS net_quantity\n"
                    "FROM fact_invoice_lines il\nJOIN dim_customers cu ON cu.customer_id = il.customer_id\n"
                    "JOIN dim_products p ON p.product_id = il.product_id\n"
                    f"WHERE p.product_description = '{PRODUCT}'\n"
                    "GROUP BY cu.customer_id, cu.customer_name\nORDER BY net_sales_inr DESC\nLIMIT 10\n```")
PER_CUSTOMER = {"columns": ["customer_name", "net_sales_inr", "net_quantity"],
                "rows": [["Allied Castings Limited", Decimal("6496200.00"), Decimal("82")],
                         ["Customer B", Decimal("5100000.00"), Decimal("64")],
                         ["Customer C", Decimal("4020000.00"), Decimal("51")]],
                "truncated": False}
RIGHT_ANSWER = ("The top customer for the Coolant pump GX-664-1B 0.75kW (415V 50Hz) is Allied Castings Limited "
                "with INR 6,496,200.00 in net sales and 82 units.")
SENT_BACK = "That did not work: the question asks for a ranking / list of customers"


@pytest.fixture
def tables(mysql, monkeypatch):
    """The fake MySQL also has the products and sales people tables."""
    monkeypatch.setattr(warehouse, "allowed_tables", lambda: {"dim_customers", "dim_calendar", "fact_invoice_lines",
                                                              "dim_products", "dim_sales_people"})
    return mysql


# ---------- the word rules ----------

@pytest.mark.parametrize("text, what", [
    (QUESTION, "customer"),                                              # 16-Nov
    ("top customer of coolant pump", "customer"),
    ("Top 5 export customers in Oct 2026", "customer"),
    ("which customers bought the coolant pump", "customer"),
    ("Which customer bought the most in Oct?", "customer"),
    ("who bought the most coolant pumps", "customer"),
    ("who are our best customers", "customer"),
    ("biggest customers in FY 2025-26", "customer"),
    ("most valuable customers", "customer"),
    ("top-5 customers", "customer"),
    ("list customers who bought GX-664", "customer"),
    ("customer-wise sales for Oct", "customer"),
    ("sales of the coolant pump by customer in Oct 2026", "customer"),
    ("rank customers by sales", "customer"),
    ("for each customer show the net sales", "customer"),
    ("top custmers of coolant pump", "customer"),                        # typos
    ("top costumers", "customer"),
    ("Top cutomers in Oct", "customer"),
    ("which cusotmer bought the most", "customer"),
    ("top products", "product"),
    ("which products did Allied Castings buy", "product"),
    ("best-selling products in Oct", "product"),
    ("what was best-selling in Oct?", "product"),
    ("top 10 prodcuts", "product"),
    ("top sales people", "sales person"),
    ("which sales person sold the most", "sales person"),
    ("who sold the most pumps in Oct", "sales person"),
    ("top states by sales", "state"),
    ("which state had the highest sales", "state"),
    ("which state has the most customers", "state"),                     # the state is ranked, not the customers
    ("state-wise sales", "state"),
    ("top countries", "country"),
    ("which country buys the most", "country"),
    ("top export markets", "country"),
    ("sales by country", "country"),
])
def test_a_ranking_or_list_is_found(text, what):
    assert agent.ranked_entities(text)[0][0] == what


@pytest.mark.parametrize("text", [
    "sales of Allied Castings", "Coolant pump sales in Oct", f"{PRODUCT} sales in Oct 2026",   # a name as a filter
    "sales of product GX-664 to Allied Castings", "show customer Allied Castings sales",
    "highest sales of customer Allied Castings", "sales bought by customer Allied Castings in Oct",
    "what is the total sales of customer Allied",
    "how many customers", "how many customers bought the coolant pump",                       # counts
    "number of customers in Kerala", "the most customers", "how many top customers are in Kerala",
    "share of the top 5 customers", "average sales per customer",
    "Monthly net sales of the top customer of the last 3 sales months as a line chart",   # known from the chat
    "sales to our biggest customer in Oct",
    "top customer groups", "top product categories", "what is the best customer group",       # another thing
    "which month was best selling", "top customs duty", "net sales of Oct 2026", "monthly sales trend", "", None,
])
def test_a_filter_a_count_or_another_thing_is_not(text):
    assert agent.ranked_entities(text) == []


@pytest.mark.parametrize("what, columns", [
    ("customer", ["customer_name", "net_sales_inr"]), ("customer", ["customer_code", "net_sales_inr"]),
    ("customer", ["cust_name", "s"]), ("customer", ["name", "s"]),
    ("product", ["product_description", "net_quantity"]), ("product", ["product_code", "q"]),
    ("sales person", ["sales_person_name", "net_sales_inr"]),
    ("state", ["state", "net_sales_inr"]), ("state", ["place_of_supply_state", "net_sales_inr"]),
    ("country", ["country", "net_sales_inr"]), ("country", ["country_segment", "net_sales_inr"]),
])
def test_a_column_of_the_thing_shows_it(what, columns):
    assert agent.shows_entity(what, columns)


@pytest.mark.parametrize("what, columns", [
    ("customer", PRODUCT_TOTAL["columns"]),                              # 16-Nov
    ("customer", ["customer_count", "net_sales_inr"]),                   # a count of them is no customer column
    ("country", ["country_count", "net_sales_inr"]),
    ("product", ["customer_name", "net_sales_inr"]),
    ("sales person", ["sales_month", "net_sales_inr"]),
    ("state", ["customer_name", "net_sales_inr"]),
    ("country", ["product_description", "net_sales_inr"]),
])
def test_other_columns_do_not(what, columns):
    assert not agent.shows_entity(what, columns)


def test_the_16_nov_result_misses_the_customer_and_the_problem_says_what_to_do():
    missing = agent.missing_entity(QUESTION, PRODUCT_TOTAL["columns"])
    assert missing == ("customer", "Top customers")
    text = agent.entity_problem(*missing, PRODUCT_TOTAL["columns"])
    assert text.startswith('the question asks for a ranking / list of customers ("Top customers")')
    assert "no customer column" in text and "product_description, net_sales_inr, net_quantity, matches" in text
    assert "one row per customer (dim_customers.customer_name)" in text and "ORDER BY that value DESC" in text
    assert agent.missing_entity(QUESTION, PER_CUSTOMER["columns"]) is None


def test_the_answer_prompt_never_gives_a_number_to_something_the_rows_do_not_name():
    prompt = agent.EXPLAIN_SYSTEM_PROMPT
    assert "Never say a number belongs to something the rows do not name" in prompt
    assert "say the rows do not name it and give what they do show" in prompt


# ---------- in the graph ----------

def test_the_16_nov_query_is_sent_back_once_and_the_per_customer_rows_are_answered(monkeypatch, tables, user, steps):
    tables.results = [PRODUCT_TOTAL, PER_CUSTOMER]
    fake = use_fake_ai(monkeypatch, [(PRODUCT_TOTAL_SQL, 3000), (PER_CUSTOMER_SQL, 3100), (RIGHT_ANSWER, 800)])

    result = agent.ask(QUESTION, user)

    assert steps == DATA_START + ["write_sql", "check_sql", "run_sql", "retry",
                                  "write_sql", "check_sql", "run_sql", "explain"]
    second = fake.calls[1][-1]["content"]
    assert second.startswith(SENT_BACK) and "dim_customers.customer_name" in second
    assert result.status == "ok" and result.rows == PER_CUSTOMER["rows"] and result.answer == RIGHT_ANSWER
    assert "Allied Castings Limited | 6,496,200.00" in fake.calls[2][-1]["content"]   # the answer saw the customers
    assert result.tries == 2 and len(tables.calls) == 2


def test_a_retry_still_without_a_customer_keeps_the_first_answer_and_never_loops(monkeypatch, tables, user, steps):
    tables.results = [PRODUCT_TOTAL, PRODUCT_TOTAL]
    fake = use_fake_ai(monkeypatch, [PRODUCT_TOTAL_SQL, PRODUCT_TOTAL_SQL, WRONG_ANSWER])

    result = agent.ask(QUESTION, user)

    assert steps == DATA_START + ["write_sql", "check_sql", "run_sql", "retry",
                                  "write_sql", "check_sql", "run_sql", "keep_first_answer", "explain"]
    assert result.status == "ok" and result.rows == PRODUCT_TOTAL["rows"] and result.error == ""
    assert len(fake.calls) == 3 and len(tables.calls) == 2 and result.tries == 2   # no third SQL try


@pytest.mark.parametrize("second_reply, second_run, last_step", [
    ("NO_SQL", None, "write_sql"),                                       # the AI gave up
    ("NO_DATA: not available", None, "write_sql"),
    ("```sql\nDELETE FROM fact_invoice_lines\n```", None, "check_sql"),  # the guard refuses it
    (PER_CUSTOMER_SQL, warehouse.QueryError("(1054) Unknown column 'cu.customer_nam'"), "run_sql"),
    (PER_CUSTOMER_SQL, {"columns": PER_CUSTOMER["columns"], "rows": [], "truncated": False}, "run_sql"),
])
def test_a_retry_that_fails_keeps_the_first_answer(monkeypatch, tables, user, steps, second_reply, second_run,
                                                     last_step):
    tables.results = [PRODUCT_TOTAL] + ([second_run] if second_run is not None else [])
    use_fake_ai(monkeypatch, [PRODUCT_TOTAL_SQL, second_reply, WRONG_ANSWER])

    result = agent.ask(QUESTION, user)

    assert steps[-3:] == [last_step, "keep_first_answer", "explain"] and "failed" not in steps
    assert result.status == "ok" and result.rows == PRODUCT_TOTAL["rows"] and result.error == ""


def test_the_last_try_is_answered_as_it_is(monkeypatch, tables, user, steps):
    error = warehouse.QueryError("(1054) Unknown column 'il.amount'")
    tables.results = [error, error, PRODUCT_TOTAL]
    fake = use_fake_ai(monkeypatch, [PRODUCT_TOTAL_SQL] * agent.MAX_TRIES + [WRONG_ANSWER])

    result = agent.ask(QUESTION, user)

    assert steps[-2:] == ["run_sql", "explain"] and "keep_first_answer" not in steps
    assert result.status == "ok" and result.rows == PRODUCT_TOTAL["rows"] and len(fake.calls) == agent.MAX_TRIES + 1


def test_the_right_query_is_not_sent_back(monkeypatch, tables, user, steps):
    tables.results = [PER_CUSTOMER]
    fake = use_fake_ai(monkeypatch, [PER_CUSTOMER_SQL, RIGHT_ANSWER])

    result = agent.ask(QUESTION, user)

    assert steps == DATA_START + ["write_sql", "check_sql", "run_sql", "explain"]
    assert result.status == "ok" and len(fake.calls) == 2


@pytest.mark.parametrize("question, rows", [
    (f"{PRODUCT} sales", PRODUCT_TOTAL),                                  # the product is a filter
    (f"Coolant pump GX-664-1B sales in Oct 2026", PRODUCT_TOTAL),
    (f"how many customers bought the {PRODUCT}",                          # a count
     {"columns": ["customer_count"], "rows": [[422]], "truncated": False}),
    ("top customers last 6 months", PER_CUSTOMER),                        # the customers are there
])
def test_a_filter_a_count_or_a_right_result_is_answered_as_it_is(monkeypatch, tables, user, steps, question, rows):
    tables.results = [rows]
    fake = use_fake_ai(monkeypatch, [PRODUCT_TOTAL_SQL, WRONG_ANSWER])

    result = agent.ask(question, user)

    assert "retry" not in steps and result.status == "ok" and len(fake.calls) == 2 and len(tables.calls) == 1


@pytest.mark.parametrize("question, first, second, plural", [
    ("top 5 products of Allied Castings",
     {"columns": ["customer_name", "net_sales_inr"], "rows": [["Allied Castings Limited", Decimal("1.00")]],
      "truncated": False},
     {"columns": ["product_description", "net_sales_inr"], "rows": [[PRODUCT, Decimal("1.00")]], "truncated": False},
     "products"),
    ("which sales person sold the most coolant pumps",
     {"columns": ["net_sales_inr"], "rows": [[Decimal("1.00")]], "truncated": False},
     {"columns": ["sales_person_name", "net_sales_inr"], "rows": [["Rahul Verma", Decimal("1.00")]],
      "truncated": False},
     "sales people"),
    ("top states by sales in Oct 2026",
     {"columns": ["net_sales_inr"], "rows": [[Decimal("1.00")]], "truncated": False},
     {"columns": ["state", "net_sales_inr"], "rows": [["Karnataka", Decimal("1.00")]], "truncated": False},
     "states"),
    ("which countries do we export the coolant pump to",
     {"columns": ["product_description", "net_sales_inr"], "rows": [[PRODUCT, Decimal("1.00")]], "truncated": False},
     {"columns": ["country", "net_sales_inr"], "rows": [["Japan", Decimal("1.00")]], "truncated": False},
     "countries"),
])
def test_products_sales_people_states_and_countries_too(monkeypatch, tables, user, steps, question, first, second,
                                                       plural):
    tables.results = [first, second]
    fake = use_fake_ai(monkeypatch, [PRODUCT_TOTAL_SQL, PER_CUSTOMER_SQL, RIGHT_ANSWER])

    result = agent.ask(question, user)

    sent_back = f"That did not work: the question asks for a ranking / list of {plural}"
    assert fake.calls[1][-1]["content"].startswith(sent_back)
    assert steps[-2:] == ["run_sql", "explain"] and result.rows == second["rows"]


def test_a_follow_up_is_checked_with_its_written_out_question(monkeypatch, tables, user, steps):
    """'and its top custmers?' after a question about the pump: the written-out question asks for the customers."""
    tables.results = [PRODUCT_TOTAL, PER_CUSTOMER]
    fake = use_fake_ai(monkeypatch, [QUESTION, PRODUCT_TOTAL_SQL, PER_CUSTOMER_SQL, RIGHT_ANSWER])

    result = agent.ask("and its top custmers?", user, context=[earlier(f"{PRODUCT} sales")])

    assert result.understood_as == QUESTION
    assert fake.calls[2][-1]["content"].startswith(SENT_BACK)
    assert result.status == "ok" and result.rows == PER_CUSTOMER["rows"]


def test_a_follow_up_about_a_filter_is_not_sent_back(monkeypatch, tables, user, steps):
    tables.results = [PRODUCT_TOTAL]
    fake = use_fake_ai(monkeypatch, [f"{PRODUCT} sales in Oct 2026", PRODUCT_TOTAL_SQL, WRONG_ANSWER])

    result = agent.ask("and in Oct?", user, context=[earlier(f"{PRODUCT} sales")])

    assert "retry" not in steps and result.status == "ok" and len(fake.calls) == 3


def test_a_line_chart_retry_and_the_ranking_retry_are_never_both_used(monkeypatch, tables, user, steps):
    """A 1-row line chart of the top customers is sent back once for the periods; that try is not sent back
    again for the customers (one kept first answer at a time)."""
    one_row = {"columns": ["sales_month", "net_sales_inr"], "rows": [["Oct 2026", Decimal("1.00")]],
               "truncated": False}
    tables.results = [one_row, one_row]
    use_fake_ai(monkeypatch, [PRODUCT_TOTAL_SQL, PRODUCT_TOTAL_SQL, WRONG_ANSWER])

    result = agent.ask("top customers' sales as a line chart", user)

    assert steps.count("retry") == 1 and steps[-2:] == ["keep_first_answer", "explain"]
    assert result.status == "ok" and result.rows == one_row["rows"]


def test_graph_state_starts_unused():
    assert graph.start_state(agent.AskResult(text="x"))["entity_check_used"] is False
