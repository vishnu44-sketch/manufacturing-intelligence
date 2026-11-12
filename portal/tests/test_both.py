"""The router's third choice 'both' (a question about the data AND the company documents) and the token savings.

'both': the data path runs with every rule as before, and the answer step also gets the closest PDF pieces, so
ONE answer covers both parts; when the data part gives no answer, the documents part is still answered.
A pure data question and a pure documents question keep exactly the prompts they had (checked here).
Token savings: the same information in fewer tokens - the SQL on one line for the answer step, the notes' example
SQL without indentation, a retry with only the tables the first try did not see.
The AI is test_agent's fake; MySQL, the notes and the PDF search are faked. No AI call, no database outside the tests.
Run with:  python -m pytest -q portal/tests/test_both.py
"""
import re

import pytest
import sqlglot
from django.utils import timezone

from portal import services
from portal.lc import graph
from portal.models import Question
from portal.rag import agent, warehouse
from portal.tests.test_agent import (ANSWER, DOC_ANSWER, DOC_QUESTION, GOOD_SQL, HITS, PDF_HITS, ROWS,  # noqa: F401
                                     mysql, use_fake_ai, use_pdf_hits)
from portal.tests.test_graph import steps  # noqa: F401
from portal.tests.test_schema_select import SCHEMA, schema  # noqa: F401

pytestmark = pytest.mark.django_db  # agent.ask() saves a Question

BOTH_QUESTION = ("Top 3 export customers by net sales in FY 2025-26, and what are the payment terms for export "
                 "customers?")
TERMS_HITS = [
    {"text": "1. Payment terms\nCustomer type\nPayment terms\nExport customers\n30% advance, 70% against shipping\n"
             "documents", "source": "sales_terms_and_discount_policy.pdf", "title": "Sales Terms and Discount Policy",
     "page": 1, "score": 0.703},
    {"text": "4. Discount policy\nUp to 5%\nSales person", "source": "sales_terms_and_discount_policy.pdf",
     "title": "Sales Terms and Discount Policy", "page": 2, "score": 0.651},
]
BOTH_ANSWER = ("In FY 2025-26 Aurora Fluid Power Limited had the highest net sales. Export customers pay 30% in "
               "advance and 70% against the shipping documents (Sales Terms and Discount Policy, page 1).")
TERMS_ANSWER = ("Export customers pay 30% in advance and 70% against the shipping documents (Sales Terms and "
                "Discount Policy, page 1).")
DATA_PATH = ["load_memories", "route", "search_notes", "pick_schema", "write_sql"]


# ---------- the router ----------

@pytest.mark.parametrize("reply, route", [
    ("both", "both"), ("Both.", "both"), ("BOTH", "both"), ("<think>needs the data and the terms</think>\nboth", "both"),
    ("documents", "documents"), ("Document", "documents"), ("data", "data"), ("", "data"), ("maybe both", "data"),
])
def test_the_router_reply_is_read_as_data_documents_or_both(reply, route):
    assert agent.read_route_reply(reply) == route


def test_the_router_prompt_offers_both_and_unclear_stays_data():
    assert "- both: the data AND the documents in one question" in agent.ROUTE_SYSTEM_PROMPT
    assert agent.ROUTE_SYSTEM_PROMPT.endswith("Reply with one word only: data, documents or both. When unsure, reply data.")
    assert agent.ROUTE_REQUEST.endswith("Your reply (data, documents or both):")


# ---------- a question about the data AND the documents ----------

