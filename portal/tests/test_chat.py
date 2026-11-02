"""Ask NOP as chats (like ChatGPT): the user's chats on the left (grouped by day), the open chat on
the right, "New chat" (a chat is only made with its first question), Rename / Remove from list /
Delete, owner-only access, and showing a chat never calls the AI - only its newest answer runs its
SQL again. Plus the data migration that put the old questions into one chat per user per day.

agent.ask() and MySQL are fakes (see test_views_ask.py). Run with:
    python -m pytest -q portal/tests/test_chat.py
"""
import datetime
import importlib

import pytest
from django.apps import apps
from django.urls import reverse
from django.utils import timezone

from portal.models import Conversation, Question
from portal.rag import agent
from portal.tests.test_views_ask import ANSWER, QUESTION, fake_ask, mysql, saved_question  # noqa: F401
from portal.views import CHAT_SIZE, _chat_groups

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


def chat_url(chat):
    return reverse("ask_chat", args=[chat.pk])


# ---------- opening the Ask page ----------

def test_without_chats_the_ask_page_is_the_new_chat_screen(client, user, mysql):
    client.force_login(user)

    r = client.get(reverse("ask"))
    page = r.content.decode()

    assert r.status_code == 200
    assert "Ask a question about NOP data" in page and "No chats yet" in page
    assert f'href="{reverse("ask_new")}"' in page                        # the "New chat" button
    assert '<textarea id="q" name="question"' in page and ">Ask</button>" in page
    assert f'action="{reverse("ask")}"' in page                          # asking here starts a chat
    assert "AI usage (this app)" not in page                             # the usage box is on History only
    assert mysql == []


def test_ask_opens_the_most_recently_used_chat_that_is_not_removed(client, user, mysql):
    make_chat(user, "Old chat question", minutes_ago=300)
    newer = make_chat(user, "Newer chat question", minutes_ago=200)
    make_chat(user, "Removed chat question", minutes_ago=100, archived=True)
    client.force_login(user)

    r = client.get(reverse("ask"))

    assert r.status_code == 302 and r.url == chat_url(newer)


def test_a_chat_shows_its_questions_oldest_first_and_the_list_only_mine(client, user, other, staff, mysql):
    chat = make_chat(user, "First question", "Second question")
    make_chat(user, "Another chat of mine", minutes_ago=500)
    make_chat(other, "Ravi's private question")
    make_chat(staff, "The boss's question")
    client.force_login(user)

    page = client.get(chat_url(chat)).content.decode()

    assert page.index("First question") < page.index("Second question")   # oldest at the top
    assert "2 questions" in page
    assert "Another chat of mine" in page                                 # my other chat in the list
    assert "Ravi" not in page and "boss" not in page                      # never someone else's
    assert 'class="chat-row active"' in page and 'aria-current="page"' in page
    assert page.index("Second question") < page.index('id="composer"')    # the question box at the bottom
    assert f'action="{chat_url(chat)}"' in page                           # asking here adds to this chat


def test_the_list_is_grouped_today_yesterday_previous_7_days_older(user):
    now = timezone.now()
    for title, days in [("Today chat", 0), ("Yesterday chat", 1), ("Three days chat", 3),
                        ("Twenty days chat", 20), ("Seven days chat", 7)]:
        Conversation.objects.create(user=user, title=title, updated_at=now - datetime.timedelta(days=days))
    Conversation.objects.create(user=user, title="Removed chat", updated_at=now, archived=True)

    groups = _chat_groups(user, now=now)

    assert [(g["label"], [c.title for c in g["chats"]]) for g in groups] == [
        ("Today", ["Today chat"]), ("Yesterday", ["Yesterday chat"]),
        ("Previous 7 days", ["Three days chat", "Seven days chat"]), ("Older", ["Twenty days chat"])]


