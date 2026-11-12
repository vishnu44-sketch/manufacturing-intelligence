"""The AI usage box on History (portal/usage.py, sent by /api/history), at fixed times.

- daily period: starts with the first question, resets exactly 24 h later at the same clock time,
  the next period starts with the next question after that;
- Groq's real count: the rolling last 24 hours;
- the week: since the last Saturday 8:20 PM (India time), resetting every Saturday 8:20 PM.
No AI and no MySQL - only saved questions in pytest's test database.
Run with:  python -m pytest -q portal/tests/test_usage.py
"""
import datetime
import zoneinfo

import pytest
from django.urls import reverse

from portal import api
from portal.models import Question
from portal.usage import ai_usage, daily_period, week_start

pytestmark = pytest.mark.django_db

IST = zoneinfo.ZoneInfo("Asia/Kolkata")
MAIN, BACKUP = "openai/gpt-oss-120b", "qwen/qwen3.8-27b"


def at(day, hour, minute=0):
    """An India-time moment in Oct 2026 (08-Oct-2026 is a Thursday, 10-Oct a Saturday)."""
    return datetime.datetime(2026, 10, day, hour, minute, tzinfo=IST)


@pytest.fixture(autouse=True)
def two_models(monkeypatch):
    monkeypatch.setenv("GROQ_MODEL", MAIN)
    monkeypatch.setenv("GROQ_FALLBACK_MODEL", BACKUP)
    monkeypatch.delenv("GROQ_DAILY_TOKEN_LIMIT", raising=False)


def asked(user, when, tokens=None, model=MAIN):
    """A saved question asked at `when` (created_at is set after the insert: auto_now_add)."""
    q = Question.objects.create(user=user, text="A question", status="ok", model=model, total_tokens=tokens)
    Question.objects.filter(pk=q.pk).update(created_at=when)
    return q


def main_row(usage):
    return next(r for r in usage["rows"] if r["model"] == MAIN)


# ---------- the daily period ----------

def test_the_first_question_starts_the_period_and_it_resets_24_hours_later(user):
    asked(user, at(8, 10, 5), 4_000)
    asked(user, at(8, 15, 0), 1_000)

    assert daily_period(at(8, 18)) == (at(8, 10, 5), at(9, 10, 5))
    assert main_row(ai_usage(at(8, 18)))["tokens"] == "5,000"
    assert main_row(ai_usage(at(9, 10, 4)))["tokens"] == "5,000"           # one minute before the reset


def test_after_the_reset_the_period_shows_0_until_the_next_question(user):
    asked(user, at(8, 10, 5), 4_000)
    asked(user, at(8, 15, 0), 1_000)

    usage = ai_usage(at(9, 10, 6))                                          # one minute after the reset

    assert usage["period_start"] is None and usage["period_end"] is None
    assert main_row(usage)["tokens"] == "0" and main_row(usage)["pct"] == 0
    assert main_row(usage)["rolling"] == "1,000"                            # Groq still counts 15:00 yesterday


def test_the_next_question_after_the_reset_starts_a_new_period(user):
    asked(user, at(8, 10, 5), 4_000)
    asked(user, at(9, 12, 30), 2_000)

    usage = ai_usage(at(9, 13))

    assert (usage["period_start"], usage["period_end"]) == (at(9, 12, 30), at(10, 12, 30))
    assert main_row(usage)["tokens"] == "2,000"


def test_a_question_exactly_24_hours_later_starts_a_new_period(user):
    asked(user, at(8, 10, 5), 4_000)
    asked(user, at(9, 10, 5), 3_000)

    assert daily_period(at(9, 11)) == (at(9, 10, 5), at(10, 10, 5))
    assert main_row(ai_usage(at(9, 11)))["tokens"] == "3,000"


def test_days_without_questions_and_questions_inside_a_period(user):
    asked(user, at(1, 9, 0), 1_000)
    asked(user, at(1, 20, 0), 1_000)                                        # inside the 01-Oct period
    asked(user, at(3, 11, 0), 2_500)                                        # two days later: a new period
    asked(user, at(3, 23, 0), 500)

    assert daily_period(at(3, 23, 30)) == (at(3, 11, 0), at(4, 11, 0))
    assert main_row(ai_usage(at(3, 23, 30)))["tokens"] == "3,000"


def test_no_questions_means_no_period(user):
    usage = ai_usage(at(8, 12))

    assert usage["period_start"] is None
    assert [r["model"] for r in usage["rows"]] == [MAIN, BACKUP]
    assert main_row(usage)["questions_left"] == 44                          # 200,000 // 4,500 default


def test_questions_left_uses_the_average_of_the_last_24_hours(user):
    asked(user, at(8, 10, 5), 4_000)
    asked(user, at(8, 11, 0), 6_000)                                        # average 5,000

    assert main_row(ai_usage(at(8, 12)))["questions_left"] == 38            # (200,000 - 10,000) // 5,000


