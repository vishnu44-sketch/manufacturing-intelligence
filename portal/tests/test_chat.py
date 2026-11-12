"""Ask NOP as chats (like ChatGPT), through the JSON API: the user's chats (grouped by day, newest
first), a chat is only made with its first question, Rename / Remove from list / Restore / Delete,
editing an old question, follow-ups, owner-only access, and showing a chat never calls the AI or
runs SQL. Plus the data migration that put the old questions into one chat per user per day.

agent.ask() and MySQL are fakes (see test_views_ask.py). Run with:
    python -m pytest -q portal/tests/test_chat.py
"""
import datetime
import importlib
import json

import pytest
from django.apps import apps
from django.utils import timezone

from portal.models import Conversation, Question
from portal.rag import agent
from portal.services import CHAT_SIZE, chat_groups
from portal.tests.test_views_ask import (  # noqa: F401
    ANSWER, QUESTION, api_get, api_post, ask, fake_ask, history, mysql, saved_question)

pytestmark = pytest.mark.django_db


def make_chat(user, *texts, minutes_ago=60, title=None, archived=False, **fields):
    """A saved chat of this user with these questions, one minute apart (the last is the newest)."""
    first = timezone.now() - datetime.timedelta(minutes=minutes_ago)
    chat = Conversation.objects.create(user=user, title=title or Conversation.title_from(texts[0]),
                                       created_at=first, updated_at=first, archived=archived)
    for n, text in enumerate(texts):
        saved = saved_question(user, text=text, conversation=chat, **fields)
        at = first + datetime.timedelta(minutes=n)
        Question.objects.filter(pk=saved.pk).update(created_at=at)
        chat.updated_at = at
    chat.save()
    return chat


def chat_list(client):
    return api_get(client, "api_chats").json()


def open_chat(client, chat):
    return api_get(client, "api_chat", chat.pk).json()


def texts(body):
    """The question texts of a chat, in order."""
    return [card["text"] for card in body["cards"]]


# ---------- the chat list ----------

def test_without_chats_the_list_is_empty(client, user, mysql):
    client.force_login(user)

    assert chat_list(client) == {"chats": [], "removed": []}   # the app shows the new-chat screen
    assert mysql == []


def test_the_newest_chat_that_is_not_removed_comes_first(client, user, mysql):
    make_chat(user, "Old chat question", minutes_ago=300)
    newer = make_chat(user, "Newer chat question", minutes_ago=200)
    make_chat(user, "Removed chat question", minutes_ago=100, archived=True)
    client.force_login(user)

    assert chat_list(client)["chats"][0]["id"] == newer.pk      # the app opens this one


def test_a_chat_has_its_questions_oldest_first_and_the_list_only_mine(client, user, other, staff, mysql):
    chat = make_chat(user, "First question", "Second question")
    make_chat(user, "Another chat of mine", minutes_ago=500)
    make_chat(other, "Ravi's private question")
    make_chat(staff, "The boss's question")
    client.force_login(user)

    body, listed = open_chat(client, chat), chat_list(client)

    assert texts(body) == ["First question", "Second question"]          # oldest at the top
    assert body["total"] == 2
    assert [c["title"] for c in listed["chats"]] == ["First question", "Another chat of mine"]
    assert "Ravi" not in json.dumps(listed) and "boss" not in json.dumps(listed)   # never someone else's


def test_the_list_is_grouped_today_yesterday_previous_7_days_older(user):
    now = timezone.now()
    for title, days in [("Today chat", 0), ("Yesterday chat", 1), ("Three days chat", 3),
                        ("Twenty days chat", 20), ("Seven days chat", 7)]:
        Conversation.objects.create(user=user, title=title, updated_at=now - datetime.timedelta(days=days))
    Conversation.objects.create(user=user, title="Removed chat", updated_at=now, archived=True)

    groups = chat_groups(user, now=now)

    assert [(g["label"], [c.title for c in g["chats"]]) for g in groups] == [
        ("Today", ["Today chat"]), ("Yesterday", ["Yesterday chat"]),
        ("Previous 7 days", ["Three days chat", "Seven days chat"]), ("Older", ["Twenty days chat"])]


