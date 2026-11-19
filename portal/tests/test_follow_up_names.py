"""18-Nov: a follow-up that names PART of a name in the previous answer's result gets that full name as a fact line in
the rewrite and SQL requests (lc.memory.previous_names, agent.FOLLOW_UP_NAMES_*). The 18-Nov ML Insights chat (answered
by the backup model): "which customers might stop buying from us? give names" listed Aurora Fluid Power Limited first;
"why is aurora on top?" then got SQL with customer_name LIKE '%Aurora%' and an answer about another customer, Aurora
CNC Systems Pvt. Ltd. (Low risk).

The rows of an answer are not saved, so the earlier answer's SQL runs again (read-only, through the guard) - only when a
word of the follow-up is also in that answer's text. Any other message gets nothing more: no query, no tokens.
The AI is always the fake one of test_agent.py; MySQL and the notes search are faked.
Run with:  python -m pytest -q portal/tests/test_follow_up_names.py
"""
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from portal.lc import memory
from portal.lc.memory import ChatHistory
from portal.rag import agent, warehouse
from portal.tests.test_agent import (BACKUP, daily_limit_error, mysql, use_fake_ai,  # noqa: F401
                                     with_backup)
from portal.tests.test_backup_ml_mode import ml_gold  # noqa: F401
from portal.tests.test_chat import make_chat

pytestmark = pytest.mark.django_db

RISK_QUESTION = "which customers might stop buying from us? give names"
RISK_SQL = ("SELECT customer_name, risk_score, risk_level, reason FROM ml_customer_risk "
            "ORDER BY risk_score DESC LIMIT 20")
RISK_ANSWER = ("Based on the data up to 31-Oct-2026, 118 high-risk customers may stop buying. The highest risk "
               "customers include Aurora Fluid Power Limited, Sunrise Fluid Power Pvt Ltd, and Tejas Fabricators Pvt. "
               "Ltd., each with no order for many months.")
NAMES = ["Aurora Fluid Power Limited", "Sunrise Fluid Power Pvt Ltd", "Tejas Fabricators Pvt. Ltd.",
         "Meridian Hydraulics Limited", "Kaveri Fluid Systems", "Allied Castings", "Nilgiri Pumps",
         "Delta Fluid Controls"]
RISK_ROWS = {"columns": ["customer_name", "risk_score", "risk_level", "reason"],
             "rows": [[name, Decimal(f"{96 - n}.50"), "High", "No order for 150 days; sales down 70%"]
                      for n, name in enumerate(NAMES)],
             "truncated": False}
FOLLOW_UP = "why is aurora on top?"
FACT = 'In the previous answer, "aurora" = Aurora Fluid Power Limited (row 1 of its result).'
UNDERSTOOD = "Why is Aurora Fluid Power Limited at the top of the customer risk list?"
AURORA_SQL = ("```sql\nSELECT customer_name, risk_score, risk_level, reason FROM ml_customer_risk\n"
              "WHERE customer_name = 'Aurora Fluid Power Limited'\n```")
AURORA_ROWS = {"columns": ["customer_name", "risk_score", "risk_level", "reason"],
               "rows": [["Aurora Fluid Power Limited", Decimal("96.50"), "High", "No order for 150 days"]],
               "truncated": False}
AURORA_ANSWER = "Aurora Fluid Power Limited is on top (risk score 96.50, High): it has had no order for 150 days."


def risk_chat(user):
    """The 18-Nov ML Insights chat: the answer that listed the high-risk customers."""
    return make_chat(user, RISK_QUESTION, sql=RISK_SQL, answer=RISK_ANSWER, rows_count=20)


def user_text(call):
    """The last user message of one AI call."""
    return call[-1]["content"]


def history(*answers):
    """Chat messages: one earlier question per (sql, answer)."""
    return ChatHistory([SimpleNamespace(text=f"question {n}", understood_as="", sql=sql, answer=answer)
                        for n, (sql, answer) in enumerate(answers, start=1)]).messages


# ---------- the 18-Nov chat ----------

def test_the_follow_up_gets_the_full_name_of_the_previous_answers_first_row(monkeypatch, ml_gold, user):
    chat = risk_chat(user)
    ml_gold.results = [RISK_ROWS, AURORA_ROWS]
    fake = use_fake_ai(monkeypatch, [UNDERSTOOD, AURORA_SQL, AURORA_ANSWER])

    result = agent.ask(FOLLOW_UP, user, context=ChatHistory.for_chat(chat), mode="ml")

    assert result.status == "ok" and result.answer == AURORA_ANSWER
    # the earlier SQL ran again first (read-only, through the guard), then the new one
    assert len(ml_gold.calls) == 2 and "FROM ml_customer_risk" in ml_gold.calls[0]
    assert "risk_score DESC" in ml_gold.calls[0] and "LIMIT 20" in ml_gold.calls[0]
    rewrite, sql, _answer = fake.calls
    assert FACT in user_text(rewrite)
    assert "write it out with the full name" in user_text(rewrite)
    assert FACT in user_text(sql)
    assert "never a LIKE on the short word" in user_text(sql)
    assert "Aurora CNC" not in json.dumps(fake.calls)
    assert "mysql" in result.step_secs


def test_the_backup_model_gets_the_fact_too(monkeypatch, ml_gold, user, with_backup):
    # 18-Nov: the follow-up was answered by the backup model (the main one was over its daily limit)
    chat = risk_chat(user)
    ml_gold.results = [RISK_ROWS, AURORA_ROWS]
    fake = use_fake_ai(monkeypatch, [UNDERSTOOD, daily_limit_error(), AURORA_SQL, AURORA_ANSWER])

    result = agent.ask(FOLLOW_UP, user, context=ChatHistory.for_chat(chat), mode="ml")

    assert result.status == "ok" and result.model == BACKUP
    backup_sql = next(call for call, model in zip(fake.calls, fake.models) if model == BACKUP)
    assert FACT in user_text(backup_sql)


