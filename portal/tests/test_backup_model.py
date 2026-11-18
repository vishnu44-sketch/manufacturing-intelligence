"""The backup model after the main model's DAILY limit (18-Nov, question 118).

At 10:42 the main model (openai/gpt-oss-120b) had used its daily tokens: Groq refused the SQL call with a 429
"tokens per day" and the app moved the call to the backup model, as planned. But the SQL request was the full one
(~6,400 tokens: the rules, the schema and five notes pieces) and the backup adds 1,000 for its reply - more than the
backup's free tier takes in a minute. Groq refused that at once too (413 "Request too large", 0.07 s), and the
question ended with "The AI service returned an error" although the backup had all its daily tokens left.
Now the backup gets a request cut to its size (lc.calls.for_backup: the 2 closest notes pieces, the last try only)
and, if Groq still says too large, once more with one piece. Every AI call of a question (rewrite, route, SQL,
answer, documents answer, general answer) moves to the backup on a daily limit; a per-minute limit still waits for
the main model; any other error is still "returned an error". The AI chart: test_ai_chart.py.

The AI is the FAKE of test_agent.py (FakeAI behind LangChain): no Groq call, never the real backup model.
Run with:  python -m pytest -q portal/tests/test_backup_model.py
"""
import pytest
from langchain_core.messages import AIMessage, HumanMessage

from portal.lc import calls
from portal.lc.calls import LcRequest
from portal.models import Question
from portal.rag import agent
from portal.tests.test_agent import (BACKUP, DOC_ANSWER, DOC_QUESTION, FY_QUESTION, GOOD_SQL, MAIN, PDF_HITS, ROWS,
                                     UNDERSTOOD, api_error, daily_limit_error, mysql, rate_limit_error,  # noqa: F401
                                     use_fake_ai, use_pdf_hits, with_backup)  # noqa: F401

pytestmark = pytest.mark.django_db  # agent.ask() saves a Question

ANSWER = "Aurora Fluid Power Limited had the highest invoice value in Aug 2026."
FIVE_NOTES = [{"text": f"note piece {n} ...", "source": "sql_examples.md", "kind": "example", "score": 1 - n / 10,
               "heading": f"Q: example {n}"} for n in range(1, 6)]


def too_large_error(model=BACKUP):
    """Groq's 413 when one request is more than the model's tokens a minute (its real wording)."""
    return api_error(413, f"Error code: 413 - Request too large for model `{model}` in organization `org_x` "
                          "service tier `on_demand` on tokens per minute (TPM): Limit 6000, Requested 7412, "
                          "please reduce your message size and try again.")


@pytest.fixture
def five_notes(monkeypatch, mysql):
    """The notes search finds five pieces (as the real one does: agent.TOP_K)."""
    monkeypatch.setattr(agent, "search", lambda question, top_k=5: FIVE_NOTES)
    return mysql


def sql_request(call):
    """The human message of a SQL call (the question, the notes, the schema)."""
    return call[1]["content"]


# ---------- the request cut for the backup ----------

def test_for_backup_keeps_the_two_closest_notes_and_the_last_try():
    values = {"schema": "s", "count": 3, "documents": "a\n\n---\n\nb\n\n---\n\nc", "today": "t", "preferences": "",
              "earlier": "E", "question": "q"}
    tries = [AIMessage("try 1"), HumanMessage("problem 1"), AIMessage("try 2"), HumanMessage("problem 2")]
    request = LcRequest("sql", values, retries=tries)

    cut = calls.for_backup(request)
    smallest = calls.for_backup(request, smallest=True)

    assert (cut.values["documents"], cut.values["count"], cut.values["earlier"]) == ("a\n\n---\n\nb", 2, "E")
    assert cut.retries == tries[2:]
    assert (smallest.values["documents"], smallest.values["count"], smallest.values["earlier"]) == ("a", 1, "")
    assert request.values == values and request.retries == tries       # the main model's request is not changed


def test_for_backup_leaves_other_requests_as_they_are():
    request = LcRequest("answer", {"question": "q", "rows": "r"})
    assert calls.for_backup(request) is request


# ---------- a daily limit at each AI call of a question ----------

def test_a_daily_limit_at_the_sql_call_moves_it_to_the_backup_with_a_smaller_request(monkeypatch, five_notes, user,
                                                                                     with_backup):
    """Question 118: the main model's daily limit at the SQL call -> the backup writes the SQL from a request cut to
    its size, then the answer; status ok and the backup's name saved (the answer card and the token line show it)."""
    waits = []
    monkeypatch.setattr(agent.time, "sleep", waits.append)
    five_notes.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [daily_limit_error(), (GOOD_SQL, 4000), (ANSWER, 900)])

    result = agent.ask("Top customers in Aug 2026?", user)

    assert result.status == "ok" and result.answer == ANSWER
    assert fake.models == [MAIN, BACKUP, BACKUP]
    assert fake.max_tokens[1:] == [agent.FALLBACK_MAX_TOKENS, agent.FALLBACK_MAX_TOKENS]
    assert waits == []                                                   # a daily limit is never waited for
    main_request, backup_request = sql_request(fake.calls[0]), sql_request(fake.calls[1])
    assert "note piece 5" in main_request and "the 5 pieces" in main_request
    assert "note piece 1" in backup_request and "note piece 2" in backup_request
    assert "note piece 3" not in backup_request and "the 2 pieces" in backup_request
    assert result.model == BACKUP and result.answered_by_backup
    saved = Question.objects.get()
    assert saved.model == BACKUP and saved.status == "ok" and saved.total_tokens == 4900


