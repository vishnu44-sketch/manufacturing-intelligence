"""Which ss_gold tables the SQL call shows (agent.schema_for_prompt) - fewer Groq tokens per question.

No Groq, no MySQL: the schema text and the document pieces are made up here (the AI is test_agent's fake).
The full check against every docs example and eval question is done offline with the real docs.
"""
import re

import pytest

from portal.lc.docs import load_docs
from portal.models import Question
from portal.rag import agent, warehouse
from portal.tests.test_agent import use_fake_ai
from portal.tests.test_ml_questions import ALLOWED, DOCS, ML_TABLES

pytestmark = pytest.mark.django_db  # agent.ask() saves a Question

SCHEMA = "\n".join([
    "dim_calendar: date_id, full_date, sales_month, financial_year",
    "dim_customers: customer_id, customer_name",
    "dim_fx_rates: fx_rate_id, rate_month, exchange_rate",
    "dim_products: product_id, product_code, product_category",
    "dim_sales_people: sales_person_id, sales_person_name",
    "dim_stock_movement_types: movement_type_id, movement_type",
    "dim_tax_codes: tax_code_id, tax_code",
    "fact_invoice_lines: invoice_line_id, invoice_date_id, customer_id, product_id, net_taxable_value",
    "fact_sales_order_lines: sales_order_line_id, order_date_id, customer_id, status, total_amount",
    "fact_stock_ledger: stock_ledger_id, report_date, product_id, movement_type_id, cumulative_value",
    "load_log: load_log_id, run_id, table_name, loaded_at",
])
ALL = {line.split(":")[0] for line in SCHEMA.splitlines()}
SMALL = set(agent.ALWAYS_SHOWN)


def shown_tables(text):
    """The tables whose columns are in the schema text (not the 'Other ss_gold tables' line)."""
    return {line.split(":")[0] for line in text.splitlines()
            if ":" in line and not line.startswith("Other ss_gold tables")}


@pytest.fixture
def schema(monkeypatch):
    monkeypatch.setattr(warehouse, "schema_text", lambda: SCHEMA)


# ---------- which tables ----------

@pytest.mark.parametrize("question, expected", [
    ("What were net sales in Aug 2026?", {"fact_invoice_lines", "dim_customers"}),
    ("How many sales orders are open?", {"fact_sales_order_lines", "fact_invoice_lines", "dim_customers"}),
    ("whats our backlog", {"fact_sales_order_lines", "dim_customers"}),
    ("What is our stock value now?", {"fact_stock_ledger"}),
    ("Top 5 products by sales value in Nov 2026?", {"fact_invoice_lines", "dim_customers", "dim_products"}),
    ("Average selling price of FG00040?", {"fact_invoice_lines", "dim_customers", "dim_products"}),
    ("When was the data last loaded?", {"load_log"}),
])
def test_the_question_words_pick_the_tables(question, expected):
    chosen = agent.tables_for_question(question, [], ALL)
    assert chosen == SMALL | expected


def test_tables_of_retrieved_examples_and_dictionary_pieces_are_added():
    hits = [
        {"kind": "example", "heading": "Q: Top items in stock?",
         "text": "Example ...\n```sql\nSELECT p.product_code FROM fact_stock_ledger sl "
                 "JOIN dim_products p ON p.product_id = sl.product_id\n```\nExpected: ..."},
        {"kind": "table", "heading": "dim_customers - what one row is", "text": "... fact_invoice_lines ..."},
        {"kind": "rule", "heading": "Sales amounts", "text": "Use fact_sales_order_lines for orders."},
    ]
    chosen = agent.tables_for_question("which items are worth the most", hits, ALL)
    # the example's SQL tables + the dictionary piece's own table; a rule's passing mention is not used
    assert chosen == SMALL | {"fact_stock_ledger", "dim_products", "dim_customers"}


def test_unsure_questions_get_every_table():
    assert agent.tables_for_question("What is the capital of France?", [], ALL) is None


