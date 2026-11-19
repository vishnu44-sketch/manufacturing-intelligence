"""The backup model answers an ML Insights question (18-Nov, question 124).

At 12:18 "what will our sales be for the next 6 months" on the ML Insights page ended with "The AI service returned
an error" after 1.5 s. The main model (openai/gpt-oss-120b) was over its daily limit, so the SQL call moved to the
backup model - but the backup's request (lc.calls.for_backup: 2 notes) still had ML mode's extras: every ml_ table's
columns and the ML notes. ~5,400 tokens + 1,000 for the reply (tiktoken o200k) is more than the backup's ~6,000 tokens
a minute: Groq refused it (413), and the smallest request too. The same question in the Assistant was answered.
Now an ML Insights request gets its own cut for the backup (graph.pick_schema -> LcRequest.backup):
- ONE note: the closest that names an ml_ table (agent.backup_ml_hits) - the ML example, rules or table piece;
- only the ml_ tables the question's words pick (agent.backup_ml_schema; ml_sales_forecast when none is);
- ML_MODE_NOTE stays after the question;
- after a 413 (the smallest request): the picked tables only, without the small always-shown tables.
The real request of question 124 for the backup: ~4,260 tokens + 1,000 (was ~5,420 + 1,000). The main model's
request is as before (every ml_ table, 5 notes).

The AI is the FAKE of test_agent.py (FakeAI behind LangChain): no Groq call. The notes are the real docs/ pieces.
Run with:  python -m pytest -q portal/tests/test_backup_ml_mode.py
"""
import pytest

from portal.lc import calls
from portal.lc.calls import LcRequest
from portal.lc.docs import load_docs
from portal.models import Question
from portal.rag import agent, warehouse
from portal.tests.test_agent import BACKUP, MAIN, daily_limit_error, mysql, use_fake_ai, with_backup  # noqa: F401
from portal.tests.test_backup_model import too_large_error
from portal.tests.test_ml_questions import (ALLOWED, DOCS, FORECAST_ANSWER, FORECAST_ROWS, FORECAST_SQL, ML_TABLES,
                                            TODAY)

pytestmark = pytest.mark.django_db  # agent.ask() saves a Question

QUESTION = "what will our sales be for the next 6 months"
# a schema about the real one's size: every table with 20 columns (the real ss_gold schema: 18 tables, ~1,200 tokens)
SCHEMA = "\n".join(f"{table}: {table}_key, " + ", ".join(f"column_{n}" for n in range(1, 21))
                   for table in sorted(ALLOWED))
# the 5 notes the real search sent for question 124 in ML mode, with the 'sales month' rule (no ml_ table) moved
# to the top: the backup must still get the closest ML note
HEADINGS = ["sales month - ", "Q: What are the sales forecasts for the next 3 months?",
            "Q: What will our total sales be in 2027?", "ML results (", "ml_sales_forecast - "]
CHARS_PER_TOKEN = 3.8      # a safe count: the real SQL request has 3.8 (the question part) - 4.1 (the rules)
                           # characters per o200k token
BACKUP_BUDGET = 5700       # the backup's request + its reply allowance, well under its ~6,000 tokens a minute


def real_notes():
    """The real docs/ pieces of HEADINGS, in that order, as the notes search gives them."""
    chunks = load_docs(DOCS)
    notes = [next(c for c in chunks if c["heading"].startswith(heading)) for heading in HEADINGS]
    return [{**note, "score": 0.9 - n / 10} for n, note in enumerate(notes)]


NOTES = real_notes()


@pytest.fixture
def ml_gold(monkeypatch, mysql):
    """The fake MySQL with every ss_gold table (the ml_ tables too), the real notes, today = 17-Nov-2026."""
    monkeypatch.setattr(warehouse, "allowed_tables", lambda: ALLOWED)
    monkeypatch.setattr(warehouse, "schema_text", lambda: SCHEMA)
    monkeypatch.setattr(agent, "search", lambda question, top_k=5: NOTES[:top_k])
    monkeypatch.setattr(agent, "today", lambda: TODAY)
    return mysql


def ml_columns_shown(request):
    """The ml_ tables whose columns a SQL request shows."""
    return {table for table in ML_TABLES if f"{table}: {table}_key" in request}