def test_the_list_has_the_day_groups_in_order(client, user, mysql):
    make_chat(user, "Asked a while ago", minutes_ago=60 * 24 * 30)
    make_chat(user, "Asked just now", minutes_ago=5)
    client.force_login(user)

    chats = chat_list(client)["chats"]

    assert [(c["group"], c["title"]) for c in chats] == [("Today", "Asked just now"), ("Older", "Asked a while ago")]
    assert chats[0]["questions"] == 1 and chats[0]["updated_text"]          # for the chat menu


# ---------- asking ----------

def test_asking_in_a_chat_adds_the_question_there_and_showing_it_again_does_not_ask_again(
        client, user, fake_ask, mysql):
    chat = make_chat(user, "An earlier question")
    client.force_login(user)

    r = ask(client, QUESTION, chat.pk)
    saved = Question.objects.get(text=QUESTION)
    assert r.json()["chat"]["id"] == chat.pk and r.json()["card"]["id"] == saved.pk
    assert saved.conversation == chat
    chat.refresh_from_db()
    assert chat.updated_at == saved.created_at                           # it moves to the top of the list

    body = open_chat(client, chat)
    open_chat(client, chat)                                               # refresh
    assert fake_ask == [QUESTION]                                         # the AI was asked once
    assert texts(body) == ["An earlier question", QUESTION]               # newest at the bottom
    assert Conversation.objects.count() == 1                              # no new chat was made


def test_new_chat_makes_a_chat_only_with_its_first_question(client, user, fake_ask, mysql):
    make_chat(user, "Yesterday's question", minutes_ago=60 * 24)
    client.force_login(user)

    r = ask(client, QUESTION)
    new = Conversation.objects.latest("pk")
    saved = Question.objects.get(text=QUESTION)
    assert Conversation.objects.count() == 2
    assert new.title == QUESTION and saved.conversation == new
    assert r.json()["chat"]["id"] == new.pk

    ask(client, "And the open orders?", new.pk)                          # a second question, same chat
    assert Conversation.objects.count() == 2 and new.questions.count() == 2


def test_a_long_first_question_becomes_a_short_title():
    long = "What were the net sales of every customer in the south region for each NOP month of FY 2026-27?"

    title = Conversation.title_from(long)

    assert len(title) <= Conversation.TITLE_CHARS and title.endswith("…")
    assert long.startswith(title[:-1])
    assert Conversation.title_from("  Open   orders?\n") == "Open orders?"


def test_empty_question_makes_no_chat_and_no_ai_call(client, user, fake_ask):
    client.force_login(user)

    r = ask(client, "   ")

    assert r.status_code == 400 and r.json()["detail"] == "Type a question first."
    assert fake_ask == [] and not Conversation.objects.exists()


# ---------- the chat menu: rename / remove from list / restore / delete ----------

def test_rename_a_chat(client, user, mysql):
    chat = make_chat(user, "Top 5 customers")
    client.force_login(user)

    r = api_post(client, "api_chat_rename", {"title": "  Customer   ranking "}, chat.pk)
    chat.refresh_from_db()

    assert chat.title == "Customer ranking"
    assert r.json()["chat"]["title"] == "Customer ranking"
    assert open_chat(client, chat)["chat"]["title"] == "Customer ranking"


def test_rename_needs_a_title(client, user):
    chat = make_chat(user, "Top 5 customers")
    client.force_login(user)

    r = api_post(client, "api_chat_rename", {"title": "   "}, chat.pk)
    chat.refresh_from_db()

    assert r.status_code == 400 and r.json()["detail"] == "A chat needs a title."
    assert chat.title == "Top 5 customers"


def test_a_long_title_is_cut_at_200_characters(client, user):
    chat = make_chat(user, "Top 5 customers")
    client.force_login(user)

    api_post(client, "api_chat_rename", {"title": "x" * 300}, chat.pk)
    chat.refresh_from_db()

    assert chat.title == "x" * 200


def test_remove_from_list_hides_the_chat_but_history_keeps_it(client, user, mysql):
    keep = make_chat(user, "Chat I keep", minutes_ago=300)
    gone = make_chat(user, "Chat I remove", minutes_ago=100)
    client.force_login(user)

    r = api_post(client, "api_chat_remove", None, gone.pk)
    gone.refresh_from_db()
    assert gone.archived
    assert "was removed from your chats" in r.json()["message"] and "Removed chats" in r.json()["message"]

    listed = chat_list(client)
    assert [c["id"] for c in listed["chats"]] == [keep.pk]               # not in the normal list ...
    assert [c["title"] for c in listed["removed"]] == ["Chat I remove"]  # ... but under "Removed chats"
    assert listed["removed"][0]["questions"] == 1
    assert "Chat I remove" in [q["text"] for q in history(client)["questions"]]   # History keeps it
    assert Question.objects.filter(conversation=gone).count() == 1


