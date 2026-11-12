"""The streamed Ask page: POST /api/ask/stream (api.ask_stream) sends the question's progress as JSON lines -
the steps as they start, the final answer piece by piece, then the same card /api/ask gives.

The AI is a fake whose replies can also be streamed word by word (StreamingFakeAI); MySQL and the notes search
are the fakes of test_agent.py. Checks: the order of the events, the saved Question is the same as /api/ask
saves, the rate-limit rules before the first piece, the "rows only" answer after a broken stream, the
sign-in / CSRF / checks, and a browser that leaves early.
Run with:  python -m pytest -q portal/tests/test_stream.py
"""
import json
import re

import pytest
from django.conf import settings
from django.test import Client
from django.urls import reverse
from langchain_core.messages import AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk

from portal import api
from portal.lc import llm
from portal.models import Conversation, Question
from portal.rag import agent
from portal.tests.test_agent import (ANSWER, BACKUP, DOC_ANSWER, DOC_QUESTION, GOOD_SQL, MAIN, PDF_HITS,  # noqa: F401
                                     ROWS, FakeAI, FakeChatModel, daily_limit_error, mysql, rate_limit_error,
                                     use_pdf_hits)

pytestmark = pytest.mark.django_db

QUESTION = "Top customers in Aug 2026?"
DATA_STEPS = ["Search the PDFs", "Search the notes in Qdrant", "Pick the tables and columns", "Write the SQL (AI)",
              "Check the SQL (guard and checks)", "Run the SQL on MySQL", "Write the answer (AI)"]


class BreaksAfter(str):
    """A reply whose stream fails after this many words (the network dropped while the answer was written)."""

    def __new__(cls, text, words):
        reply = super().__new__(cls, text)
        reply.words = words
        return reply


class StreamingFakeChatModel(FakeChatModel):
    """FakeChatModel that can also stream: the reply comes word by word, Groq's token count in the last piece."""

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        self.ai.streamed.append(len(self.ai.calls) + 1)  # the number of the call that is streamed (1 = the first)
        message = self.ai.reply(messages, self.model, self.max_tokens)
        words = re.findall(r"\S+\s*", message.content)
        for n, word in enumerate(words, start=1):
            yield ChatGenerationChunk(message=AIMessageChunk(content=word))
            if isinstance(self.ai.last_text, BreaksAfter) and n == self.ai.last_text.words:
                raise ConnectionError("the stream broke")
        yield ChatGenerationChunk(message=AIMessageChunk(content="", usage_metadata=message.usage_metadata,
                                                         response_metadata=message.response_metadata))


class StreamingFakeAI(FakeAI):
    """FakeAI with StreamingFakeChatModel. streamed = which calls were streamed (1-based)."""

    def __init__(self, replies):
        super().__init__(replies)
        self.streamed = []
        self.last_text = None

    def make_llm(self, model, max_tokens, effort):
        return StreamingFakeChatModel(ai=self, model=model, max_tokens=max_tokens)

    def reply(self, messages, model, max_tokens):
        upcoming = self.replies[0] if self.replies else None
        self.last_text = upcoming[0] if isinstance(upcoming, tuple) else upcoming
        return super().reply(messages, model, max_tokens)


def fake_ai(monkeypatch, replies):
    fake = StreamingFakeAI(replies)
    monkeypatch.setattr(llm, "make_llm", fake.make_llm)
    return fake


@pytest.fixture
def signed_in(client, user):
    client.force_login(user)
    return client


def stream(client, question=QUESTION, chat_id=None):
    """POST to the stream; -> (the response, its events) - the whole stream read."""
    r = client.post(reverse("api_ask_stream"), data=json.dumps({"question": question, "chat_id": chat_id}),
                    content_type="application/json")
    if not r.streaming:
        return r, []
    return r, [json.loads(line) for line in b"".join(r.streaming_content).decode("utf-8").splitlines()]


def kinds(events):
    """The event types in order, with runs of the same type folded: ['step', 'token', 'done']."""
    folded = []
    for event in events:
        if not folded or folded[-1] != event["type"]:
            folded.append(event["type"])
    return folded


# ---------- the events ----------