def tokens(call):
    """A safe count of the tokens of one call's messages (more than tiktoken o200k counts)."""
    return round(sum(len(message["content"]) for message in call) / CHARS_PER_TOKEN)


def forecast_reply():
    return f"```sql\n{FORECAST_SQL}\n```"


# ---------- the request cut for the backup ----------

def test_a_daily_limit_at_the_ml_sql_call_gives_the_backup_one_ml_note_and_the_picked_ml_table(
        monkeypatch, ml_gold, user, with_backup):
    ml_gold.results = [FORECAST_ROWS]
    fake = use_fake_ai(monkeypatch, [daily_limit_error(), (forecast_reply(), 3000), (FORECAST_ANSWER, 800)])

    result = agent.ask(QUESTION, user, mode="ml")

    assert result.status == "ok" and result.answer == FORECAST_ANSWER
    assert result.model == BACKUP and result.answered_by_backup
    assert fake.models == [MAIN, BACKUP, BACKUP]
    saved = Question.objects.get()
    assert saved.model == BACKUP and saved.status == "ok"
    main, backup = fake.calls[0], fake.calls[1]
    # the main model's ML-mode request is as before: every ml_ table, the 5 notes
    assert ml_columns_shown(main[-1]["content"]) == ML_TABLES
    assert "the 5 pieces" in main[-1]["content"] and "business rule: sales month" in main[-1]["content"]
    # the backup: only the ml_ table the question picks, one note - the closest ML one (not the 'sales month' rule)
    request = backup[-1]["content"]
    assert ml_columns_shown(request) == {"ml_sales_forecast"}
    assert "fact_invoice_lines: fact_invoice_lines_key" in request                  # 'sales': as in the Assistant
    assert "dim_calendar: dim_calendar_key" in request                              # the small tables stay
    assert "Other ss_gold tables" in request and "ml_customer_risk" in request      # the others are still named
    assert "the 1 pieces" in request and "Q: What are the sales forecasts for the next 3 months?" in request
    assert "business rule: sales month" not in request and "ML results (" not in request
    assert request.endswith(f"Question: {QUESTION}{agent.ML_MODE_NOTE}")
    assert backup[0]["content"] == agent.SQL_SYSTEM_PROMPT                          # the same rules
    # its size: well under the backup's tokens a minute, with the reply allowance
    assert fake.max_tokens[1] == agent.FALLBACK_MAX_TOKENS
    assert tokens(backup) + agent.FALLBACK_MAX_TOKENS <= BACKUP_BUDGET
    assert tokens(main) + agent.FALLBACK_MAX_TOKENS > BACKUP_BUDGET                 # the main one would not fit


def test_a_backup_ml_request_still_too_large_is_sent_with_the_picked_tables_only(monkeypatch, ml_gold, user,
                                                                                with_backup):
    ml_gold.results = [FORECAST_ROWS]
    fake = use_fake_ai(monkeypatch, [daily_limit_error(), too_large_error(), forecast_reply(), FORECAST_ANSWER])

    result = agent.ask(QUESTION, user, mode="ml")

    assert result.status == "ok" and result.model == BACKUP
    assert fake.models == [MAIN, BACKUP, BACKUP, BACKUP]
    cut, smallest = fake.calls[1][-1]["content"], fake.calls[2][-1]["content"]
    assert "dim_calendar: dim_calendar_key" in cut
    assert ml_columns_shown(smallest) == {"ml_sales_forecast"}
    assert "fact_invoice_lines: fact_invoice_lines_key" in smallest
    assert "dim_calendar: dim_calendar_key" not in smallest and "dim_calendar" in smallest  # named, no columns
    assert "the 1 pieces" in smallest and "Q: What are the sales forecasts for the next 3 months?" in smallest
    assert smallest.endswith(f"Question: {QUESTION}{agent.ML_MODE_NOTE}")
    assert tokens(fake.calls[2]) < tokens(fake.calls[1])