def test_the_fact_reaches_the_sql_request_also_when_the_rewrite_says_new(monkeypatch, ml_gold, user):
    chat = risk_chat(user)
    ml_gold.results = [RISK_ROWS, AURORA_ROWS]
    fake = use_fake_ai(monkeypatch, ["NEW", AURORA_SQL, AURORA_ANSWER])

    agent.ask(FOLLOW_UP, user, context=ChatHistory.for_chat(chat), mode="ml")

    assert FACT in user_text(fake.calls[1])


# ---------- nothing more: no query, no tokens ----------

def test_a_follow_up_without_such_a_word_gets_nothing_and_no_query(monkeypatch, ml_gold, user):
    chat = risk_chat(user)
    ml_gold.results = [AURORA_ROWS]
    fake = use_fake_ai(monkeypatch, ["NEW", AURORA_SQL, AURORA_ANSWER])

    agent.ask("and which customers in Kerala?", user, context=ChatHistory.for_chat(chat), mode="ml")

    assert len(ml_gold.calls) == 1                                        # only the new SQL
    assert "In the previous answer" not in json.dumps(fake.calls)
    assert user_text(fake.calls[0]).endswith(agent.REWRITE_REQUEST.split("{earlier}", 1)[1].format(
        question="and which customers in Kerala?"))


def test_a_first_question_gets_nothing_and_no_query(monkeypatch, ml_gold, user):
    ml_gold.results = [AURORA_ROWS]
    fake = use_fake_ai(monkeypatch, [AURORA_SQL, AURORA_ANSWER])

    agent.ask(FOLLOW_UP, user, mode="ml")

    assert len(ml_gold.calls) == 1
    assert "In the previous answer" not in json.dumps(fake.calls)


def test_the_previous_sql_failing_adds_nothing(monkeypatch, ml_gold, user):
    chat = risk_chat(user)
    ml_gold.results = [warehouse.QueryError("(1146) Table 'ss_gold.ml_customer_risk' doesn't exist"), AURORA_ROWS]
    fake = use_fake_ai(monkeypatch, [UNDERSTOOD, AURORA_SQL, AURORA_ANSWER])

    result = agent.ask(FOLLOW_UP, user, context=ChatHistory.for_chat(chat), mode="ml")

    assert result.status == "ok" and len(ml_gold.calls) == 2              # the new SQL still runs
    assert "In the previous answer" not in json.dumps(fake.calls)


# ---------- the word rules (lc.memory.previous_names) ----------

def test_several_names_list_up_to_three_and_say_which_row_is_first(ml_gold):
    ml_gold.results = [RISK_ROWS]
    text = memory.previous_names(history((RISK_SQL, RISK_ANSWER)), "why are the fluid ones on top?")
    assert text == ('In the previous answer, "fluid" is part of 4 names of its result: Aurora Fluid Power Limited '
                    '(row 1), Sunrise Fluid Power Pvt Ltd (row 2), Kaveri Fluid Systems (row 5) and 1 more - the first '
                    'is row 1.')


def test_the_word_is_matched_in_any_case_as_a_whole_word(ml_gold):
    ml_gold.results = [RISK_ROWS]
    assert memory.previous_names(history((RISK_SQL, RISK_ANSWER)), "Why is AURORA first?") == FACT
    # "auro" is not a whole word of any name (and not in the answer): no query
    ml_gold.results, ml_gold.calls = [RISK_ROWS], []
    assert memory.previous_names(history((RISK_SQL, RISK_ANSWER)), "why is auro first?") == ""
    assert ml_gold.calls == []


def test_two_words_get_one_line_each(ml_gold):
    ml_gold.results = [RISK_ROWS]
    text = memory.previous_names(history((RISK_SQL, RISK_ANSWER)), "compare aurora and tejas")
    assert text.splitlines() == [FACT, 'In the previous answer, "tejas" = Tejas Fabricators Pvt. Ltd. (row 3 of its '
                                       'result).']


@pytest.mark.parametrize("text", [
    "and for Sep 2026?", "why are customers high risk?", "show the risk_score and reason", "explain the reason",
    "which customers might stop buying?", "",
])
def test_ordinary_and_sql_words_need_no_query(ml_gold, text):
    assert memory.previous_names(history((RISK_SQL, RISK_ANSWER)), text) == ""
    assert ml_gold.calls == []


def test_a_name_typed_in_full_or_a_word_only_in_the_text_adds_nothing(ml_gold):
    ml_gold.results = [RISK_ROWS]
    assert memory.previous_names(history((RISK_SQL, RISK_ANSWER)), "why is Aurora Fluid Power Limited on top?") == ""
    ml_gold.results = [RISK_ROWS]
    assert memory.previous_names(history((RISK_SQL, RISK_ANSWER)), "how many months of data?") == ""


def test_an_answer_without_sql_has_no_rows():
    assert memory.previous_names(history(("", "Aurora is a dawn light.")), FOLLOW_UP) == ""
    assert memory.previous_names([], FOLLOW_UP) == ""


def test_an_older_answer_is_named_by_its_number(ml_gold):
    ml_gold.results = [RISK_ROWS]
    text = memory.previous_names(history((RISK_SQL, RISK_ANSWER), ("", "High risk means a score over 70.")),
                                 FOLLOW_UP)
    assert text == FACT.replace("the previous answer", "earlier answer 1")