def test_the_stream_sends_the_steps_then_the_answer_word_by_word_then_the_card(monkeypatch, mysql, signed_in):
    mysql.results = [ROWS]
    fake = fake_ai(monkeypatch, [(GOOD_SQL, 3000), (ANSWER, 800)])

    r, events = stream(signed_in)

    assert r.status_code == 200 and r["Content-Type"] == "application/x-ndjson"
    assert r["X-Accel-Buffering"] == "no" and "no-cache" in r["Cache-Control"]
    assert kinds(events) == ["step", "token", "done"]
    assert [e["label"] for e in events if e["type"] == "step"] == DATA_STEPS
    tokens = [e["text"] for e in events if e["type"] == "token"]
    assert len(tokens) > 3 and "".join(tokens) == ANSWER                     # word by word
    card = events[-1]["card"]
    assert card["answer"] == ANSWER and card["status"] == "ok" and card["has_rows"] is True
    assert card["token_notice"].startswith("This question used 3,800 tokens (SQL 3,000 + answer 800)")
    assert events[-1]["chat"]["title"] == QUESTION
    assert fake.streamed == [2]                                              # only the answer call is streamed


def test_the_streamed_question_is_saved_as_api_ask_saves_it(monkeypatch, mysql, signed_in):
    mysql.results = [ROWS, ROWS]
    fake_ai(monkeypatch, [(GOOD_SQL, 3000), (ANSWER, 800), (GOOD_SQL, 3000), (ANSWER, 800)])

    plain = signed_in.post(reverse("api_ask"), data=json.dumps({"question": QUESTION, "chat_id": None}),
                           content_type="application/json").json()
    _, events = stream(signed_in)

    first, second = Question.objects.order_by("pk")
    fields = ["text", "sql", "answer", "rows_count", "status", "error", "sources", "tries", "model", "sql_tokens",
              "answer_tokens", "total_tokens", "understood_as"]
    assert [getattr(second, f) for f in fields] == [getattr(first, f) for f in fields]
    assert set(second.step_secs) == set(first.step_secs)                     # the same time steps
    assert second.conversation is not None and second.conversation != first.conversation
    streamed = events[-1]["card"]
    for key in ("id", "created_at", "created_text", "secs", "time_steps", "rows_url", "excel_url"):
        streamed.pop(key), plain["card"].pop(key)
    assert streamed == plain["card"]


class UsageTwiceChatModel(StreamingFakeChatModel):
    """Groq on 03-Nov: the token count of the whole reply came twice at the end of the stream (on the last piece
    with text and on an empty piece after it)."""

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        pieces = list(super()._stream(messages, stop, run_manager, **kwargs))
        last = pieces[-1].message
        yield from pieces[:-2]
        yield ChatGenerationChunk(message=AIMessageChunk(content=pieces[-2].message.content,
                                                         usage_metadata=last.usage_metadata))
        yield pieces[-1]


def test_a_token_count_sent_twice_is_counted_once(monkeypatch, mysql, signed_in):
    mysql.results = [ROWS]
    fake = fake_ai(monkeypatch, [(GOOD_SQL, 3000), (ANSWER, 800)])
    monkeypatch.setattr(llm, "make_llm", lambda model, max_tokens, effort: UsageTwiceChatModel(
        ai=fake, model=model, max_tokens=max_tokens))

    _, events = stream(signed_in)

    assert "".join(e["text"] for e in events if e["type"] == "token") == ANSWER
    saved = Question.objects.get()
    assert (saved.sql_tokens, saved.answer_tokens, saved.total_tokens) == (3000, 800, 3800)   # not 1,600


def test_the_plain_api_ask_never_streams(monkeypatch, mysql, signed_in):
    mysql.results = [ROWS]
    fake = fake_ai(monkeypatch, [(GOOD_SQL, 3000), (ANSWER, 800)])

    r = signed_in.post(reverse("api_ask"), data=json.dumps({"question": QUESTION, "chat_id": None}),
                       content_type="application/json")

    assert r.status_code == 200 and not r.streaming and fake.streamed == []


