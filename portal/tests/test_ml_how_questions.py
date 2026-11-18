"""Questions about HOW this app's ML works get the general answer with the app's ML facts; its RESULTS stay data.

18-Nov, real chat: "is that trained for 12 months?" (after a forecast answer) went the data way - the AI wrote
SELECT horizon_months, COUNT(*) AS forecast_count FROM ml_sales_forecast GROUP BY horizon_months and explained the
counts confusingly. Now:
- SQL_SYSTEM_PROMPT part C and the router's 'general' say: how the app's ML works (training data / period, model,
  how accuracy or risk is worked out, input files) is GENERAL; its results (forecasts, accuracy, lists) are data.
- agent.about_app_ml also matches "how do you calculate risk" (any risk / churn word), so the general answer gets
  the "This app's ML" facts block (test_general_ml_facts.py).
- A follow-up written out by the rewrite step reaches the SQL writer, the router and the word check.

The AI is the fake one of test_agent.py; MySQL (warehouse.run_select) and the notes search are faked.
Run with:  python -m pytest -q portal/tests/test_ml_how_questions.py
"""
import pytest

from portal.rag import agent
from portal.tests.test_agent import ANSWER, GOOD_SQL, PDF_HITS, ROWS, mysql, use_fake_ai, use_pdf_hits  # noqa: F401
from portal.tests.test_chat import make_chat
from portal.lc.memory import ChatHistory
from portal.tests.test_general_ml_facts import ML_BLOCK, ML_ROWS, fake_ml_db, general_request
from portal.tests.test_graph import DATA_START, steps  # noqa: F401

pytestmark = pytest.mark.django_db  # agent.ask() saves a Question

QUESTION = "is that trained for 12 months?"
UNDERSTOOD = "Is the sales forecast model trained for 12 months?"
FORECAST_QUESTION = "What will our sales be for the next 3 months?"
FORECAST_SQL = "SELECT sales_month, forecast_inr, low_inr, high_inr, mape_pct, data_to FROM ml_sales_forecast"
FORECAST_ANSWER = "The forecast for Nov 2026 is INR 1,200,000.00."
TRAINED = ("No - the app's sales forecast is trained on the complete sales months in forecast_monthly_sales.csv "
           "and forecasts 3 sales months.")


# ---------- the prompts ----------

def test_the_prompts_send_how_the_ml_works_to_general_and_its_results_to_data():
    assert ("Also GENERAL: how this app's ML works (training data / period, model, how accuracy or risk is worked "
            "out, input files) - its results (forecasts, accuracy, lists) are SQL.") in agent.SQL_SYSTEM_PROMPT
    general_line = next(line for line in agent.ROUTE_SYSTEM_PROMPT.splitlines() if line.startswith("- general:"))
    assert ("Also how this app's ML works (training data / period, model, how accuracy or risk is worked out, "
            "input files) - its results (forecasts, lists, scores) are data.") in general_line


# ---------- the word check that adds the ML facts block ----------

@pytest.mark.parametrize("question, about_ml", [
    (QUESTION, True),
    (UNDERSTOOD, True),
    ("how was the model trained", True),
    ("how do you calculate risk", True),
    ("how is the churn risk worked out", True),
    ("which input files does it use", True),
    ("how is accuracy measured", True),
    ("how many months can it forecast", True),
    ("what is the forecast horizon", True),
    ("what is the capital of France", False),
    ("what is GST", False),
    ("who are you", False),
    ("hello", False),
])
def test_the_word_check_matches_the_how_questions(question, about_ml):
    assert agent.about_app_ml(question) is about_ml


# ---------- the AI chose GENERAL: the general answer with the ML facts, no SQL ----------

