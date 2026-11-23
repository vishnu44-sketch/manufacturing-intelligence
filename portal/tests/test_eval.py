"""The golden set and its grading (no AI, no Groq tokens: the agent is replaced by a fake)."""
import csv
import json
from datetime import date
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from portal.evals import grading
from portal.evals.questions import ITEMS, ML_QUICK, QUICK
from portal.lc import calls as lc_calls
from portal.lc.calls import LcRequest
from portal.management.commands import run_eval
from portal.rag import agent, sql_guard, warehouse
from portal.tests.test_agent import use_fake_ai

IDS = [item["id"] for item in ITEMS]


# ---------- the question set ----------

def test_the_golden_set_has_unique_ids_and_known_keys():
    assert len(IDS) == len(set(IDS)) >= 50
    keys = {"id", "question", "must", "should", "must_have", "must_not", "allow", "expect", "context", "mode"}
    assert all(set(item) <= keys and item["question"].strip() for item in ITEMS)


def test_a_follow_up_comes_after_the_questions_of_its_chat():
    for item in ITEMS:
        for earlier in item.get("context", []):
            assert IDS.index(earlier) < IDS.index(item["id"]), item["id"]


def test_the_quick_set_is_15_questions_of_the_golden_set():
    assert len(QUICK) == len(set(QUICK)) == 15 and set(QUICK) <= set(IDS)


def test_the_ml_set_has_the_questions_that_failed_on_18_nov():
    """18-Nov: a weaker model failed these in ML Insights; they are asked as in an ML Insights chat (mode 'ml')."""
    assert len(ML_QUICK) == len(set(ML_QUICK)) == 10 and set(ML_QUICK) <= set(IDS)
    by_id = {item["id"]: item for item in ITEMS}
    assert [by_id[i]["question"] for i in ("N30", "N31", "N32", "N33")] == [
        "my top customer in Aug 2027", "predict sales for Aug 2027 and give me top 5 customers",
        "What is the sales forecast for August 2027?", "can you give it for sep 2027"]
    assert by_id["N33"]["context"] == ["N32"] and by_id["N34"]["context"] == ["N24"]
    assert by_id["N37"]["context"] == ["N21"]
    assert all(by_id[i].get("mode") == "ml" for i in ML_QUICK if i not in ("N21", "N24"))
    assert {item.get("mode", "") for item in ITEMS} == {"", "ml"}


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


def test_a_whole_number_may_be_written_with_zero_decimals():
    """20-Nov: N62 failed with "missing 31; missing 191" although the answer said "31.000 units ... 191.000 units"
    (quantities are DECIMAL(15,3)); a whole-number truth is found with .000 after it, but not inside another number."""
    answer = "there are 31.000 units on open sales orders and 191.000 units in stock"
    assert grading.found(31, answer) and grading.found(191, answer)
    assert grading.found(Decimal("4097"), "4,097.00 items") and grading.found(31, "31 units.")
    assert not grading.found(31, "31.05 units") and not grading.found(31, "31.500 units")
    assert not grading.found(31, "131.000 units")


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


def test_expect_may_allow_several_statuses(truth):
    item = {"id": "X", "question": "?", "expect": ["general", "ok"]}
    assert grading.grade(item, {"status": "general", "answer": "a"}) == ("PASS", [])
    assert grading.grade(item, {"status": "ok", "answer": "a"}) == ("PASS", [])
    assert grading.grade(item, {"status": "nodata", "answer": "a"}) == (
        "FAIL", ["status nodata (expected general or ok)"])


def test_a_forecast_is_found_as_the_answer_writes_it(truth):
    """The truth of a forecast is its amount in Cr with one decimal (CONCAT(ROUND(x / 10000000, 1)) gives '53.7'),
    as agent.ML_RESULTS_NOTE has the answer write it."""
    item = {"id": "X", "question": "?", "must": ["53.7"], "must_not": ["you can ask me"]}
    assert grading.grade(item, {"status": "ok", "answer": "Aug 2027: about INR 53.7 Cr"}) == ("PASS", [])
    assert grading.grade(item, {"status": "ok", "answer": "about INR 56.3 Cr"})[0] == "FAIL"
    assert grading.grade(item, {"status": "ok", "answer": "53.7 Cr. You can ask me more"})[0] == "PARTIAL"


# ---------- the command ----------