def test_every_user_counts_and_the_backup_model_has_its_own_line(user, other):
    asked(user, at(8, 10, 5), 4_000)
    asked(other, at(8, 11, 0), 2_000)
    asked(user, at(8, 11, 30), 1_500, model=BACKUP)

    rows = {r["model"]: r for r in ai_usage(at(8, 12))["rows"]}

    assert rows[MAIN]["tokens"] == "6,000" and rows[BACKUP]["tokens"] == "1,500"


# ---------- Groq's real count (rolling last 24 h) ----------

def test_the_rolling_count_can_be_higher_than_a_fresh_period(user):
    asked(user, at(7, 12, 0), 4_000)                                        # period 07-Oct 12:00 .. 08-Oct 12:00
    asked(user, at(7, 14, 0), 1_000)
    asked(user, at(8, 12, 30), 2_000)                                       # starts the next period

    usage = ai_usage(at(8, 13, 0))

    assert main_row(usage)["tokens"] == "2,000"                             # the new period only
    assert main_row(usage)["rolling"] == "3,000"                            # Groq: 07-Oct 14:00 is < 24 h ago


# ---------- the week: since Saturday 8:20 PM ----------

def test_the_week_starts_on_saturday_at_8_20_pm():
    assert week_start(at(10, 20, 19)) == at(3, 20, 20)                      # Sat 20:19: still last week
    assert week_start(at(10, 20, 20)) == at(10, 20, 20)                     # exactly 8:20 PM: new week
    assert week_start(at(10, 20, 21)) == at(10, 20, 20)
    assert week_start(at(11, 9, 0)) == at(10, 20, 20)                       # Sunday morning
    assert week_start(at(8, 10, 0)) == at(3, 20, 20)                        # Thursday


def test_weekly_totals_reset_on_saturday_at_8_20_pm(user):
    asked(user, at(10, 20, 19), 1_000)                                      # last week
    asked(user, at(10, 20, 21), 2_000)                                      # this week

    before = ai_usage(at(10, 20, 19))
    after = ai_usage(at(10, 21, 0))

    assert (main_row(before)["week_tokens"], main_row(before)["week_questions"]) == ("1,000", 1)
    assert (main_row(after)["week_tokens"], main_row(after)["week_questions"]) == ("2,000", 1)
    assert after["week_start"] == at(10, 20, 20) and after["week_end"] == at(17, 20, 20)


def test_a_question_without_saved_tokens_counts_as_a_question_with_0_tokens(user):
    asked(user, at(8, 10, 0), None)
    asked(user, at(8, 11, 0), 3_000)

    row = main_row(ai_usage(at(8, 12)))

    assert row["week_tokens"] == "3,000" and row["week_questions"] == 2


# ---------- what the box says (History's usage data, /api/history) ----------

@pytest.fixture
def usage_at(monkeypatch):
    """History's usage box as it would be at a fixed moment."""
    def fixed(now):
        monkeypatch.setattr(api, "ai_usage", lambda: ai_usage(now))
    return fixed


def test_the_box_data_at_a_fixed_time(client, user, usage_at):
    asked(user, at(8, 10, 5), 4_000)
    asked(user, at(8, 15, 0), 1_000)
    usage_at(at(8, 18))
    client.force_login(user)

    usage = client.get(reverse("api_history")).json()["usage"]

    assert usage["period_start"] == "Thu 08-Oct 10:05 AM"                  # "Daily period since ..."
    assert usage["period_end"] == "Fri 09-Oct 10:05 AM"                    # "... - resets ..."
    main, backup = usage["rows"]
    assert (main["model"], main["tokens"], main["limit"], main["pct"]) == (MAIN, "5,000", "200,000", 2)
    assert main["questions_left"] == 78                                    # (200,000 - 5,000) // 2,500
    assert (main["rolling"], backup["model"], backup["rolling"]) == ("5,000", BACKUP, "0")
    assert (usage["week_start"], usage["week_end"]) == ("Sat 03-Oct 8:20 PM", "Sat 10-Oct 8:20 PM")
    assert (main["week_tokens"], main["week_questions"]) == ("5,000", 2)
    assert (backup["week_tokens"], backup["week_questions"]) == ("0", 0)


def test_the_box_says_when_the_next_period_starts(client, user, usage_at):
    asked(user, at(8, 10, 5), 4_000)
    usage_at(at(9, 11))
    client.force_login(user)

    usage = client.get(reverse("api_history")).json()["usage"]

    assert usage["period_start"] == "" and usage["period_end"] == ""      # "Daily period: starts with your next question."


def test_history_has_the_box_and_the_ask_screens_do_not(client, user):
    client.force_login(user)

    history = client.get(reverse("api_history")).json()
    chats = client.get(reverse("api_chats")).json()

    assert history["usage"]["rows"] and history["usage"]["week_start"]
    assert "usage" not in chats
