"""The golden set and its grading (no AI, no Groq tokens: the agent is replaced by a fake)."""
import csv
import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from portal.evals import grading
from portal.evals.questions import ITEMS, QUICK
from portal.management.commands import run_eval
from portal.rag import agent, sql_guard, warehouse

IDS = [item["id"] for item in ITEMS]


# ---------- the question set ----------

def test_the_golden_set_has_unique_ids_and_known_keys():
    assert len(IDS) == len(set(IDS)) >= 50
    keys = {"id", "question", "must", "should", "must_have", "must_not", "allow", "expect", "context"}
    assert all(set(item) <= keys and item["question"].strip() for item in ITEMS)


def test_a_follow_up_comes_after_the_questions_of_its_chat():
    for item in ITEMS:
        for earlier in item.get("context", []):
            assert IDS.index(earlier) < IDS.index(item["id"]), item["id"]


def test_the_quick_set_is_15_questions_of_the_golden_set():
    assert len(QUICK) == len(set(QUICK)) == 15 and set(QUICK) <= set(IDS)


def test_phrases_are_written_in_lower_case():
    """The answer is compared in lower case, so an upper-case phrase could never match."""
    for item in ITEMS:
        for phrase in item.get("must_have", []) + item.get("must_not", []) + item.get("allow", []):
            assert phrase == phrase.lower(), (item["id"], phrase)


def test_every_truth_sql_passes_the_guard():
    try:
        tables = warehouse.allowed_tables()
    except Exception as exc:
        pytest.skip(f"read-only MySQL not available: {exc}")
    for item in ITEMS:
        for key in ("must", "should"):
            if item.get(key):
                sql_guard.check_sql(item[key], tables)


def test_a_follow_up_brings_the_earlier_questions_of_its_chat():
    picked = [item["id"] for item in run_eval.pick_items("full", ["Q62"])]
    assert picked == ["Q58", "Q59", "Q60", "Q61", "Q62"]                    # Q59 itself follows Q58
    assert [item["id"] for item in run_eval.pick_items("quick")] == [i for i in IDS if i in QUICK]
    with pytest.raises(CommandError, match="Q99"):
        run_eval.pick_items("full", ["Q99"])


# ---------- grading ----------

def test_how_values_may_be_written():
    assert grading.spellings(Decimal("33851075.00")) == ["33,851,075.00"]
    assert grading.spellings(4097) == ["4,097"]
    assert "20-Mar-2027" in grading.spellings(date(2027, 3, 20))
    assert grading.found(4097, "4,097 finished goods") and not grading.found(4097, "14,097 items")
    assert not grading.found(Decimal("4.5"), "it rose 4.55 %")


@pytest.fixture
def truth(monkeypatch):
    """The truth 'SQL' of a test item is the list of its values; a real golden SQL gives nothing (no MySQL)."""
    monkeypatch.setattr(grading, "truth_values", lambda sql: [] if isinstance(sql, str) else list(sql or []))


def test_grade_pass_partial_and_fail(truth):
    item = {"id": "X", "question": "?", "must": [Decimal("827149042.00")], "should": [date(2026, 10, 21)],
            "must_have": ["so far"]}
    right = "Nov 2026 so far (21-Oct-2026 to 28-Oct-2026): INR 827,149,042.00."
    assert grading.grade(item, {"status": "ok", "answer": right}) == ("PASS", [])
    assert grading.grade(item, {"status": "ok", "answer": "INR 3,869,959,327.00"})[0] == "FAIL"
    verdict, why = grading.grade(item, {"status": "ok", "answer": "INR 827,149,042.00 from 2026-10-21, profit"})
    assert verdict == "PARTIAL" and "date written as yyyy-mm-dd" in why and "says 'profit'" in why
    assert grading.grade({"id": "N10", "question": "?", "expect": "refused"}, {"status": "ok"})[0] == "FAIL"


# ---------- the command ----------

@pytest.fixture
def results_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(run_eval, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(run_eval, "current_commit", lambda: "abc1234")
    return tmp_path


@pytest.mark.django_db
def test_a_run_asks_grades_and_adds_a_score_line(results_dir, truth, monkeypatch, staff):
    asked = []

    def fake_ask(question, user, context=None):
        asked.append((question, len(context or [])))
        status = "refused" if question.startswith("delete") else "ok"
        return agent.AskResult(text=question, status=status, answer="so far, before gst", model="openai/gpt-oss-120b")
    monkeypatch.setattr(agent, "ask", fake_ask)
    chat_before = agent._chat

    call_command("run_eval", "quick", "--cap", "1000000", "--out", str(results_dir / "q.json"))

    assert len(asked) == 15
    saved = json.loads((results_dir / "q.json").read_text(encoding="utf-8"))
    assert set(saved) == set(QUICK) and saved["N10"]["status"] == "refused"
    rows = list(csv.DictReader((results_dir / "scores.csv").open(encoding="utf-8")))
    assert len(rows) == 1 and rows[0]["set"] == "quick" and rows[0]["asked"] == rows[0]["of"] == "15"
    assert rows[0]["commit"] == "abc1234" and rows[0]["file"] == "q.json"
    assert int(rows[0]["pass"]) + int(rows[0]["partial"]) + int(rows[0]["fail"]) == 15
    assert agent._chat is chat_before                       # the agent is put back after the run

    call_command("run_eval", "quick", "--cap", "1000000", "--out", str(results_dir / "q.json"))
    assert len(asked) == 15                                   # all answered already: nothing asked again
    assert len(list(csv.DictReader((results_dir / "scores.csv").open(encoding="utf-8")))) == 2


@pytest.mark.django_db
def test_a_run_stops_before_the_token_cap(results_dir, truth, monkeypatch, staff):
    def fake_client():   # a new client each time, like groq.Groq(); every call 'costs' 7,000 tokens
        response = SimpleNamespace(usage=SimpleNamespace(total_tokens=7_000),
                                   choices=[SimpleNamespace(finish_reason="stop")])
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: response)))
    monkeypatch.setattr(agent, "get_groq_client", fake_client)

    def ask_one_call(question, user, context=None):
        agent.get_groq_client().chat.completions.create(model="m")
        return agent.AskResult(text=question, status="ok")
    monkeypatch.setattr(agent, "ask", ask_one_call)

    call_command("run_eval", "full", "--cap", "20000", "--out", str(results_dir / "f.json"))
    saved = json.loads((results_dir / "f.json").read_text(encoding="utf-8"))
    # Q38 (7,000) + Q39, a follow-up (about 11,000) = 18,000; Q40 would pass 20,000
    assert list(saved) == ["Q38", "Q39"] and saved["Q38"]["tokens"] == 7_000
    rows = list(csv.DictReader((results_dir / "scores.csv").open(encoding="utf-8")))
    assert rows[0]["asked"] == "2" and rows[0]["of"] == str(len(ITEMS)) and rows[0]["tokens"] == "14000"


@pytest.mark.django_db
def test_nothing_of_a_run_stays_in_history(results_dir, truth, monkeypatch, staff):
    from portal.models import Question

    def ask_and_save(question, user, context=None):
        Question.objects.create(user=user, text=question)
        return agent.AskResult(text=question, status="ok")
    monkeypatch.setattr(agent, "ask", ask_and_save)
    call_command("run_eval", "quick", "--ids", "Q38", "--cap", "1000000", "--out", str(results_dir / "h.json"))
    assert Question.objects.count() == 0