@pytest.fixture
def results_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(run_eval, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(run_eval, "current_commit", lambda: "abc1234")
    return tmp_path


@pytest.mark.django_db
def test_a_run_asks_grades_and_adds_a_score_line(results_dir, truth, monkeypatch, staff):
    asked = []

    def fake_ask(question, user, context=None, mode="", model=""):
        asked.append((question, len(context or [])))
        status = "refused" if question.startswith("delete") else "ok"
        return agent.AskResult(text=question, status=status, answer="so far, before gst", model="openai/gpt-oss-120b")
    monkeypatch.setattr(agent, "ask", fake_ask)
    chat_before = lc_calls.chat

    call_command("run_eval", "quick", "--cap", "1000000", "--out", str(results_dir / "q.json"))

    assert len(asked) == 15
    saved = json.loads((results_dir / "q.json").read_text(encoding="utf-8"))
    assert set(saved) == set(QUICK) and saved["N10"]["status"] == "refused"
    rows = list(csv.DictReader((results_dir / "scores.csv").open(encoding="utf-8")))
    assert len(rows) == 1 and rows[0]["set"] == "quick" and rows[0]["asked"] == rows[0]["of"] == "15"
    assert rows[0]["commit"] == "abc1234" and rows[0]["file"] == "q.json"
    assert int(rows[0]["pass"]) + int(rows[0]["partial"]) + int(rows[0]["fail"]) == 15
    assert lc_calls.chat is chat_before                     # the AI call is put back after the run

    call_command("run_eval", "quick", "--cap", "1000000", "--out", str(results_dir / "q.json"))
    assert len(asked) == 15                                   # all answered already: nothing asked again
    assert len(list(csv.DictReader((results_dir / "scores.csv").open(encoding="utf-8")))) == 2


@pytest.mark.django_db
def test_a_run_stops_before_the_token_cap(results_dir, truth, monkeypatch, staff):
    use_fake_ai(monkeypatch, [("Top customers in Sep 2026?", 7_000)] * 5)   # every call 'costs' 7,000 tokens

    # one AI call through LangChain, like the agent makes
    def ask_one_call(question, user, context=None, mode="", model=""):
        lc_calls.chat(LcRequest("rewrite", {"earlier": "1. Q (latest)", "question": question}), 100, "low")
        return agent.AskResult(text=question, status="ok")
    monkeypatch.setattr(agent, "ask", ask_one_call)

    call_command("run_eval", "full", "--cap", "20000", "--out", str(results_dir / "f.json"))
    saved = json.loads((results_dir / "f.json").read_text(encoding="utf-8"))
    # Q38 (7,000) + Q39, a follow-up (about 11,000) = 18,000; Q40 would pass 20,000
    assert list(saved) == ["Q38", "Q39"] and saved["Q38"]["tokens"] == 7_000
    assert saved["Q38"]["calls"] == [{"model": agent.model_name(), "total": 7_000, "finish": "stop"}]
    rows = list(csv.DictReader((results_dir / "scores.csv").open(encoding="utf-8")))
    assert rows[0]["asked"] == "2" and rows[0]["of"] == str(len(ITEMS)) and rows[0]["tokens"] == "14000"


@pytest.mark.django_db
def test_a_run_never_spends_the_other_models_tokens(results_dir, truth, monkeypatch, staff):
    """A main-model run: a call for the backup model is refused at once (as if its daily limit were used up),
    never reaches the AI and is not recorded; the main model's call is recorded with its tokens."""
    monkeypatch.setenv("GROQ_FALLBACK_MODEL", "qwen/qwen3.8-27b")
    fake = use_fake_ai(monkeypatch, [("Top customers in Sep 2026?", 7_000)])
    refused = []

    def ask_both(question, user, context=None, mode="", model=""):
        request = LcRequest("rewrite", {"earlier": "1. Q (latest)", "question": question})
        try:
            lc_calls.chat(request, 100, "low", "qwen/qwen3.8-27b")
        except agent.DailyLimitReached:
            refused.append(question)
        lc_calls.chat(request, 100, "low")
        return agent.AskResult(text=question, status="ok")
    monkeypatch.setattr(agent, "ask", ask_both)

    call_command("run_eval", "quick", "--ids", "Q38", "--cap", "1000000", "--out", str(results_dir / "m.json"))
    saved = json.loads((results_dir / "m.json").read_text(encoding="utf-8"))
    assert len(refused) == 1 and fake.models == [agent.model_name()]
    assert saved["Q38"]["calls"] == [{"model": agent.model_name(), "total": 7_000, "finish": "stop"}]


@pytest.mark.django_db
def test_memory_store_searches_the_docs_in_a_store_in_memory(results_dir, truth, monkeypatch, staff):
    """--memory-store (Qdrant not running): the docs/ notes are built in memory (fake vectors here) and the
    agent's search reads them; afterwards the agent's own search is back."""
    from langchain_core.embeddings import Embeddings
    from portal.lc import vectorstore

    class LetterEmbeddings(Embeddings):   # a fake model: how often a few letters appear
        def embed_documents(self, texts):
            return [self.embed_query(text) for text in texts]

        def embed_query(self, text):
            return [float(text.lower().count(letter)) + 0.1 for letter in "aeiou"]

    monkeypatch.setattr(vectorstore, "get_embeddings", lambda: LetterEmbeddings())
    search_before, found = agent.search, []

    def ask_search(question, user, context=None, mode="", model=""):
        found.extend(agent.search(question, top_k=3))
        return agent.AskResult(text=question, status="ok")
    monkeypatch.setattr(agent, "ask", ask_search)

    call_command("run_eval", "quick", "--ids", "Q38", "--cap", "1000000", "--memory-store",
                 "--out", str(results_dir / "s.json"))
    vectorstore.clear()
    assert len(found) == 3 and {hit["source"] for hit in found} <= {"business_rules.md", "data_dictionary.md",
                                                                      "sql_examples.md"}
    assert agent.search is search_before


@pytest.mark.django_db
def test_nothing_of_a_run_stays_in_history(results_dir, truth, monkeypatch, staff):
    from portal.models import Question

    def ask_and_save(question, user, context=None, mode="", model=""):
        Question.objects.create(user=user, text=question)
        return agent.AskResult(text=question, status="ok")
    monkeypatch.setattr(agent, "ask", ask_and_save)
    call_command("run_eval", "quick", "--ids", "Q38", "--cap", "1000000", "--out", str(results_dir / "h.json"))
    assert Question.objects.count() == 0


# ---------- one chosen model of the chain (18-Nov: test each model before a demo) ----------

@pytest.mark.django_db
def test_model_choice_is_passed_to_every_question(results_dir, truth, monkeypatch, staff):
    """--model second (19-Nov: groq-main-2, the same model on the second Groq key): every question is asked with
    model='groq-main-2' (an admin's choice: only that model); a call on the first key never reaches the AI although
    it is the same model name; the answers file and the score line name it.
    The ML set is asked as in an ML Insights chat (mode 'ml', its follow-ups with their earlier answers)."""
    from portal.lc import llm
    monkeypatch.setenv("GROQ_API_KEY_2", "test-key-2")
    fake = use_fake_ai(monkeypatch, [("Top customers in Sep 2026?", 3_000)])
    asked, refused = [], []

    def ask_second(question, user, context=None, mode="", model=""):
        asked.append((question, mode, model, len(context or [])))
        request = LcRequest("rewrite", {"earlier": "1. Q (latest)", "question": question})
        try:
            lc_calls.chat(request, 100, "low", agent.model_name())        # the same model on the first key: refused
        except agent.DailyLimitReached:
            refused.append(question)
        if len(asked) == 1:                                               # the chosen key: asked and counted
            lc_calls.chat(request, 100, "low", agent.model_name(), key_env=llm.KEY_2)
        return agent.AskResult(text=question, status="ok", answer="about INR 53.7 Cr", model=agent.model_name())
    monkeypatch.setattr(agent, "ask", ask_second)

    call_command("run_eval", "ml", "--model", "second", "--cap", "1000000")

    assert [model for _, _, model, _ in asked] == ["groq-main-2"] * 10 and len(refused) == 10
    assert {question: mode for question, mode, _, _ in asked}["my top customer in Aug 2027"] == "ml"
    assert ("can you give it for sep 2027", "ml", "groq-main-2", 1) in asked          # N33 after N32
    assert fake.models == [agent.model_name()] and fake.keys == [llm.KEY_2]
    files = list(results_dir.glob("ml_second_*.json"))
    assert len(files) == 1
    saved = json.loads(files[0].read_text(encoding="utf-8"))
    assert list(saved) == ML_QUICK and saved["N21"]["calls"] == [
        {"model": agent.model_name(), "total": 3_000, "finish": "stop"}]
    rows = list(csv.DictReader((results_dir / "scores.csv").open(encoding="utf-8")))
    assert rows[0]["set"] == "ml" and rows[0]["model"] == agent.model_name() and rows[0]["of"] == "10"


@pytest.mark.django_db
def test_main_and_backup_are_the_groq_models(results_dir, truth, monkeypatch, staff):
    monkeypatch.setenv("GROQ_FALLBACK_MODEL", "qwen/qwen3.8-27b")
    chosen = []

    def ask_one(question, user, context=None, mode="", model=""):
        chosen.append(model)
        return agent.AskResult(text=question, status="ok")
    monkeypatch.setattr(agent, "ask", ask_one)

    call_command("run_eval", "quick", "--ids", "Q38", "--cap", "1000000")
    call_command("run_eval", "quick", "--ids", "Q38", "--model", "backup", "--cap", "1000000")
    call_command("run_eval", "quick", "--ids", "Q38", "--model", "groq-main", "--cap", "1000000",
                 "--out", str(results_dir / "g.json"))
    assert chosen == ["groq-main", "groq-backup", "groq-main"]
    # the answers files keep their old names: main / backup
    assert sorted(path.name.split("_")[1] for path in results_dir.glob("quick_*.json")) == ["backup", "main"]


@pytest.mark.parametrize("model, message", [
    ("second", "groq-main-2 is not set up"),                   # no GROQ_API_KEY_2 in the tests
    ("groq-backup", "groq-backup is not set up"),              # no GROQ_FALLBACK_MODEL
])
@pytest.mark.django_db
def test_a_model_that_is_not_set_up_is_refused(results_dir, monkeypatch, staff, model, message):
    monkeypatch.delenv("GROQ_FALLBACK_MODEL", raising=False)
    monkeypatch.setattr(agent, "ask", lambda *args, **kwargs: pytest.fail("nothing may be asked"))
    with pytest.raises(CommandError, match=message):
        call_command("run_eval", "quick", "--ids", "Q38", "--model", model, "--cap", "1000000")