def test_the_page_shows_the_day_groups_in_order(client, user, mysql):
    make_chat(user, "Asked a while ago", minutes_ago=60 * 24 * 30)
    newest = make_chat(user, "Asked just now", minutes_ago=5)
    client.force_login(user)

    page = client.get(chat_url(newest)).content.decode()

    assert page.index(">Today<") < page.index("Asked just now") < page.index(">Older<") < page.index("Asked a while ago")


# ---------- asking ----------

def test_asking_in_a_chat_adds_the_question_there_and_a_refresh_does_not_ask_again(client, user, fake_ask, mysql):
    chat = make_chat(user, "An earlier question")
    client.force_login(user)

    r = client.post(chat_url(chat), {"question": QUESTION})
    saved = Question.objects.get(text=QUESTION)
    assert r.url == f"{chat_url(chat)}#q-{saved.pk}"
    assert saved.conversation == chat
    chat.refresh_from_db()
    assert chat.updated_at == saved.created_at                           # it moves to the top of the list

    page = client.get(r.url).content.decode()
    client.get(r.url)                                                     # refresh
    assert fake_ask == [QUESTION]                                         # the AI was asked once
    assert page.index("An earlier question") < page.index(f'id="q-{saved.pk}"')   # newest at the bottom
    assert "data-chat-newest" in page[page.index(f'id="q-{saved.pk}"'):][:80]
    assert Conversation.objects.count() == 1                              # no new chat was made


def test_new_chat_makes_a_chat_only_with_its_first_question(client, user, fake_ask, mysql):
    make_chat(user, "Yesterday's question", minutes_ago=60 * 24)
    client.force_login(user)

    page = client.get(reverse("ask_new")).content.decode()               # the empty "New chat" screen
    assert Conversation.objects.count() == 1                              # nothing made yet
    assert "Ask a question about NOP data" in page and f'action="{reverse("ask")}"' in page

    r = client.post(reverse("ask"), {"question": QUESTION})
    new = Conversation.objects.latest("pk")
    saved = Question.objects.get(text=QUESTION)
    assert Conversation.objects.count() == 2
    assert new.title == QUESTION and saved.conversation == new
    assert r.url == f"{chat_url(new)}#q-{saved.pk}"

    client.post(chat_url(new), {"question": "And the open orders?"})     # a second question, same chat
    assert Conversation.objects.count() == 2 and new.questions.count() == 2


def test_a_long_first_question_becomes_a_short_title():
    long = "What were the net sales of every customer in the south region for each NOP month of FY 2026-27?"

    title = Conversation.title_from(long)

    assert len(title) <= Conversation.TITLE_CHARS and title.endswith("…")
    assert long.startswith(title[:-1])
    assert Conversation.title_from("  Open   orders?\n") == "Open orders?"


def test_empty_question_makes_no_chat_and_no_ai_call(client, user, fake_ask):
    client.force_login(user)

    r = client.post(reverse("ask"), {"question": "   "})

    assert r.status_code == 200 and "Type a question first." in r.content.decode()
    assert fake_ask == [] and not Conversation.objects.exists()


# ---------- the chat menu: rename / remove from list / delete ----------

def test_rename_a_chat(client, user, mysql):
    chat = make_chat(user, "Top 5 customers")
    client.force_login(user)

    r = client.post(reverse("chat_rename", args=[chat.pk]), {"title": "  Customer   ranking ", "next": chat_url(chat)})
    chat.refresh_from_db()

    assert chat.title == "Customer ranking"
    assert r.url == chat_url(chat)
    page = client.get(chat_url(chat)).content.decode()
    assert "Customer ranking" in page


def test_rename_needs_a_title_and_ignores_an_outside_next(client, user):
    chat = make_chat(user, "Top 5 customers")
    client.force_login(user)

    r = client.post(reverse("chat_rename", args=[chat.pk]), {"title": "   ", "next": "https://evil.example/"})
    chat.refresh_from_db()

    assert chat.title == "Top 5 customers"
    assert r.url == chat_url(chat)                                        # never to another site