def test_a_removed_chat_can_be_opened_and_restored(client, user, mysql):
    chat = make_chat(user, "Chat I remove", archived=True)
    client.force_login(user)

    assert open_chat(client, chat)["chat"]["archived"] is True          # "This chat was removed ..."

    r = api_post(client, "api_chat_restore", None, chat.pk)
    chat.refresh_from_db()
    assert not chat.archived and r.json()["chat"]["archived"] is False
    assert [c["id"] for c in chat_list(client)["chats"]] == [chat.pk]


def test_asking_in_a_removed_chat_brings_it_back(client, user, fake_ask, mysql):
    chat = make_chat(user, "Chat I remove", archived=True)
    client.force_login(user)

    ask(client, QUESTION, chat.pk)
    chat.refresh_from_db()

    assert not chat.archived


def test_delete_hides_the_chat_and_its_questions_but_keeps_the_rows(client, user, mysql):
    """03-Nov: a soft delete - gone for the user everywhere, kept for the audit log."""
    keep = make_chat(user, "Chat I keep", minutes_ago=300)
    gone = make_chat(user, "Delete me one", "Delete me two", minutes_ago=100)
    client.force_login(user)

    r = api_post(client, "api_chat_delete", None, gone.pk)
    lines = [q["text"] for q in history(client)["questions"]]
    gone.refresh_from_db()

    assert gone.deleted_at is not None and gone.deleted_by == user               # marked, not removed
    assert Question.objects.filter(text__startswith="Delete me").count() == 2   # the audit trail stays
    assert r.json() == {"deleted": 2, "message": '"Delete me one" was deleted with its 2 questions.'}
    assert [c["id"] for c in chat_list(client)["chats"]] == [keep.pk]    # the app opens the chat that is left
    assert "Delete me one" not in lines and "Chat I keep" in lines        # gone from History too


def test_delete_needs_a_post(client, user, mysql):
    chat = make_chat(user, "Question one", "Question two")
    client.force_login(user)

    assert api_get(client, "api_chat_delete", chat.pk).status_code == 405
    assert Conversation.objects.filter(pk=chat.pk).exists()


def test_nobody_else_can_open_ask_in_rename_remove_or_delete_my_chat(client, user, other, staff, fake_ask, mysql):
    chat = make_chat(user, "Asha's chat")
    for person in (other, staff):                                         # chats are private, also for admins
        client.force_login(person)
        assert api_get(client, "api_chat", chat.pk).status_code == 404
        assert ask(client, QUESTION, chat.pk).status_code == 404
        for action in ("api_chat_rename", "api_chat_remove", "api_chat_restore", "api_chat_delete"):
            assert api_post(client, action, {"title": "Hacked"}, chat.pk).status_code == 404, action
    chat.refresh_from_db()

    assert fake_ask == []
    assert chat.title == "Asha's chat" and not chat.archived and chat.questions.count() == 1


def test_chat_actions_need_a_sign_in(client, user):
    chat = make_chat(user, "Asha's chat")
    assert api_get(client, "api_chat", chat.pk).status_code == 401
    assert api_get(client, "api_chats").status_code == 401
    for action in ("api_chat_rename", "api_chat_remove", "api_chat_restore", "api_chat_delete"):
        r = api_post(client, action, {"title": "Hacked"}, chat.pk)
        assert r.status_code == 401 and r.json()["detail"] == "Please sign in.", action
    assert Conversation.objects.filter(pk=chat.pk, archived=False, title="Asha's chat").exists()


# ---------- showing a chat: fast, no AI ----------

def test_showing_a_chat_runs_no_sql_and_every_answer_can_load_its_rows(client, user, mysql):
    """The app loads the rows of the newest answer at once and of older ones on "Show rows"."""
    chat = make_chat(user, "Old question one", "Old question two", "Newest question")
    client.force_login(user)

    cards = open_chat(client, chat)["cards"]

    assert mysql == []                                                    # no SQL run to show the chat
    assert all(card["has_rows"] and card["rows_url"] and card["excel_url"] for card in cards)
    client.get(cards[-1]["rows_url"])
    assert len(mysql) == 1                                                # one SQL run for the newest rows