def test_a_both_question_answers_the_data_and_the_documents_in_one_answer(monkeypatch, mysql, user, steps):
    use_pdf_hits(monkeypatch, TERMS_HITS)
    mysql.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [("both", 300), (GOOD_SQL, 3000), (BOTH_ANSWER, 900)])

    result = agent.ask(BOTH_QUESTION, user)

    assert steps == DATA_PATH + ["check_sql", "run_sql", "explain"]
    assert result.status == "ok" and result.answer == BOTH_ANSWER and result.rows == ROWS["rows"] and result.sql
    assert len(fake.calls) == 3                                     # router, SQL, ONE answer (no documents call)
    sql_request = fake.calls[1][1]["content"]
    assert sql_request.endswith(f"Question: {BOTH_QUESTION}{agent.SQL_BOTH_NOTE}")
    answer_system, answer_request = (m["content"] for m in fake.calls[2])
    assert answer_system == agent.EXPLAIN_SYSTEM_PROMPT
    assert "Aurora Fluid Power Limited | 1,730,000.00" in answer_request                       # the rows ...
    assert "\n\nFrom the company documents (the pieces closest to the question" in answer_request  # ... and the PDFs
    assert "[1] Sales Terms and Discount Policy, page 1\n1. Payment terms" in answer_request
    assert answer_request.index("1,730,000.00") < answer_request.index("From the company documents")
    assert [s["kind"] for s in result.sources] == ["example", "rule", "pdf", "pdf"]           # notes + PDF pages
    assert result.sources[2]["heading"] == "Sales Terms and Discount Policy, page 1"
    saved = Question.objects.get()
    assert saved.status == "ok" and saved.rows_count == 2 and saved.sql
    assert [s["kind"] for s in saved.sources] == ["example", "rule", "pdf", "pdf"]
    assert result.tokens_text == "Tokens used: 4,200 (SQL 3,300 + answer 900)"                # SQL, not 'route'
    assert services.token_notice(saved).startswith("This question used 4,200 tokens (SQL 3,300 + answer 900)")


def test_a_both_question_whose_data_part_has_no_data_still_answers_the_documents_part(monkeypatch, mysql, user, steps):
    use_pdf_hits(monkeypatch, TERMS_HITS)
    fake = use_fake_ai(monkeypatch, ["both", "NO_DATA: export customers are not marked in the NOP data",
                                     TERMS_ANSWER])

    result = agent.ask(BOTH_QUESTION, user)

    assert steps == DATA_PATH + ["documents_part"]
    assert result.status == "docs" and mysql.calls == []
    assert result.answer == (TERMS_ANSWER + " About the data part of your question: The NOP data does not have "
                                            "this: export customers are not marked in the NOP data.")
    docs_system, docs_request = (m["content"] for m in fake.calls[2])
    assert docs_system == agent.DOCS_SYSTEM_PROMPT
    assert docs_request.endswith(f"Question: {BOTH_QUESTION}{agent.DOCS_PART_NOTE}")
    assert [s["kind"] for s in result.sources] == ["example", "rule", "pdf", "pdf"]
    assert Question.objects.get().status == "docs"


def test_a_both_question_whose_sql_fails_three_times_still_answers_the_documents_part(monkeypatch, mysql, user, steps):
    use_pdf_hits(monkeypatch, TERMS_HITS)
    mysql.results = [warehouse.QueryError("(1054) Unknown column 'il.amount'")] * agent.MAX_TRIES
    use_fake_ai(monkeypatch, ["both"] + [GOOD_SQL] * agent.MAX_TRIES + [TERMS_ANSWER])

    result = agent.ask(BOTH_QUESTION, user)

    assert steps[-2:] == ["failed", "documents_part"]
    assert result.status == "docs" and result.answer.startswith(TERMS_ANSWER)
    assert result.answer.endswith(f"About the data part of your question: {agent.FAILED_ANSWER}")
    assert result.error.startswith(f"{agent.MAX_TRIES} tries failed")               # kept for the admin


def test_a_both_question_with_a_name_that_matches_nothing_keeps_its_sql(monkeypatch, mysql, user, steps):
    use_pdf_hits(monkeypatch, TERMS_HITS)
    mysql.results = [{"columns": ["customer_name", "net_sales_inr"], "rows": [], "truncated": False}]
    not_found = 'No customer with "Zylo" in its name was found in the data.'
    monkeypatch.setattr(agent, "name_search_notes", lambda result, allowed: (not_found, []))
    use_fake_ai(monkeypatch, ["both", GOOD_SQL, TERMS_ANSWER])

    result = agent.ask("Sales of Zylo and the payment terms for export customers?", user)

    assert steps[-2:] == ["check_names", "documents_part"]
    assert result.status == "ok" and result.sql
    assert result.answer == f"{TERMS_ANSWER} About the data part of your question: {not_found}"