def test_remove_from_list_hides_the_chat_but_history_keeps_it(client, user, mysql):
    keep = make_chat(user, "Chat I keep", minutes_ago=300)
    gone = make_chat(user, "Chat I remove", minutes_ago=100)
    client.force_login(user)

    r = client.post(reverse("chat_remove", args=[gone.pk]), {"next": chat_url(gone)})
    gone.refresh_from_db()
    assert gone.archived
    assert r.url == reverse("ask")                                        # not back into the removed chat
    assert client.get(reverse("ask")).url == chat_url(keep)               # /ask/ now opens the other chat

    page = client.get(chat_url(keep)).content.decode()
    groups = page[page.index('class="chats-scroll"'):page.index("Removed chats")]
    assert "Chat I remove" not in groups                                  # not in the normal list ...
    assert "Removed chats (1)" in page                                    # ... but under "Removed chats"
    assert "Chat I remove" in client.get(reverse("history")).content.decode()   # History keeps it
    assert Question.objects.filter(conversation=gone).count() == 1


def test_a_removed_chat_can_be_opened_and_restored(client, user, mysql):
    chat = make_chat(user, "Chat I remove", archived=True)
    client.force_login(user)

    page = client.get(chat_url(chat)).content.decode()
    assert "This chat was removed from your list." in page and "Restore it" in page

    r = client.post(reverse("chat_restore", args=[chat.pk]))
    chat.refresh_from_db()
    assert not chat.archived and r.url == chat_url(chat)


def test_asking_in_a_removed_chat_brings_it_back(client, user, fake_ask, mysql):
    chat = make_chat(user, "Chat I remove", archived=True)
    client.force_login(user)

    client.post(chat_url(chat), {"question": QUESTION})
    chat.refresh_from_db()

    assert not chat.archived


def test_delete_removes_the_chat_and_its_questions_for_good(client, user, mysql):
    keep = make_chat(user, "Chat I keep", minutes_ago=300)
    gone = make_chat(user, "Delete me one", "Delete me two", minutes_ago=100)
    client.force_login(user)

    r = client.post(reverse("chat_delete", args=[gone.pk]), {"next": chat_url(gone)}, follow=True)
    page = r.content.decode()
    history = client.get(reverse("history")).content.decode()

    assert not Conversation.objects.filter(pk=gone.pk).exists()
    assert not Question.objects.filter(text__startswith="Delete me").exists()
    assert "was deleted with its 2 questions" in page
    assert r.redirect_chain[-1][0] == chat_url(keep)                      # /ask/ -> the chat that is left
    assert "Delete me" not in history and "Chat I keep" in history        # gone from History too
    assert Conversation.objects.filter(pk=keep.pk).exists()


def test_delete_asks_first_and_needs_a_post(client, user, mysql):
    chat = make_chat(user, "Question one", "Question two")
    client.force_login(user)

    page = client.get(chat_url(chat)).content.decode()

    assert 'data-confirm="Delete this chat and its 2 questions permanently? This cannot be undone."' in page
    assert client.get(reverse("chat_delete", args=[chat.pk])).status_code == 405
    assert Conversation.objects.filter(pk=chat.pk).exists()


def test_nobody_else_can_open_ask_in_rename_remove_or_delete_my_chat(client, user, other, staff, fake_ask, mysql):
    chat = make_chat(user, "Asha's chat")
    for person in (other, staff):                                         # chats are private, also for admins
        client.force_login(person)
        assert client.get(chat_url(chat)).status_code == 404
        assert client.post(chat_url(chat), {"question": QUESTION}).status_code == 404
        for action in ("chat_rename", "chat_remove", "chat_restore", "chat_delete"):
            assert client.post(reverse(action, args=[chat.pk]), {"title": "Hacked"}).status_code == 404, action
    chat.refresh_from_db()

    assert fake_ask == []
    assert chat.title == "Asha's chat" and not chat.archived and chat.questions.count() == 1