def test_the_18_nov_question_with_the_sql_writers_general_gets_the_ml_facts(monkeypatch, mysql, user, steps):
    calls = fake_ml_db(monkeypatch, ML_ROWS)
    fake = use_fake_ai(monkeypatch, ["GENERAL", TRAINED])

    result = agent.ask(QUESTION, user)

    assert steps == DATA_START + ["write_sql", "general_answer"]
    assert result.status == "general" and result.answer == TRAINED and result.sql == ""
    assert general_request(fake) == f"{QUESTION}\n\n{ML_BLOCK}"
    assert len(calls) == 1 and "ml_run_log" in calls[0]                 # the facts query only, no SQL of the AI ran
    assert fake.calls[-1][0]["content"] == agent.GENERAL_SYSTEM_PROMPT


def test_the_routers_general_does_the_same(monkeypatch, mysql, user, steps):
    use_pdf_hits(monkeypatch, PDF_HITS)  # the router runs only when a PDF piece scores high enough
    calls = fake_ml_db(monkeypatch, ML_ROWS)
    fake = use_fake_ai(monkeypatch, ["general", TRAINED])

    result = agent.ask("how do you calculate risk", user)

    assert steps == ["load_memories", "route", "general_answer"]
    assert result.status == "general" and result.answer == TRAINED
    assert general_request(fake) == f"how do you calculate risk\n\n{ML_BLOCK}"
    assert len(calls) == 1                                               # the facts query only


# ---------- a follow-up: the rewritten question reaches the decision and the word check ----------

def forecast_chat(user):
    return make_chat(user, FORECAST_QUESTION, sql=FORECAST_SQL, answer=FORECAST_ANSWER)


def test_the_follow_up_is_written_out_and_reaches_the_sql_writer_and_the_facts(monkeypatch, mysql, user, steps):
    calls = fake_ml_db(monkeypatch, ML_ROWS)
    fake = use_fake_ai(monkeypatch, [UNDERSTOOD, "GENERAL", TRAINED])

    result = agent.ask(QUESTION, user, context=ChatHistory.for_chat(forecast_chat(user)))

    assert steps == ["load_memories", "rewrite"] + DATA_START[1:] + ["write_sql", "general_answer"]
    assert result.status == "general" and result.understood_as == UNDERSTOOD
    assert FORECAST_QUESTION in fake.calls[0][-1]["content"]             # the rewrite saw the forecast question
    assert f"(Written out in full: {UNDERSTOOD})" in fake.calls[1][-1]["content"]   # the SQL writer decided on it
    assert general_request(fake).startswith(f"{QUESTION}\n(Understood as: {UNDERSTOOD})")
    assert ML_BLOCK in general_request(fake) and len(calls) == 1


def test_the_router_decides_on_the_written_out_follow_up(monkeypatch, mysql, user, steps):
    use_pdf_hits(monkeypatch, PDF_HITS)
    fake_ml_db(monkeypatch, ML_ROWS)
    fake = use_fake_ai(monkeypatch, [UNDERSTOOD, "general", TRAINED])

    result = agent.ask(QUESTION, user, context=ChatHistory.for_chat(forecast_chat(user)))

    assert steps == ["load_memories", "rewrite", "route", "general_answer"]
    assert f"Question: {UNDERSTOOD}" in fake.calls[1][-1]["content"]     # the router saw the written-out question
    assert result.status == "general" and ML_BLOCK in general_request(fake)


# ---------- the ML results stay the data way ----------

@pytest.mark.parametrize("question", [
    "what will our sales be next month",
    "what accuracy did the Holt-Winters model achieve and what are its forecast values",
])
def test_a_results_question_with_sql_still_goes_the_data_way(monkeypatch, mysql, user, steps, question):
    mysql.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [GOOD_SQL, ANSWER])

    result = agent.ask(question, user)

    assert steps == DATA_START + ["write_sql", "check_sql", "run_sql", "explain"]
    assert result.status == "ok" and result.answer == ANSWER and len(mysql.calls) == 1
    assert all(call[0]["content"] != agent.GENERAL_SYSTEM_PROMPT for call in fake.calls)