def test_a_both_question_the_documents_cannot_answer_keeps_the_data_answer(monkeypatch, mysql, user):
    use_pdf_hits(monkeypatch, TERMS_HITS)
    use_fake_ai(monkeypatch, ["both", "NO_DATA: payments are not in the NOP data",
                              "NOT_IN_DOCUMENTS: the documents do not give it"])

    result = agent.ask(BOTH_QUESTION, user)

    assert result.status == "nodata"
    assert result.answer == "The NOP data does not have this: payments are not in the NOP data."


# ---------- a pure data / documents question: exactly the prompts it had ----------

def test_a_data_question_gets_the_same_prompts_as_before(monkeypatch, mysql, user):
    """No PDF piece scores high enough: no router call, and nothing of 'both' reaches the SQL or answer request."""
    mysql.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [GOOD_SQL, ANSWER])
    question = "Top customers in Aug 2026?"

    result = agent.ask(question, user)

    schema, _ = agent.schema_for_prompt(question, HITS)
    assert fake.calls[0] == [
        {"role": "system", "content": agent.SQL_SYSTEM_PROMPT},
        {"role": "user", "content": agent.SQL_REQUEST.format(
            schema=schema, count=2, documents="\n\n---\n\n".join(h["text"] for h in HITS),
            today=timezone.localdate().strftime("%d-%b-%Y (%A)"), preferences="", earlier="", question=question)}]
    values = agent.explain_values(result, agent.ROWS_FOR_ANSWER)
    assert values["documents"] == ""
    old_template = agent.EXPLAIN_REQUEST.replace("{documents}", "")      # the answer request before 'both'
    assert fake.calls[1] == [{"role": "system", "content": agent.EXPLAIN_SYSTEM_PROMPT},
                             {"role": "user", "content": old_template.format(**values)}]
    everything = str(fake.calls)
    assert "From the company documents" not in everything and "answered from the company documents" not in everything


def test_a_data_question_the_router_sends_to_the_data_gets_no_documents(monkeypatch, mysql, user):
    use_pdf_hits(monkeypatch, PDF_HITS)
    mysql.results = [ROWS]
    fake = use_fake_ai(monkeypatch, ["data", GOOD_SQL, ANSWER])

    result = agent.ask("Top customers in Aug 2026?", user)

    assert result.status == "ok" and [s["kind"] for s in result.sources] == ["example", "rule"]
    assert fake.calls[1][1]["content"].endswith("Question: Top customers in Aug 2026?")
    assert "From the company documents" not in fake.calls[2][1]["content"]


def test_a_documents_question_gets_the_same_prompts_as_before(monkeypatch, mysql, user):
    use_pdf_hits(monkeypatch, PDF_HITS)
    fake = use_fake_ai(monkeypatch, ["documents", DOC_ANSWER])

    result = agent.ask(DOC_QUESTION, user)

    assert result.status == "docs" and result.answer == DOC_ANSWER
    assert fake.calls[1] == [
        {"role": "system", "content": agent.DOCS_SYSTEM_PROMPT},
        {"role": "user", "content": agent.DOCS_REQUEST.format(
            documents="\n\n---\n\n".join(f"[{n}] {h['title']}, page {h['page']}\n{h['text']}"
                                         for n, h in enumerate(PDF_HITS, start=1)),
            question=DOC_QUESTION, understood="", preferences="")}]
    assert agent.from_documents(result.sources)


def test_the_graph_starts_every_question_on_the_data_route():
    assert graph.start_state(agent.AskResult(text="q"))["route"] == "data"


# ---------- fewer tokens, the same information ----------

PRETTY_SQL = """SELECT
  cu.customer_name,
  COALESCE(cu.state, 'Not  given') AS state,
  ROUND(SUM(il.net_taxable_value), 2) AS net_sales_inr
FROM fact_invoice_lines AS il
JOIN dim_customers AS cu
  ON cu.customer_id = il.customer_id
WHERE
  il.sale_type = 'Export' AND cu.customer_name LIKE '%Tech  Industries%'
GROUP BY
  cu.customer_id,
  cu.customer_name
ORDER BY
  net_sales_inr DESC
LIMIT 3"""