def test_chat_pages_and_actions_need_a_login(client, user):
    chat = make_chat(user, "Asha's chat")
    for url in (chat_url(chat), reverse("ask_new")):
        r = client.get(url)
        assert r.status_code == 302 and r.url.startswith(reverse("login")), url
    for action in ("chat_rename", "chat_remove", "chat_restore", "chat_delete"):
        r = client.post(reverse(action, args=[chat.pk]))
        assert r.status_code == 302 and r.url.startswith(reverse("login")), action
    assert Conversation.objects.filter(pk=chat.pk, archived=False).exists()


# ---------- showing a chat: fast, no AI ----------

def test_only_the_newest_answer_runs_its_sql_again(client, user, mysql):
    chat = make_chat(user, "Old question one", "Old question two", "Newest question")
    old1, old2, newest = chat.questions.order_by("created_at")
    client.force_login(user)

    page = client.get(chat_url(chat)).content.decode()

    assert len(mysql) == 1                                                # one SQL run for the whole chat
    assert "Aurora Fluid Power Limited" in page                           # the newest rows table
    for old in (old1, old2):                                              # older answers: link to their page
        assert f'href="{reverse("ask_result", args=[old.pk])}">Show rows</a>' in page
    assert f'href="{reverse("ask_result", args=[newest.pk])}">Show rows' not in page
    assert page.count("Download Excel") == 3


def test_a_long_chat_shows_the_last_questions_and_points_to_history(client, user, mysql):
    chat = make_chat(user, *[f"Chat question {n:02d}" for n in range(CHAT_SIZE + 2)])
    client.force_login(user)

    page = client.get(chat_url(chat)).content.decode()

    assert "2 earlier questions of this chat are in" in page
    assert f"{CHAT_SIZE + 2} questions" in page
    assert "Chat question 00" not in page.split('class="thread"')[1] and "Chat question 21" in page
    assert len(mysql) == 1


def test_refused_and_failed_questions_show_their_message_and_run_nothing(client, user, mysql):
    chat = make_chat(user, "What is the capital of France?", status="refused", sql="",
                     answer=agent.REFUSAL_ANSWER, rows_count=None, sources=[])
    client.force_login(user)

    page = client.get(chat_url(chat)).content.decode()

    assert "NOT A NOP DATA QUESTION" in page and agent.REFUSAL_ANSWER in page
    assert "Show rows" not in page and "Download Excel" not in page
    assert mysql == []


def test_chat_answers_keep_the_backup_note_but_no_token_line(client, user, mysql, monkeypatch):
    monkeypatch.setenv("GROQ_MODEL", "openai/gpt-oss-120b")
    chat = make_chat(user, "Answered by the backup", model="qwen/qwen3.8-27b",
                     sql_tokens=3_000, answer_tokens=700, total_tokens=3_700)
    client.force_login(user)

    page = client.get(chat_url(chat)).content.decode()

    assert "Answered by the backup model (qwen/qwen3.8-27b)" in page
    assert "Tokens used" not in page and "This question used" not in page   # only once, right after asking


@pytest.fixture
def fake_ask_with_tokens(monkeypatch):
    """Like fake_ask, but the saved question carries the Groq tokens the real agent saves."""
    def ask(question, user, context=None):
        saved = saved_question(user, text=question, model="openai/gpt-oss-120b",
                               sql_tokens=3_483, answer_tokens=861, total_tokens=4_344)
        return agent.AskResult(text=question, status="ok", answer=ANSWER, question=saved)

    monkeypatch.setattr(agent, "ask", ask)


NOTICE = "This question used 4,344 tokens (SQL 3,483 + answer 861) - openai/gpt-oss-120b"