def test_a_long_chat_sends_the_last_questions_and_counts_the_earlier_ones(client, user, mysql):
    chat = make_chat(user, *[f"Chat question {n:02d}" for n in range(CHAT_SIZE + 2)])
    client.force_login(user)

    body = open_chat(client, chat)

    assert body["earlier"] == 2 and body["total"] == CHAT_SIZE + 2       # "2 earlier questions ... in History"
    assert texts(body)[0] == "Chat question 02" and texts(body)[-1] == f"Chat question {CHAT_SIZE + 1}"
    assert mysql == []


def test_refused_and_failed_questions_have_their_message_and_run_nothing(client, user, mysql):
    chat = make_chat(user, "What is the capital of France?", status="refused", sql="",
                     answer=agent.REFUSAL_ANSWER, rows_count=None, sources=[])
    client.force_login(user)

    card = open_chat(client, chat)["cards"][0]

    assert card["status"] == "refused" and card["answer"] == agent.REFUSAL_ANSWER
    assert card["has_rows"] is False and card["excel_url"] == ""
    assert mysql == []


def test_chat_answers_keep_the_backup_note_but_no_token_line(client, user, mysql, monkeypatch):
    monkeypatch.setenv("GROQ_MODEL", "openai/gpt-oss-120b")
    chat = make_chat(user, "Answered by the backup", model="qwen/qwen3.8-27b",
                     sql_tokens=3_000, answer_tokens=700, total_tokens=3_700)
    client.force_login(user)

    card = open_chat(client, chat)["cards"][0]

    assert card["backup_model"] == "qwen/qwen3.8-27b"
    assert card["token_notice"] == ""                                     # only once, right after asking


@pytest.fixture
def fake_ask_with_tokens(monkeypatch):
    """Like fake_ask, but the saved question carries the Groq tokens the real agent saves."""
    def fake(question, user, context=None):
        saved = saved_question(user, text=question, model="openai/gpt-oss-120b",
                               sql_tokens=3_483, answer_tokens=861, total_tokens=4_344)
        return agent.AskResult(text=question, status="ok", answer=ANSWER, question=saved)

    monkeypatch.setattr(agent, "ask", fake)


NOTICE = "This question used 4,344 tokens (SQL 3,483 + answer 861) - openai/gpt-oss-120b"


def test_token_notice_comes_once_right_after_asking(client, user, fake_ask_with_tokens, mysql):
    chat = make_chat(user, "An earlier question", model="openai/gpt-oss-120b",
                     sql_tokens=1_000, answer_tokens=500, total_tokens=1_500)
    client.force_login(user)

    first = ask(client, QUESTION, chat.pk).json()
    later = open_chat(client, chat)                                       # coming back later

    assert first["card"]["token_notice"] == NOTICE                       # the app fades it after 20 s
    assert [card["token_notice"] for card in later["cards"]] == ["", ""]  # never again, no notice for older ones


def test_no_token_notice_when_groq_reported_no_tokens(client, user, fake_ask, mysql):
    client.force_login(user)

    card = ask(client, QUESTION).json()["card"]

    assert card["answer"] == ANSWER and card["token_notice"] == ""


def test_a_saved_answer_names_its_chat(client, user, other, staff, mysql):
    chat = make_chat(user, "First question", "Second question")
    first = chat.questions.order_by("created_at").first()

    client.force_login(user)
    mine = api_get(client, "api_question", first.pk).json()
    client.force_login(staff)
    staff_view = api_get(client, "api_question", first.pk).json()

    assert mine["chat"]["id"] == chat.pk and mine["card"]["text"] == "First question"   # back to the chat
    assert staff_view["chat"] is None                                     # someone else's chat stays private


# ---------- the data migration: old questions -> one chat per user per day ----------