def test_a_document_question_streams_its_answer(monkeypatch, mysql, signed_in):
    use_pdf_hits(monkeypatch, PDF_HITS)
    fake_ai(monkeypatch, [("documents", 300), (DOC_ANSWER, 900)])

    _, events = stream(signed_in, DOC_QUESTION)

    assert [e["label"] for e in events if e["type"] == "step"] == ["Search the PDFs", "Write the answer (AI)"]
    assert "".join(e["text"] for e in events if e["type"] == "token") == DOC_ANSWER
    card = events[-1]["card"]
    assert card["status"] == "docs" and card["sources"][0] == {"kind": "pdf", "heading": "Warranty and Returns Policy, page 1"}
    assert Question.objects.get().total_tokens == 1200


def test_a_not_in_documents_reply_is_never_streamed_as_text(monkeypatch, mysql, signed_in):
    use_pdf_hits(monkeypatch, PDF_HITS)
    fake_ai(monkeypatch, ["documents", "NOT_IN_DOCUMENTS: the documents do not give the price list"])

    _, events = stream(signed_in, DOC_QUESTION)

    assert kinds(events) == ["step", "done"]
    assert events[-1]["card"]["answer"] == "The documents do not have this: the documents do not give the price list."


def test_a_retry_step_says_which_try_it_is(monkeypatch, mysql, signed_in):
    from portal.rag import warehouse
    mysql.results = [warehouse.QueryError("(1054) Unknown column 'il.amount'"), ROWS]
    fake_ai(monkeypatch, [GOOD_SQL, GOOD_SQL, ANSWER])

    _, events = stream(signed_in)

    labels = [e["label"] for e in events if e["type"] == "step"]
    assert "Write the SQL (AI) - try 2" in labels and labels.count("Run the SQL on MySQL") == 2


# ---------- the rules for errors ----------

def test_a_rate_limit_before_the_first_piece_waits_and_tries_again(monkeypatch, mysql, signed_in):
    monkeypatch.setattr(agent.time, "sleep", lambda secs: None)
    mysql.results = [ROWS]
    fake = fake_ai(monkeypatch, [(GOOD_SQL, 3000), rate_limit_error(2), (ANSWER, 800)])

    _, events = stream(signed_in)

    assert "".join(e["text"] for e in events if e["type"] == "token") == ANSWER
    saved = Question.objects.get()
    assert saved.status == "ok" and saved.answer == ANSWER and saved.answer_tokens == 800
    assert fake.streamed == [2, 3]                                           # the same streamed call, again


def test_a_daily_limit_before_the_first_piece_moves_to_the_backup_model(monkeypatch, mysql, signed_in):
    monkeypatch.setenv("GROQ_MODEL", MAIN)
    monkeypatch.setenv("GROQ_FALLBACK_MODEL", BACKUP)
    mysql.results = [ROWS]
    fake = fake_ai(monkeypatch, [(GOOD_SQL, 3000), daily_limit_error(), (ANSWER, 700)])

    _, events = stream(signed_in)

    assert events[-1]["card"]["answer"] == ANSWER and fake.models[-1] == BACKUP
    assert Question.objects.get().model == BACKUP


def test_a_stream_that_breaks_after_the_first_piece_shows_the_rows_without_a_summary(monkeypatch, mysql, signed_in):
    mysql.results = [ROWS]
    fake_ai(monkeypatch, [(GOOD_SQL, 3000), (BreaksAfter(ANSWER, 3), 800)])

    _, events = stream(signed_in)

    shown = "".join(e["text"] for e in events if e["type"] == "token")
    assert shown and ANSWER.startswith(shown) and shown != ANSWER           # part of it was on screen
    card = events[-1]["card"]
    assert card["answer"] == agent.ROWS_ONLY_ANSWER and card["has_rows"] is True   # never half an answer
    saved = Question.objects.get()
    assert saved.status == "ok" and saved.answer == agent.ROWS_ONLY_ANSWER
    assert saved.error == f"Answer not written: {agent.STREAM_BROKEN}"