def test_token_notice_shows_once_right_after_asking(client, user, fake_ask_with_tokens, mysql):
    chat = make_chat(user, "An earlier question", model="openai/gpt-oss-120b",
                     sql_tokens=1_000, answer_tokens=500, total_tokens=1_500)
    client.force_login(user)

    url = client.post(chat_url(chat), {"question": QUESTION}).url
    first = client.get(url).content.decode()                             # the redirect after asking
    again = client.get(url).content.decode()                             # a refresh
    other_page = client.get(reverse("history"))
    later = client.get(chat_url(chat)).content.decode()                  # coming back later

    assert first.count(NOTICE) == 1
    assert 'data-fade-after="20000"' in first                            # app.js fades it after 20 s
    assert first.index(NOTICE) > first.index(f'id="q-{Question.objects.get(text=QUESTION).pk}"')
    assert "1,500" not in first                                          # no notice for older answers
    assert NOTICE not in again and NOTICE not in later
    assert other_page.status_code == 200


def test_no_token_notice_when_groq_reported_no_tokens(client, user, fake_ask, mysql):
    client.force_login(user)

    page = client.post(reverse("ask"), {"question": QUESTION}, follow=True).content.decode()

    assert ANSWER in page
    assert "This question used" not in page


def test_example_link_opens_the_new_chat_screen_with_the_box_filled(client, user, mysql):
    make_chat(user, "An earlier question")
    client.force_login(user)

    r = client.get(reverse("ask"), {"q": "Open sales orders?"})
    assert r.status_code == 302 and r.url.startswith(reverse("ask_new"))

    page = client.get(r.url).content.decode()
    assert ">Open sales orders?</textarea>" in page
    assert "An earlier question" in page                                  # the list is still there
    assert f'href="{reverse("ask_new")}?q=' in page                       # the example chips


def test_a_saved_answer_page_links_back_to_its_chat(client, user, mysql):
    chat = make_chat(user, "First question", "Second question")
    first = chat.questions.order_by("created_at").first()
    client.force_login(user)

    page = client.get(reverse("ask_result", args=[first.pk])).content.decode()

    assert f'href="{chat_url(chat)}#q-{first.pk}"' in page                # back to the chat
    assert 'class="chat-row active"' in page                              # its chat is lit in the list
    assert f'action="{chat_url(chat)}"' in page                           # asking here continues that chat
    assert ">First question</textarea>" in page
    assert "Aurora Fluid Power Limited" in page and len(mysql) == 1


def test_no_usage_box_on_the_ask_pages(client, user, mysql):
    chat = make_chat(user, "A question", model="openai/gpt-oss-120b", total_tokens=4_000)
    client.force_login(user)

    for url in (chat_url(chat), reverse("ask_new"),
                reverse("ask_result", args=[chat.questions.first().pk])):
        page = client.get(url).content.decode()
        assert "AI usage (this app)" not in page and "questions left" not in page, url


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


def test_the_ask_page_is_built_for_separate_scrolling(client, user, mysql):
    """Desktop: the page fills the window (body class page-ask), only the conversation panel
    (#conv-scroll) and the chat list scroll, and the question box sits after the panel - so it is
    pinned under the conversation and never covers the last answer (app.css / app.js do the rest)."""
    chat = make_chat(user, "A question")
    client.force_login(user)

    page = client.get(chat_url(chat)).content.decode()

    assert '<body class="page-ask">' in page
    assert page.index('id="conv-scroll"') < page.index('<div class="bubble">A question</div>') < page.index('id="composer"')
    assert page.index('class="chats-scroll"') > page.index('class="btn primary new-chat"')   # New chat above the list
    assert '<body class="">' in client.get(reverse("history")).content.decode()             # other pages scroll normally


# ---------- edit an old question (like ChatGPT) ----------

def edit_url(question):
    return reverse("question_edit", args=[question.pk])


def thread_texts(page):
    """The question bubbles of a chat page, in order."""
    import re
    return re.findall(r'<div class="bubble">([^<]*)</div>', page)