# ---------- the text that goes to the AI ----------

def test_schema_for_prompt_shows_some_tables_and_names_the_others(schema):
    text, full = agent.schema_for_prompt("What were net sales in Aug 2026?", [])
    assert full is False
    assert shown_tables(text) == SMALL | {"fact_invoice_lines", "dim_customers"}
    others = text.splitlines()[-1]
    assert others.startswith("Other ss_gold tables")
    for table in ("fact_sales_order_lines", "fact_stock_ledger", "dim_products", "load_log"):
        assert table in others
    assert len(text) < len(SCHEMA)


def test_schema_for_prompt_falls_back_to_the_full_schema(schema):
    text, full = agent.schema_for_prompt("Tell me something", [])
    assert full is True and text == SCHEMA


# ---------- a failed try shows the full schema ----------

SQL ="```sql\nSELECT ROUND(SUM(il.net_taxable_value), 2) AS net_sales_inr FROM fact_invoice_lines il\n```"


def test_the_retry_after_a_failed_try_shows_every_table(monkeypatch, schema, user):
    results = [warehouse.QueryError("(1054) Unknown column 'il.amount' in 'field list'"),
               {"columns": ["net_sales_inr"], "rows": [[1]], "truncated": False}]

    def run_select(sql):
        result = results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(agent, "search", lambda question, top_k=5: [])
    monkeypatch.setattr(warehouse, "allowed_tables", lambda: ALL)
    monkeypatch.setattr(warehouse, "run_select", run_select)
    fake = use_fake_ai(monkeypatch, [SQL, SQL, "Net sales were 1."])

    result = agent.ask("What were net sales in Aug 2026?", user)

    assert result.status == "ok" and result.tries == 2
    first_request = fake.calls[0][1]["content"]
    assert "fact_stock_ledger: " not in first_request          # try 1: only some tables
    retry_message = fake.calls[1][-1]["content"]
    assert "The rest of the ss_gold schema" in retry_message and "fact_stock_ledger: " in retry_message
    assert Question.objects.count() == 1


# ---------- the words that pick each ml_ table (18-Nov: "which products customers buy together?") ----------
# On ML Insights the backup model answered "which products customers buy together?" with the top customers by
# orders. The words of each ml_ table now cover more ways (and typos) of asking, and stay narrow enough that a
# normal question picks no ml_ table.

def ml_picked(question):
    """The ml_ tables the question's words alone pick (ml_run_log left out: 'model' and 'ML' pick it)."""
    return (agent.tables_for_question(question, [], ALLOWED) or set()) & (ML_TABLES - {"ml_run_log"})


ML_VARIANTS = {
    "ml_product_pairs": [
        "which products customers buy together?", "what do customers usually buy together", "products bought together",
        "items purchased together", "what is ordered together most", "products sold together",
        "what goes together with FG00040", "products often bought with TX-675", "frequently bought items",
        "top product pairs", "which items are paired", "product combinations", "bundles we could offer",
        "cross-sell ideas for coolant pumps", "cross sell suggestions", "market basket analysis",
        "what do customers buy along with GCI pumps", "which products buy togather", "what sells togther",
        # 18-Nov: the names of the method
        "association rules of our products", "associative rule mining on the orders", "association mining",
        "rule mining for products", "run apriori on the sales orders", "fp-growth results", "FP growth itemsets",
        "frequent itemsets", "order baskets", "basket analysis", "frequently bought products",
        "items bought together"],
    "ml_customer_risk": [
        "which customers might stop buying", "customers likely to leave", "who will stop ordering from us",
        "churn risk", "customers at risk", "risk score of Allied Castings", "are we losing customers",
        "customers going inactive soon", "which clients may stop purchasing", "customer attrition",
        "customers about to leave", "chrun list"],
    "ml_customer_segments": [
        "what customer groups do we have", "customer segments", "customer segmentation", "types of customers",
        "kinds of customers we have", "customer clusters", "RFM groups", "segment our customers",
        "which customers are occasional buyers", "groups of customers by buying"],
    "ml_invoice_alerts": [
        "any unusual invoices", "suspicious invoices", "odd prices last month", "strange invoices", "invoice outliers",
        "anomalies in invoices", "anomalous prices", "invoice alerts", "which invoices to check",
        "invoices that need review", "abnormal credit notes", "unusal invoices", "suspicous invoice lines",
        "any red flags in billing"],
    "ml_stock_runout": [
        "which items will run out of stock soon", "items running out", "stock out soon", "stockouts next month",
        "what will be out of stock soon", "days of stock left", "items to reorder", "what should we reorder",
        "when should we reorder FG00040", "how long will the stock last", "items runing out", "parts running low"],
    "ml_sales_forecast": [
        "sales forecast", "forcast for next month", "predict sales", "sales prediction", "sales projection",
        "next 6 months sales", "next year sales", "future sales", "estimate next quarter",
        "what will we sell next month", "expected sales in Dec 2026", "sales outlook", "coming months sales"],
}