def test_migration_puts_old_questions_into_one_chat_per_user_per_day(user, other):
    migration = importlib.import_module("portal.migrations.0006_conversation")
    india = timezone.get_current_timezone()

    def old(person, text, day, hour):
        saved = saved_question(person, text=text)
        at = timezone.make_aware(datetime.datetime(2026, 10, day, hour, 0), india)
        Question.objects.filter(pk=saved.pk).update(created_at=at)

    old(user, "Mon morning", 5, 9)
    old(user, "Mon evening", 5, 21)
    old(user, "Tue morning", 6, 0)                                        # just after midnight: next day
    old(other, "Ravi on Monday", 5, 10)

    migration.questions_into_chats(apps, None)

    chats = {c.title: c for c in Conversation.objects.all()}
    assert sorted(chats) == ["Mon morning", "Ravi on Monday", "Tue morning"]
    assert sorted(chats["Mon morning"].questions.values_list("text", flat=True)) == ["Mon evening", "Mon morning"]
    assert chats["Mon morning"].user == user and chats["Ravi on Monday"].user == other
    assert timezone.localtime(chats["Mon morning"].updated_at).hour == 21   # its last question
    assert not Question.objects.filter(conversation__isnull=True).exists()


# ---------- edit an old question (like ChatGPT) ----------

def edit(client, question, text):
    return api_post(client, "api_edit", {"question": text}, question.pk)


def test_edit_replaces_the_question_in_place_and_history_keeps_the_old_one(client, user, fake_ask, mysql):
    chat = make_chat(user, "Q1", "Q2", "Q3")
    old = chat.questions.get(text="Q2")
    client.force_login(user)

    r = edit(client, old, "  Q2 edited  ")

    new = Question.objects.get(text="Q2 edited")
    assert fake_ask == ["Q2 edited"]                                     # asked once, as typed (trimmed)
    assert r.status_code == 200
    assert r.json()["replaced"] == old.pk and r.json()["card"]["id"] == new.pk
    assert r.json()["chat"]["id"] == chat.pk and r.json()["card"]["edited"] is True
    old.refresh_from_db()
    assert old.replaced_by == new and new.conversation == chat
    body = open_chat(client, chat)
    assert texts(body) == ["Q1", "Q2 edited", "Q3"]                      # same place, old one hidden
    assert body["cards"][1]["edited"] is True                            # "· edited"
    lines = {q["text"]: q for q in history(client)["questions"]}
    assert lines["Q2"]["edited"] is True                                  # old one still listed, marked
    assert lines["Q2 edited"]["edited"] is False


def test_an_edit_returns_the_card_with_its_rows_and_token_notice(client, user, fake_ask_with_tokens, mysql):
    chat = make_chat(user, "Q1", "Q2")
    client.force_login(user)

    card = edit(client, chat.questions.get(text="Q1"), "Q1 again").json()["card"]

    assert card["token_notice"] == NOTICE                                # one-time notice, as for a new question
    assert card["has_rows"] and card["rows_url"]                         # the app loads its rows at once
    assert mysql == []


def test_only_the_owner_can_edit_and_an_edited_version_cannot_be_edited_again(client, user, other, fake_ask, mysql):
    chat = make_chat(user, "Mine")
    mine = chat.questions.get()
    assert edit(client, mine, "Stranger").status_code == 401
    client.force_login(other)
    assert edit(client, mine, "Hacked").status_code == 404
    client.force_login(user)
    edit(client, mine, "Mine, edited")
    assert edit(client, mine, "Again").status_code == 404                # already replaced
    assert api_get(client, "api_edit", mine.pk).status_code == 405        # POST only
    assert fake_ask == ["Mine, edited"]


@pytest.mark.parametrize("text, message", [
    ("   ", "Type the edited question first."),
    ("x" * 1001, "Please keep the question under 1000 characters."),
])
def test_an_empty_or_too_long_edit_asks_nothing(client, user, fake_ask, mysql, text, message):
    chat = make_chat(user, "Keep me")
    client.force_login(user)

    r = edit(client, chat.questions.get(), text)

    assert r.status_code == 400 and r.json()["detail"] == message
    assert fake_ask == []
    assert not Question.objects.filter(replaced_by__isnull=False).exists()


def test_editing_the_first_question_retitles_the_chat_unless_it_was_renamed(client, user, fake_ask, mysql):
    plain = make_chat(user, "Old first question", "Second")
    renamed = make_chat(user, "Another first", title="My own title")
    client.force_login(user)

    edit(client, plain.questions.get(text="Old first question"), "New first question")
    edit(client, plain.questions.get(text="Second"), "Second, edited")
    edit(client, renamed.questions.get(), "Changed")

    plain.refresh_from_db(); renamed.refresh_from_db()
    assert plain.title == "New first question"
    assert renamed.title == "My own title"


