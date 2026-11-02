"""Which ai_gold tables the SQL call shows (agent.schema_for_prompt) - fewer Groq tokens per question.

No Groq, no MySQL: the schema text and the document pieces are made up here.
The full check against every docs example and eval question is done offline with the real docs.
"""
import copy
from types import SimpleNamespace

import pytest

from portal.models import Question
from portal.rag import agent, warehouse

pytestmark = pytest.mark.django_db  # agent.ask() saves a Question

SCHEMA = "\n".join([
    "dim_calendar: date_id, full_date, nop_sales_month, financial_year",
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
    """The tables whose columns are in the schema text (not the 'Other ai_gold tables' line)."""
    return {line.split(":")[0] for line in text.splitlines()
            if ":" in line and not line.startswith("Other ai_gold tables")}


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
    assert others.startswith("Other ai_gold tables")
    for table in ("fact_sales_order_lines", "fact_stock_ledger", "dim_products", "load_log"):
        assert table in others
    assert len(text) < len(SCHEMA)


def test_schema_for_prompt_falls_back_to_the_full_schema(schema):
    text, full = agent.schema_for_prompt("Tell me something", [])
    assert full is True and text == SCHEMA


# ---------- a failed try shows the full schema ----------

class FakeGroq:
    """replies = what each call returns, in order; calls = the messages of every call."""

    def __init__(self, replies):
        self.replies, self.calls = list(replies), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(copy.deepcopy(kwargs["messages"]))
        reply = self.replies.pop(0)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=reply))])


SQL = "```sql\nSELECT ROUND(SUM(il.net_taxable_value), 2) AS net_sales_inr FROM fact_invoice_lines il\n```"


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
    fake = FakeGroq([SQL, SQL, "Net sales were 1."])
    monkeypatch.setattr(agent, "get_groq_client", lambda: fake)

    result = agent.ask("What were net sales in Aug 2026?", user)

    assert result.status == "ok" and result.tries == 2
    first_request = fake.calls[0][1]["content"]
    assert "fact_stock_ledger: " not in first_request          # try 1: only some tables
    retry_message = fake.calls[1][-1]["content"]
    assert "The full ai_gold schema" in retry_message and "fact_stock_ledger: " in retry_message
    assert Question.objects.count() == 1
