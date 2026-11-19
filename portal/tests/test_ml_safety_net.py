"""A NO_DATA about how this app's own ML works becomes the general answer with the ML facts (a safety net).

18-Nov, answered by the backup model: "which model you used for forecast and how accurate it is?" got DATA NOT
AVAILABLE: "How the forecast model works ... is not in the SS Manufacturing data." The right answer is the app's own
facts: Holt-Winters, best of 5 models in a backtest, 4.16 % MAPE (last 6 months), trained on 30 sales months.
Now, when the SQL writer replies NO_DATA (or only a MISSING line, no SQL) for the WHOLE question, our code checks
agent.no_data_about_app_ml: the question names the app's ML, the reason names it too, and neither names a topic
that is truly not in the data (profit, payments ...). Then the question goes to general_answer with the "This app's
ML" facts, like a GENERAL reply - the AI still writes the answer. Anything else keeps its normal NO_DATA.
Also 18-Nov: "how do you calculate customer risk score?" said "20% weight for overdue amounts" - the facts line now
says the 20 % is DAYS overdue (days since the last invoice vs the usual gap), not unpaid amounts.

The AI is the fake one of test_agent.py; MySQL (warehouse.run_select) and the notes search are faked.
Run with:  python -m pytest -q portal/tests/test_ml_safety_net.py
"""
import pytest

from portal.models import Question
from portal.rag import agent
from portal.tests.test_agent import mysql, use_fake_ai  # noqa: F401
from portal.tests.test_general_ml_facts import ML_BLOCK, ML_ROWS, fake_ml_db, general_request
from portal.tests.test_graph import DATA_START, steps  # noqa: F401

pytestmark = pytest.mark.django_db  # agent.ask() saves a Question

FORECAST_QUESTION = "which model you used for forecast and how accurate it is?"
FORECAST_NO_DATA = "NO_DATA: How the forecast model works and how accurate it is is not in the SS Manufacturing data."
FORECAST_ANSWER = ("The sales forecast uses Holt-Winters (trend + multiplicative 12-month season), the best of 5 "
                   "models in a backtest, with about 4.16 % error (MAPE, last 6 months).")
RISK_QUESTION = "how do you calculate customer risk score?"
PROFIT_QUESTION = "forecast our profit for next year"
PROFIT_NO_DATA = ("NO_DATA: a profit forecast needs the cost of the items sold, and the SS Manufacturing data has "
                  "only selling prices")


# ---------- the rule ----------

@pytest.mark.parametrize("question, reason, general", [
    (FORECAST_QUESTION, FORECAST_NO_DATA, True),                        # the 18-Nov question
    (RISK_QUESTION, "how the customer risk score is calculated is not in the data", True),
    (RISK_QUESTION, "the risk score's weights (sales drop, fewer orders, days overdue) are not stored", True),
    ("what data was the ML trained on", "the training data of the ML is not in the data", True),
    (PROFIT_QUESTION, PROFIT_NO_DATA, False),                           # profit is truly missing
    ("predict which customers will pay late", "payment dates are not in the data, so late payment cannot be "
                                              "predicted", False),      # payments are truly missing
    ("what is the budget forecast for next year", "the budget forecast is not in the data", False),
    ("sales of product model X200", "product models are not in the SS Manufacturing data", False),  # no ML word
    ("how was the forecast trained", "", False),                        # no reason given: stays NO_DATA
    ("salaries of the staff", "salaries are not in the SS Manufacturing data", False),
])
def test_the_rule(question, reason, general):
    assert agent.no_data_about_app_ml(question, reason) is general


# ---------- through the graph ----------

def test_the_18_nov_question_with_no_data_gets_the_general_answer_with_the_ml_facts(monkeypatch, mysql, user, steps):
    calls = fake_ml_db(monkeypatch, ML_ROWS)
    fake = use_fake_ai(monkeypatch, [(FORECAST_NO_DATA, 5000), (FORECAST_ANSWER, 400)])

    result = agent.ask(FORECAST_QUESTION, user)

    assert steps == DATA_START + ["write_sql", "general_answer"]
    assert result.status == "general" and result.answer == FORECAST_ANSWER
    assert "does not have this" not in result.answer and result.sql == ""
    assert general_request(fake) == f"{FORECAST_QUESTION}\n\n{ML_BLOCK}"
    assert fake.calls[-1][0]["content"] == agent.GENERAL_SYSTEM_PROMPT
    assert len(calls) == 1 and "ml_run_log" in calls[0]                 # the facts query only, no SQL of the AI ran
    assert result.tokens_text == "Tokens used: 5,400 (SQL 5,000 + answer 400)"   # one general call, counted
    assert Question.objects.get().status == "general"


def test_a_missing_line_without_sql_about_the_apps_ml_does_the_same(monkeypatch, mysql, user, steps):
    fake_ml_db(monkeypatch, ML_ROWS)
    fake = use_fake_ai(monkeypatch, ["MISSING: how the customer risk score is calculated is not in the data",
                                     FORECAST_ANSWER])

    result = agent.ask(RISK_QUESTION, user)

    assert steps == DATA_START + ["write_sql", "general_answer"]
    assert result.status == "general" and general_request(fake) == f"{RISK_QUESTION}\n\n{ML_BLOCK}"
    assert len(fake.calls) == 2                                          # no retry of the SQL step


def test_a_profit_question_with_no_data_stays_no_data(monkeypatch, mysql, user, steps):
    calls = fake_ml_db(monkeypatch, ML_ROWS)
    fake = use_fake_ai(monkeypatch, [PROFIT_NO_DATA])

    result = agent.ask(PROFIT_QUESTION, user)

    assert steps == DATA_START + ["write_sql"]
    assert result.status == "nodata" and result.answer.startswith("The SS Manufacturing data does not have this: a "
                                                                  "profit forecast needs")
    assert len(fake.calls) == 1 and calls == [] and mysql.calls == []


# ---------- the facts wording ----------

def test_the_risk_line_says_days_overdue_not_amounts():
    how = agent.ML_FACT_LINES["customer_risk"][1]
    assert ("40 % how far sales dropped (last 3 months vs the customer's normal 3 months), 40 % fewer sales orders "
            "than normal, 20 % days overdue (days since the last invoice vs the customer's usual gap between invoices "
            "- not unpaid amounts)") in how
    assert "20 % overdue;" not in how


def test_the_block_says_the_new_lines(monkeypatch):
    fake_ml_db(monkeypatch, ML_ROWS)

    block = agent.ml_facts_note()

    assert "20 % days overdue (days since the last invoice" in block
    assert "lowest MAPE on the last 6 complete months held back" in block
    assert "money (net sales)" in block and "days left = stock quantity / average daily sales quantity" in block