def test_the_assistant_backup_request_is_cut_as_before(monkeypatch, ml_gold, user, with_backup):
    """A question of the Assistant: no ML cut - the 2 closest notes, the schema as the main model's."""
    ml_gold.results = [FORECAST_ROWS]
    fake = use_fake_ai(monkeypatch, [daily_limit_error(), forecast_reply(), FORECAST_ANSWER])

    agent.ask(QUESTION, user)

    main, backup = fake.calls[0][-1]["content"], fake.calls[1][-1]["content"]
    assert "the 2 pieces" in backup and "business rule: sales month" in backup
    assert main.split("Documents (")[0] == backup.split("Documents (")[0]          # the same schema
    assert ml_columns_shown(backup) == {"ml_sales_forecast"} and agent.ML_MODE_NOTE not in backup


# ---------- the parts ----------

def test_the_backup_ml_schema_picks_the_ml_tables_of_the_question(monkeypatch):
    monkeypatch.setattr(warehouse, "schema_text", lambda: SCHEMA)

    def ml_shown(question, hits=()):
        return ml_columns_shown(agent.backup_ml_schema(question, list(hits)))

    assert ml_shown(QUESTION) == {"ml_sales_forecast"}
    assert ml_shown("which customers might stop buying from us") == {"ml_customer_risk"}
    assert ml_shown("any unusual invoices last month?") == {"ml_invoice_alerts"}
    assert ml_shown("Top customers in Aug 2026?") == {"ml_sales_forecast"}          # none picked: the forecast
    assert ml_shown("anything interesting?") == {"ml_sales_forecast"}               # unsure: never every table
    # the main model's ML-mode schema is unchanged: every ml_ table
    assert ml_columns_shown(agent.schema_for_prompt(QUESTION, [], ml_mode=True)[0]) == ML_TABLES


def test_the_backup_gets_the_closest_note_that_names_an_ml_table():
    assert agent.backup_ml_hits(NOTES) == [NOTES[1]]
    plain = [NOTES[0]]
    assert agent.backup_ml_hits(plain) == plain                                     # no ML note: the closest
    assert agent.backup_ml_hits([]) == []


# ---------- 18-Nov: "which products customers buy together?" ----------
# On ML Insights the backup answered it with the top customers by orders (fact_sales_order_lines), not the product
# pairs. Its one note must be the bought-together example (else a note naming ml_product_pairs), never another ML
# example such as 'might stop buying' that the search ranked higher, and its schema must show ml_product_pairs.

PAIRS_QUESTION = "which products customers buy together?"
PAIRS_EXAMPLE = "Q: Which products are bought together?"


def notes_of(*headings):
    """The real docs/ pieces whose headings start with these, in this order (closest first)."""
    chunks = load_docs(DOCS)
    notes = [next(c for c in chunks if c["heading"].startswith(heading)) for heading in headings]
    return [{**note, "score": 0.9 - n / 10} for n, note in enumerate(notes)]


def test_the_pairs_question_gives_the_backup_the_bought_together_example():
    # the 5 notes the real search sent for the 18-Nov question
    logged = notes_of(PAIRS_EXAMPLE, "ml_product_pairs - ", "Names in a question", "ml_customer_segments - ",
                      "Q: Which customers bought from us between Jan 2026")
    assert [n["heading"] for n in agent.backup_ml_hits(logged, PAIRS_QUESTION)] == [PAIRS_EXAMPLE]
    # other ML notes ranked higher: still the bought-together example
    harder = notes_of("Q: Which customers might stop buying from us?", "ml_customer_segments - ",
                      "Q: Which customers bought from us between Jan 2026", "ML results (", PAIRS_EXAMPLE)
    assert [n["heading"] for n in agent.backup_ml_hits(harder, PAIRS_QUESTION)] == [PAIRS_EXAMPLE]
    # no pairs example among the notes: the closest note that names ml_product_pairs (its table piece, the ML rules)
    no_example = notes_of("Q: Which customers might stop buying from us?", "ML results (", "ml_product_pairs - ")
    assert agent.backup_ml_hits(no_example, PAIRS_QUESTION) == [no_example[1]]
    # without the question (or a question that picks no ml_ table): the closest ML note, as before
    assert agent.backup_ml_hits(harder) == [harder[0]]
    assert agent.backup_ml_hits(harder, "anything interesting?") == [harder[0]]