def test_every_question_bubble_has_a_pencil_and_an_edit_form(client, user, mysql):
    chat = make_chat(user, "First", "Second")
    client.force_login(user)

    page = client.get(chat_url(chat)).content.decode()

    for saved in chat.questions.all():
        assert f'action="{edit_url(saved)}"' in page
    assert page.count("data-edit-toggle") == 2


def test_edit_replaces_the_question_in_place_and_history_keeps_the_old_one(client, user, fake_ask, mysql):
    chat = make_chat(user, "Q1", "Q2", "Q3")
    old = chat.questions.get(text="Q2")
    client.force_login(user)

    r = client.post(edit_url(old), {"question": "  Q2 edited  "})

    new = Question.objects.get(text="Q2 edited")
    assert fake_ask == ["Q2 edited"]                                     # asked once, as typed (trimmed)
    assert r.status_code == 302 and r.url == f"{chat_url(chat)}#q-{new.pk}"
    old.refresh_from_db()
    assert old.replaced_by == new and new.conversation == chat
    page = client.get(chat_url(chat)).content.decode()
    assert thread_texts(page) == ["Q1", "Q2 edited", "Q3"]              # same place, old one hidden
    assert "· edited" in page
    history = client.get(reverse("history")).content.decode()
    assert 'Q2<div class="mut">edited - replaced by a newer version</div>' in history   # old one still listed


def test_after_an_edit_the_edited_answer_and_the_newest_load_their_rows(client, user, fake_ask, mysql):
    chat = make_chat(user, "Q1", "Q2", "Q3")
    client.force_login(user)
    client.post(edit_url(chat.questions.get(text="Q1")), {"question": "Q1 again"})
    mysql.clear()

    client.get(chat_url(chat))                                           # right after the edit
    assert len(mysql) == 2                                               # the edited one + the newest
    mysql.clear()
    client.get(chat_url(chat))                                           # a later visit
    assert len(mysql) == 1                                               # only the newest


def test_only_the_owner_can_edit_and_an_edited_version_cannot_be_edited_again(client, user, other, fake_ask, mysql):
    chat = make_chat(user, "Mine")
    mine = chat.questions.get()
    client.force_login(other)
    assert client.post(edit_url(mine), {"question": "Hacked"}).status_code == 404
    client.force_login(user)
    client.post(edit_url(mine), {"question": "Mine, edited"})
    assert client.post(edit_url(mine), {"question": "Again"}).status_code == 404   # already replaced
    assert client.get(edit_url(mine)).status_code == 405                           # POST only
    assert fake_ask == ["Mine, edited"]


def test_an_empty_edit_asks_nothing(client, user, fake_ask, mysql):
    chat = make_chat(user, "Keep me")
    client.force_login(user)

    r = client.post(edit_url(chat.questions.get()), {"question": "   "})

    assert fake_ask == [] and r.status_code == 302
    assert not Question.objects.filter(replaced_by__isnull=False).exists()


def test_editing_the_first_question_retitles_the_chat_unless_it_was_renamed(client, user, fake_ask, mysql):
    plain = make_chat(user, "Old first question", "Second")
    renamed = make_chat(user, "Another first", title="My own title")
    client.force_login(user)

    client.post(edit_url(plain.questions.get(text="Old first question")), {"question": "New first question"})
    client.post(edit_url(plain.questions.get(text="Second")), {"question": "Second, edited"})
    client.post(edit_url(renamed.questions.get()), {"question": "Changed"})

    plain.refresh_from_db(); renamed.refresh_from_db()
    assert plain.title == "New first question"
    assert renamed.title == "My own title"


def test_deleting_a_chat_also_deletes_the_edited_away_versions(client, user, fake_ask, mysql):
    chat = make_chat(user, "Q1")
    client.force_login(user)
    client.post(edit_url(chat.questions.get()), {"question": "Q1 edited"})
    assert Question.objects.filter(conversation=chat).count() == 2

    client.post(reverse("chat_delete", args=[chat.pk]))

    assert not Question.objects.filter(user=user).exists()