def test_the_answer_step_gets_the_same_sql_on_one_line():
    compact = agent.compact_sql(PRETTY_SQL)
    assert "\n" not in compact and "  ON" not in compact
    assert sqlglot.parse_one(compact, read="mysql") == sqlglot.parse_one(PRETTY_SQL, read="mysql")   # the same query
    assert "'Not  given'" in compact and "'%Tech  Industries%'" in compact      # quoted text exactly as it was
    assert len(compact) < len(PRETTY_SQL)
    commented = "SELECT 1 -- one\nFROM dim_calendar"
    assert agent.compact_sql(commented) == commented                             # a comment: left as it was
    assert agent.limit_note(agent.AskResult(text="q", sql=PRETTY_SQL, rows=[[1]] * 3)) != ""  # rules read result.sql


def test_the_answer_request_has_the_compact_sql(monkeypatch, mysql, user):
    mysql.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [GOOD_SQL, ANSWER])

    result = agent.ask("Top customers in Aug 2026?", user)

    request = fake.calls[1][1]["content"]
    sent = request.split("SQL that was run:\n", 1)[1].split("\n", 1)[0]
    assert sqlglot.parse_one(sent, read="mysql") == sqlglot.parse_one(result.sql, read="mysql")


NOTE = """Example question with its SQL: Q: Who were the top 5 customers by invoice value in Aug 2026?

- a rule line
  - an indented rule line (kept)

```sql
SELECT cu.customer_name,
       ROUND(SUM(il.net_taxable_value), 2) AS invoice_value_inr
FROM fact_invoice_lines il
JOIN dim_customers cu ON cu.customer_id = il.customer_id
WHERE c.nop_sales_month = 'Aug  2026'
LIMIT 5;
```

Why: a month name means the NOP sales month."""


def test_the_notes_example_sql_loses_only_its_indentation():
    compact = agent.compact_notes(NOTE)
    sql_of = lambda text: re.search(r"```sql\n(.*?)```", text, re.S).group(1)  # noqa: E731
    assert sqlglot.parse_one(sql_of(compact), read="mysql") == sqlglot.parse_one(sql_of(NOTE), read="mysql")
    assert [line.strip() for line in compact.splitlines()] == [line.strip() for line in NOTE.splitlines()]
    assert "\n       ROUND" not in compact and "\nROUND(SUM" in compact
    assert "\n  - an indented rule line (kept)" in compact                       # outside the SQL: exactly as it was
    assert compact.split("```sql")[0] == NOTE.split("```sql")[0] and compact.split("```")[-1] == NOTE.split("```")[-1]


def test_a_retry_gets_the_tables_it_did_not_see_and_together_they_are_the_whole_schema(monkeypatch, schema, user):
    """22-Oct: a retry with the whole schema again was 8,071 tokens (over Groq's 8,000 a minute)."""
    results = [warehouse.QueryError("(1054) Unknown column 'il.amount' in 'field list'"),
               {"columns": ["net_sales_inr"], "rows": [[1]], "truncated": False}]

    def run_select(sql):
        result = results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result
    sql = "```sql\nSELECT ROUND(SUM(il.net_taxable_value), 2) AS net_sales_inr FROM fact_invoice_lines il\n```"
    monkeypatch.setattr(agent, "search", lambda question, top_k=5: [])
    monkeypatch.setattr(warehouse, "allowed_tables", lambda: {line.split(":")[0] for line in SCHEMA.splitlines()})
    monkeypatch.setattr(warehouse, "run_select", run_select)
    fake = use_fake_ai(monkeypatch, [sql, sql, "Net sales were 1."])

    assert agent.ask("What were net sales in Aug 2026?", user).tries == 2

    first = fake.calls[1][1]["content"].split("ai_gold schema (table: columns):\n", 1)[1].split("\n\nDocuments", 1)[0]
    retry = fake.calls[1][-1]["content"].split("with them you have every table and column):\n", 1)[1]
    first_tables = [line for line in first.splitlines() if not line.startswith("Other ai_gold tables")]
    assert sorted(first_tables + retry.splitlines()) == sorted(SCHEMA.splitlines())   # every table, once
    assert not set(first_tables) & set(retry.splitlines())