RULE_MINING_QUESTION = "which products in the order basket CSV dataset can be used for associative rule mining?"


def test_the_rule_mining_question_gives_the_backup_the_pairs_example_and_table(monkeypatch):
    """18-Nov: answered with 102 raw basket rows instead of the bought-together results."""
    monkeypatch.setattr(warehouse, "schema_text", lambda: SCHEMA)
    harder = notes_of("Q: Which customers might stop buying from us?", "Q: How many sales orders are open",
                      "ML results (", PAIRS_EXAMPLE, "ml_product_pairs - ")
    note = agent.backup_ml_hits(harder, RULE_MINING_QUESTION)
    assert [n["heading"] for n in note] == [PAIRS_EXAMPLE]
    assert ml_columns_shown(agent.backup_ml_schema(RULE_MINING_QUESTION, note)) == {"ml_product_pairs"}


def test_the_pairs_question_shows_the_backup_the_pairs_table(monkeypatch):
    monkeypatch.setattr(warehouse, "schema_text", lambda: SCHEMA)
    note = notes_of(PAIRS_EXAMPLE)
    assert ml_columns_shown(agent.backup_ml_schema(PAIRS_QUESTION, note)) == {"ml_product_pairs"}
    assert ml_columns_shown(agent.backup_ml_schema(PAIRS_QUESTION, note, smallest=True)) == {"ml_product_pairs"}
    assert ml_columns_shown(agent.backup_ml_schema(PAIRS_QUESTION, [])) == {"ml_product_pairs"}  # its words alone


PAIRS_SQL = ("SELECT pp.product_a_code, pp.product_b_code, pp.orders_together, pp.lift FROM ml_product_pairs pp "
             "ORDER BY pp.orders_together DESC, pp.lift DESC LIMIT 10")
PAIRS_ROWS = {"columns": ["product_a_code", "product_b_code", "orders_together", "lift"],
              "rows": [["FG00580", "FG01116", 146, 11.77]], "truncated": False}
PAIRS_ANSWER = "FG00580 and FG01116 are bought together most often: on 146 sales orders."


def test_the_backup_request_of_the_pairs_question(monkeypatch, ml_gold, user, with_backup):
    ml_gold.results = [PAIRS_ROWS]
    harder = notes_of("Q: Which customers might stop buying from us?", "ml_customer_segments - ",
                      "Q: Which customers bought from us between Jan 2026", "ML results (", PAIRS_EXAMPLE)
    monkeypatch.setattr(agent, "search", lambda question, top_k=5: harder[:top_k])
    # (the pairs reply twice: the result check of the ranked customers may still send the first one back - only the
    # backup's first request is checked here)
    pairs_reply = (f"```sql\n{PAIRS_SQL}\n```", 3000)
    fake = use_fake_ai(monkeypatch, [daily_limit_error(), pairs_reply, pairs_reply, (PAIRS_ANSWER, 800)])

    result = agent.ask(PAIRS_QUESTION, user, mode="ml")

    assert result.model == BACKUP and fake.models[:2] == [MAIN, BACKUP]
    request = fake.calls[1][-1]["content"]
    assert ml_columns_shown(request) == {"ml_product_pairs"}
    assert "the 1 pieces" in request and PAIRS_EXAMPLE in request
    assert "might stop buying" not in request.split("Question:")[0]
    assert tokens(fake.calls[1]) + agent.FALLBACK_MAX_TOKENS <= BACKUP_BUDGET


def test_for_backup_swaps_in_the_ml_values():
    values = {"schema": "all", "count": 5, "documents": "a\n\n---\n\nb\n\n---\n\nc", "today": "t",
              "earlier": "E", "question": "q"}
    backup = {"documents": "ml note", "count": 1, "schema": "picked", "smallest_schema": "picked only"}
    request = LcRequest("sql", values, backup=backup)

    cut, smallest = calls.for_backup(request), calls.for_backup(request, smallest=True)

    assert (cut.values["documents"], cut.values["count"], cut.values["schema"], cut.values["earlier"]) == \
        ("ml note", 1, "picked", "E")
    assert (smallest.values["schema"], smallest.values["earlier"]) == ("picked only", "")
    assert request.values == values                                                 # the main model's: unchanged