RULE_MINING_QUESTION = "which products in the order basket CSV dataset can be used for associative rule mining?"


def test_the_18_nov_questions_pick_the_product_pairs():
    assert ml_picked("which products customers buy together?") == {"ml_product_pairs"}
    assert ml_picked(RULE_MINING_QUESTION) == {"ml_product_pairs"}
    assert ml_picked("so what are the products whcih can get this type of associative") == {"ml_product_pairs"}


@pytest.mark.parametrize("table, question", [(table, question) for table, questions in ML_VARIANTS.items()
                                             for question in questions])
def test_each_way_of_asking_picks_its_ml_table(table, question):
    assert table in ml_picked(question)


@pytest.mark.parametrize("question", [
    "top customers last month", "sales by product", "stock value", "What is our stock value now?",
    "Top 5 products by sales value in Nov 2026?", "which customers stopped buying from us",
    "which customers did we lose last year", "sales by customer group", "net sales per customer group in FY 2026-27",
    "sales by customer type", "net sales by country segment", "How much did OEM and after-market customers buy?",
    "open sales orders", "which items have zero stock", "which items are below minimum inventory level",
    "sales along with freight", "invoices with GST in Aug 2026", "how many orders did we get last month",
    "credit notes this year", "what did Allied Castings buy in Aug 2026", "sales this month so far",
    "who bought the most last month", "stock movement in Oct 2026", "price of FG00040",
    "which customers bought from us in Jan 2026", "monthly sales trend", "how much did sales grow this year",
    "customers with orders overdue", "which products did customers order last month", "top items by quantity sold",
    "orders booked with delivery overdue", "which products are associated with Allied Castings",
    "rules for net sales", "how often did Allied Castings order in 2026",
])
def test_a_normal_question_picks_no_ml_table(question):
    assert ml_picked(question) == set()


EXAMPLES = [c for c in load_docs(DOCS) if c["kind"] == "example" and c["heading"].startswith("Q: ")]


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda example: example["heading"][3:60])
def test_every_docs_example_question_picks_the_ml_tables_of_its_sql(example):
    """docs/sql_examples.md: an ML example's question picks the ml_ tables its SQL uses; a normal example's
    question picks none (its words alone, without the notes)."""
    sql = example["text"].split("```sql", 1)[1].split("```", 1)[0]
    assert ml_picked(example["heading"][3:]) == set(re.findall(r"\bml_[a-z_]+", sql)) - {"ml_run_log"}


def test_the_docs_have_ml_and_normal_examples():
    with_ml = [e for e in EXAMPLES if "ml_" in e["text"].split("```sql", 1)[1].split("```", 1)[0]]
    assert len(with_ml) >= 9 and len(EXAMPLES) - len(with_ml) >= 30