def test_a_broken_document_answer_is_a_friendly_error_not_half_an_answer(monkeypatch, mysql, signed_in):
    use_pdf_hits(monkeypatch, PDF_HITS)
    fake_ai(monkeypatch, ["documents", BreaksAfter(DOC_ANSWER, 4)])

    _, events = stream(signed_in, DOC_QUESTION)

    card = events[-1]["card"]
    assert card["status"] == "error" and card["answer"] == agent.STREAM_BROKEN
    assert Question.objects.get().answer == agent.STREAM_BROKEN


def test_a_failure_outside_the_question_is_an_error_line(monkeypatch, mysql, signed_in):
    mysql.results = [ROWS]
    fake_ai(monkeypatch, [GOOD_SQL, ANSWER])

    def no_chat(*args):
        raise RuntimeError("the History database went away")
    monkeypatch.setattr(Conversation.objects, "create", no_chat)

    _, events = stream(signed_in)

    assert events[-1] == {"type": "error", "message": agent.UNEXPECTED}
    assert "done" not in kinds(events)


# like a real server: no test transaction around it (closing the response closes the database link, as it should)
@pytest.mark.django_db(transaction=True)
def test_the_question_is_still_saved_when_the_browser_leaves_early(monkeypatch, mysql, signed_in):
    mysql.results = [ROWS]
    fake_ai(monkeypatch, [(GOOD_SQL, 3000), (ANSWER, 800)])

    r = signed_in.post(reverse("api_ask_stream"), data=json.dumps({"question": QUESTION, "chat_id": None}),
                       content_type="application/json")
    first = json.loads(next(iter(r.streaming_content)))
    r.close()                                                                # the browser left after one line

    assert first == {"type": "step", "label": "Search the PDFs"}
    saved = Question.objects.get()
    assert saved.status == "ok" and saved.answer == ANSWER and saved.total_tokens == 3800
    assert saved.conversation is not None


# ---------- the same checks as /api/ask ----------

def test_the_stream_needs_a_sign_in_and_says_so_in_json(client, mysql):
    r, _ = stream(client)

    assert r.status_code == 401 and r.json()["detail"] == "Please sign in."


def test_the_stream_needs_the_csrf_token(user, mysql, monkeypatch):
    fake = fake_ai(monkeypatch, [])
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)

    no_token, _ = stream(client)
    assert no_token.status_code == 403 and "CSRF" in no_token.json()["detail"]

    token = client.get(reverse("api_csrf")).json()["csrfToken"]
    mysql.results = [ROWS]
    fake.replies = [GOOD_SQL, ANSWER]
    r = client.post(reverse("api_ask_stream"), data=json.dumps({"question": QUESTION, "chat_id": None}),
                    content_type="application/json", HTTP_X_CSRFTOKEN=token)
    assert r.status_code == 200 and r.streaming
    assert json.loads(b"".join(r.streaming_content).splitlines()[-1])["type"] == "done"
    assert settings.CSRF_COOKIE_NAME in client.cookies


def test_the_stream_checks_the_question_and_the_chat_before_anything_is_sent(monkeypatch, mysql, signed_in, other):
    fake = fake_ai(monkeypatch, [])
    theirs = Conversation.objects.create(user=other, title="Theirs")

    empty, _ = stream(signed_in, "   ")
    too_long, _ = stream(signed_in, "x" * (agent.MAX_QUESTION_CHARS + 1))
    not_mine, _ = stream(signed_in, QUESTION, theirs.pk)
    wrong_method = signed_in.get(reverse("api_ask_stream"))

    assert (empty.status_code, empty.json()["detail"]) == (400, "Type a question first.")
    assert too_long.status_code == 400 and not_mine.status_code == 404 and wrong_method.status_code == 405
    assert fake.calls == [] and Question.objects.count() == 0


def test_the_stream_continues_a_chat(monkeypatch, mysql, signed_in, user):
    mysql.results = [ROWS]
    fake_ai(monkeypatch, [GOOD_SQL, ANSWER])
    chat = Conversation.objects.create(user=user, title="Sales")

    _, events = stream(signed_in, QUESTION, chat.pk)

    assert events[-1]["chat"]["id"] == chat.pk
    assert Question.objects.get().conversation == chat


def test_the_lines_are_one_json_object_each():
    assert api._line({"type": "token", "text": "a\nb"}) == b'{"type": "token", "text": "a\\nb"}\n'