def test_deleting_a_chat_also_hides_the_edited_away_versions(client, user, fake_ask, mysql):
    chat = make_chat(user, "Q1")
    client.force_login(user)
    edit(client, chat.questions.get(), "Q1 edited")
    assert Question.objects.filter(conversation=chat).count() == 2

    api_post(client, "api_chat_delete", None, chat.pk)

    assert history(client)["questions"] == []                        # both versions gone from History
    assert Question.objects.filter(user=user).count() == 2           # and kept for the audit log


def test_a_no_data_answer_has_its_own_status(client, user, mysql):
    chat = make_chat(user, "profit this year?", status="nodata", sql="", rows_count=None,
                     answer="The NOP data does not have this: profit needs costs.")
    client.force_login(user)

    assert open_chat(client, chat)["cards"][0]["status"] == "nodata"     # DATA NOT AVAILABLE
    assert history(client)["questions"][0]["status"] == "nodata"          # NO DATA


def test_the_newest_chat_is_first_in_its_group(client, user, mysql):
    """A new chat goes to the TOP of the list (not the bottom) - also with the question counts."""
    make_chat(user, "Oldest today", minutes_ago=180)
    make_chat(user, "Middle today", minutes_ago=120)
    make_chat(user, "Newest today", minutes_ago=30)

    groups = chat_groups(user)

    assert [c.title for c in groups[0]["chats"]] == ["Newest today", "Middle today", "Oldest today"]
    client.force_login(user)
    assert [c["title"] for c in chat_list(client)["chats"]] == ["Newest today", "Middle today", "Oldest today"]


def test_removed_chats_are_listed_newest_first(client, user, mysql):
    make_chat(user, "Removed long ago", minutes_ago=300, archived=True)
    make_chat(user, "Removed recently", minutes_ago=10, archived=True)
    make_chat(user, "Still listed", minutes_ago=5)
    client.force_login(user)

    assert [c["title"] for c in chat_list(client)["removed"]] == ["Removed recently", "Removed long ago"]


def test_the_api_is_never_cached_so_back_never_shows_old_data(client, user, mysql):
    chat = make_chat(user, "A question")
    client.force_login(user)

    for r in (api_get(client, "api_chat", chat.pk), api_get(client, "api_chats"),
              api_get(client, "api_question", chat.questions.get().pk), client.get("/c/1")):
        assert "no-store" in r["Cache-Control"]


# ---------- follow-up questions ----------

def test_a_follow_up_in_a_chat_passes_its_last_3_answered_questions(client, user, fake_ask, mysql):
    chat = make_chat(user, "Q1", "Q2", "Q3", "Q4")
    refused = saved_question(user, text="weather?", status="refused", conversation=chat)
    client.force_login(user)

    ask(client, "and for Sep?", chat.pk)

    assert fake_ask.contexts[-1] == ["Q2", "Q3", "Q4"]          # oldest first; refused one left out
    assert refused.text not in fake_ask.contexts[-1]


def test_the_first_question_of_a_new_chat_has_no_context(client, user, fake_ask, mysql):
    make_chat(user, "An older chat")
    client.force_login(user)

    ask(client, "Top customers?")

    assert fake_ask.contexts == [[]]


def test_an_edit_sees_only_the_questions_before_it(client, user, fake_ask, mysql):
    chat = make_chat(user, "Q1", "Q2", "Q3")
    client.force_login(user)

    edit(client, chat.questions.get(text="Q2"), "Q2 better")

    assert fake_ask.contexts == [["Q1"]]


def test_understood_as_comes_with_the_answer_and_in_history_and_ask_again_uses_it(client, user, mysql):
    chat = make_chat(user, "and for Sep?", understood_as="Top 5 customers by invoice value in Sep 2026")
    client.force_login(user)

    card = open_chat(client, chat)["cards"][0]
    line = history(client)["questions"][0]

    assert card["understood_as"] == "Top 5 customers by invoice value in Sep 2026"
    assert line["understood_as"] == "Top 5 customers by invoice value in Sep 2026"
    assert line["ask_again"] == "Top 5 customers by invoice value in Sep 2026"
