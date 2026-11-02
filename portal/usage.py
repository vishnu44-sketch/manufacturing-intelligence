"""Groq token usage of this app, for the box on History (portal/_usage_box.html).

The saved questions of all users of this app are counted three ways:
- the daily PERIOD: it starts with the first question and resets exactly 24 hours later at the same
  clock time (first question 10:05 AM -> resets 10:05 AM the next day); the next period starts with
  the next question after that;
- Groq's real count: the rolling last 24 hours - what Groq's daily limit really counts;
- the WEEK: since the last Saturday 8:20 PM (local time), resetting every Saturday 8:20 PM.
Tests and other tools that use the same Groq key are not included.
"""
import datetime

from django.db.models import Avg, Count, Sum
from django.utils import timezone

from .models import Question
from .rag import agent

DEFAULT_TOKENS_PER_QUESTION = 4500            # for "questions left" until the app has its own numbers
PERIOD = datetime.timedelta(hours=24)         # length of the daily period
PERIOD_LOOKBACK = datetime.timedelta(days=8)  # questions read to rebuild the chain of daily periods
WEEK_RESET_WEEKDAY = 5                        # the week resets on Saturday (Monday = 0) ...
WEEK_RESET_TIME = datetime.time(20, 20)       # ... at 8:20 PM local time


def ai_usage(now=None):
    """Everything the usage box shows:
    {rows: [{model, tokens, limit, pct, questions_left, rolling, week_tokens, week_questions}],
     period_start, period_end, week_start, week_end}.
    tokens / pct / questions_left are for the daily period (0 when no period is running), rolling =
    the last 24 hours, week_* = since week_start. The main and the backup model are always listed.
    A question counts under the model that wrote its last reply."""
    now = now or timezone.now()
    period_start, period_end = daily_period(now)
    week_from = week_start(now)
    asked = Question.objects.filter(created_at__lte=now)
    last_24h = asked.filter(created_at__gte=now - PERIOD)
    period = _per_model(asked.filter(created_at__gte=period_start)) if period_start else {}
    rolling = _per_model(last_24h)
    week = _per_model(asked.filter(created_at__gte=week_from))

    models = [m for m in (agent.model_name(), agent.fallback_model_name()) if m]
    models += sorted(m for m in {*period, *rolling, *week} if m not in models)
    limit = agent.daily_token_limit()
    per_question = tokens_per_question(last_24h)
    rows = []
    for model in models:
        used = period.get(model, (0, 0))[0]
        week_tokens, week_questions = week.get(model, (0, 0))
        rows.append({"model": model, "tokens": f"{used:,}", "limit": f"{limit:,}",
                     "pct": round(used * 100 / limit),
                     "questions_left": max(0, (limit - used) // per_question),
                     "rolling": f"{rolling.get(model, (0, 0))[0]:,}",
                     "week_tokens": f"{week_tokens:,}", "week_questions": week_questions})
    return {"rows": rows, "period_start": period_start, "period_end": period_end,
            "week_start": week_from, "week_end": week_from + datetime.timedelta(days=7)}


def daily_period(now=None):
    """(start, end) of the running daily period, or (None, None) when none is running.
    A period starts with a question and ends 24 hours later; the next one starts with the first
    question at or after that end (rebuilt from the questions of the last 8 days)."""
    now = now or timezone.now()
    start = None
    for asked_at in (Question.objects.filter(created_at__gte=now - PERIOD_LOOKBACK, created_at__lte=now)
                     .order_by("created_at").values_list("created_at", flat=True)):
        if start is None or asked_at >= start + PERIOD:
            start = asked_at
    if start is None or now >= start + PERIOD:
        return None, None
    return start, start + PERIOD


def week_start(now=None):
    """The last week reset (Saturday 8:20 PM local time) at or before now."""
    local = timezone.localtime(now or timezone.now())
    reset_day = local.date() - datetime.timedelta(days=(local.weekday() - WEEK_RESET_WEEKDAY) % 7)
    start = datetime.datetime.combine(reset_day, WEEK_RESET_TIME, tzinfo=local.tzinfo)
    return start if start <= local else start - datetime.timedelta(days=7)


def tokens_per_question(questions):
    """Average tokens of one question among these (with tokens saved), or the default."""
    average = questions.filter(total_tokens__gt=0).aggregate(avg=Avg("total_tokens"))["avg"]
    return round(average) if average else DEFAULT_TOKENS_PER_QUESTION


def _per_model(questions):
    """{model: (tokens, questions)} - questions without a model (asked before 07-Oct) are left out;
    a question without saved tokens counts as a question with 0 tokens."""
    rows = (questions.exclude(model="").order_by().values("model")
            .annotate(tokens=Sum("total_tokens"), n=Count("id")))
    return {r["model"]: (r["tokens"] or 0, r["n"]) for r in rows}