def test_a_no_data_answer_shows_its_own_label(client, user, mysql):
    chat = make_chat(user, "profit this year?", status="nodata", sql="", rows_count=None,
                     answer="The NOP data does not have this: profit needs costs.")
    client.force_login(user)

    page = client.get(chat_url(chat)).content.decode()

    assert "DATA NOT AVAILABLE" in page and "NOT A NOP DATA QUESTION" not in page
    assert "NO DATA" in client.get(reverse("history")).content.decode()


def test_the_newest_chat_is_first_in_its_group(client, user, mysql):
    """A new chat goes to the TOP of the list (not the bottom) - also with the question counts."""
    make_chat(user, "Oldest today", minutes_ago=180)
    make_chat(user, "Middle today", minutes_ago=120)
    make_chat(user, "Newest today", minutes_ago=30)

    groups = _chat_groups(user)

    assert [c.title for c in groups[0]["chats"]] == ["Newest today", "Middle today", "Oldest today"]
    client.force_login(user)
    page = client.get(reverse("ask"), follow=True).content.decode()
    assert page.index("Newest today") < page.index("Middle today") < page.index("Oldest today")


def test_removed_chats_are_listed_newest_first(client, user, mysql):
    make_chat(user, "Removed long ago", minutes_ago=300, archived=True)
    make_chat(user, "Removed recently", minutes_ago=10, archived=True)
    make_chat(user, "Still listed", minutes_ago=5)
    client.force_login(user)

    page = client.get(reverse("ask"), follow=True).content.decode()

    assert page.index("Removed recently") < page.index("Removed long ago")


def test_ask_pages_are_never_cached_so_back_never_shows_an_old_thinking_page(client, user, mysql):
    chat = make_chat(user, "A question")
    client.force_login(user)

    for url in (chat_url(chat), reverse("ask_new"), reverse("ask_result", args=[chat.questions.get().pk])):
        assert "no-store" in client.get(url)["Cache-Control"]



# ---------- follow-up questions ----------

def test_a_follow_up_in_a_chat_passes_its_last_3_answered_questions(client, user, fake_ask, mysql):
    chat = make_chat(user, "Q1", "Q2", "Q3", "Q4")
    refused = saved_question(user, text="weather?", status="refused", conversation=chat)
    client.force_login(user)

    client.post(chat_url(chat), {"question": "and for Sep?"})

    assert fake_ask.contexts[-1] == ["Q2", "Q3", "Q4"]          # oldest first; refused one left out
    assert refused.text not in fake_ask.contexts[-1]


def test_the_first_question_of_a_new_chat_has_no_context(client, user, fake_ask, mysql):
    make_chat(user, "An older chat")
    client.force_login(user)

    client.post(reverse("ask"), {"question": "Top customers?"})

    assert fake_ask.contexts == [[]]


def test_an_edit_sees_only_the_questions_before_it(client, user, fake_ask, mysql):
    chat = make_chat(user, "Q1", "Q2", "Q3")
    client.force_login(user)

    client.post(edit_url(chat.questions.get(text="Q2")), {"question": "Q2 better"})

    assert fake_ask.contexts == [["Q1"]]


def test_understood_as_shows_on_the_answer_and_in_history_and_ask_again_uses_it(client, user, mysql):
    chat = make_chat(user, "and for Sep?", understood_as="Top 5 customers by invoice value in Sep 2026")
    client.force_login(user)

    page = client.get(chat_url(chat)).content.decode()
    history = client.get(reverse("history")).content.decode()

    assert "Understood as: Top 5 customers by invoice value in Sep 2026" in page
    assert "Understood as: Top 5 customers by invoice value in Sep 2026" in history
    assert 'name="question" value="Top 5 customers by invoice value in Sep 2026"' in history