def test_a_backup_request_still_too_large_is_sent_once_more_with_one_notes_piece(monkeypatch, five_notes, user,
                                                                                with_backup):
    five_notes.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [daily_limit_error(), too_large_error(), GOOD_SQL, ANSWER])

    result = agent.ask("Top customers in Aug 2026?", user)

    assert result.status == "ok" and result.model == BACKUP
    assert fake.models == [MAIN, BACKUP, BACKUP, BACKUP]
    last = sql_request(fake.calls[2])
    assert "note piece 1" in last and "note piece 2" not in last and "the 1 pieces" in last


def test_a_backup_request_too_large_even_with_one_piece_gives_the_error_message(monkeypatch, five_notes, user,
                                                                                with_backup):
    fake = use_fake_ai(monkeypatch, [daily_limit_error(), too_large_error(), too_large_error()])

    result = agent.ask("Top customers in Aug 2026?", user)

    assert result.status == "error" and result.answer == agent.AI_ERROR
    assert fake.models == [MAIN, BACKUP, BACKUP] and five_notes.calls == []


def test_a_daily_limit_at_the_rewrite_moves_the_whole_question_to_the_backup(monkeypatch, mysql, user, with_backup):
    mysql.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [daily_limit_error(), UNDERSTOOD, GOOD_SQL, ANSWER])

    result = agent.ask("can i get above questions profit perstange also", user, context=[FY_QUESTION])

    assert result.status == "ok" and result.understood_as == UNDERSTOOD
    assert fake.models == [MAIN, BACKUP, BACKUP, BACKUP]
    assert result.model == BACKUP


def test_a_daily_limit_at_the_router_moves_the_documents_answer_to_the_backup(monkeypatch, mysql, user, with_backup):
    use_pdf_hits(monkeypatch, PDF_HITS)
    fake = use_fake_ai(monkeypatch, [daily_limit_error(), "documents", DOC_ANSWER])

    result = agent.ask(DOC_QUESTION, user)

    assert result.status == "docs" and result.answer == DOC_ANSWER
    assert fake.models == [MAIN, BACKUP, BACKUP]
    assert result.model == BACKUP and Question.objects.get().model == BACKUP


def test_a_daily_limit_at_the_general_answer_moves_it_to_the_backup(monkeypatch, mysql, user, with_backup):
    paris = "The capital of France is Paris."
    fake = use_fake_ai(monkeypatch, ["GENERAL", daily_limit_error(), paris])

    result = agent.ask("What is the capital of France?", user)

    assert result.status == "general" and result.answer == paris
    assert fake.models == [MAIN, MAIN, BACKUP]
    assert result.model == BACKUP and Question.objects.get().model == BACKUP


# ---------- not a daily limit: no backup ----------

def test_a_per_minute_limit_waits_for_the_main_model_and_never_uses_the_backup(monkeypatch, five_notes, user,
                                                                               with_backup):
    waits = []
    monkeypatch.setattr(agent.time, "sleep", waits.append)
    five_notes.results = [ROWS]
    fake = use_fake_ai(monkeypatch, [rate_limit_error(retry_after=2), GOOD_SQL, ANSWER])

    result = agent.ask("Top customers in Aug 2026?", user)

    assert result.status == "ok" and result.model == MAIN and not result.answered_by_backup
    assert waits == [2.5] and fake.models == [MAIN, MAIN, MAIN]
    assert "note piece 5" in sql_request(fake.calls[1])                 # the main model's full request


def test_another_error_of_the_main_model_gives_the_error_message_and_no_backup(monkeypatch, five_notes, user,
                                                                               with_backup):
    fake = use_fake_ai(monkeypatch, [api_error(400, "Error code: 400 - invalid request")])

    result = agent.ask("Top customers in Aug 2026?", user)

    assert result.status == "error" and result.answer == agent.AI_ERROR
    assert fake.models == [MAIN]


def test_another_error_of_the_backup_gives_the_error_message(monkeypatch, five_notes, user, with_backup):
    fake = use_fake_ai(monkeypatch, [daily_limit_error(), api_error(404, "Error code: 404 - model not found")])

    result = agent.ask("Top customers in Aug 2026?", user)

    assert result.status == "error" and result.answer == agent.AI_ERROR
    assert fake.models == [MAIN, BACKUP]
