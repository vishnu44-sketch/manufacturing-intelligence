"""The AI chart: a chart the React app cannot draw itself (a sankey, a sunburst, a gauge, a bar with a target
line ...), made by the AI from an answer's rows - POST /api/questions/<id>/chart (api.question_chart).

The built-in charts (bar, line, donut, treemap, heatmap ...) are drawn in the browser with 0 AI tokens; this
is only for the unusual ones, and only when the user clicks "Make this chart with AI".

The steps: the saved SQL runs again exactly like the rows endpoint (services.saved_result: guard + read-only
MySQL, no AI call), then ONE AI call (the main model, low effort, at most MAX_TOKENS) through lc/calls.chat -
so the app's rate-limit rules apply (wait on a per-minute limit, a friendly message on a daily limit). The AI
gets the question, the column names, at most MAX_ROWS rows and the chart asked for, and must reply with ONLY
an Apache ECharts option as JSON.

The reply is DATA, never code: check_option() lets through only plain JSON with the allowed top-level keys and
series types, no functions / "javascript:" / HTML tags / web addresses, and nothing too big or too deep.
The browser checks it once more (AiChart.tsx: the allowed keys, a text-only tooltip).

The tokens: added to the question's own token count (total_tokens) when the question was answered by the same
model, so the History usage box counts them under the right model; they are always sent back to be shown.
"""
import datetime
import decimal
import json
import logging
import math
import re
from dataclasses import dataclass

from django.db.models import F, Value
from django.db.models.functions import Coalesce
from langchain_core.prompts import ChatPromptTemplate

from . import services
from .lc import calls
from .lc.calls import LcRequest
from .models import Question
from .rag import agent

log = logging.getLogger(__name__)

MAX_ROWS = 50               # rows the AI gets (the chart is made from these)
MAX_TOKENS = 1500           # the AI's reply: one ECharts option
EFFORT = "low"
MAX_OPTION_CHARS = 30_000   # the option as JSON text
MAX_DEPTH = 12              # nesting of the option
MAX_NODES = 20_000          # values in the option
MAX_SERIES = 20
MAX_KIND_CHARS = 60

# the top-level keys the browser may draw (frontend/src/charts/AiChart.tsx ALLOWED_KEYS is the same list)
ALLOWED_KEYS = frozenset({"series", "xAxis", "yAxis", "title", "legend", "tooltip", "grid", "visualMap", "dataset",
                          "radar", "polar", "angleAxis", "radiusAxis", "color"})
# the series types the browser has loaded (frontend/src/charts/echarts.ts + echartsAi.ts)
SERIES_TYPES = frozenset({"line", "bar", "pie", "scatter", "effectScatter", "radar", "treemap", "sunburst", "sankey",
                          "boxplot", "candlestick", "heatmap", "funnel", "gauge", "pictorialBar", "graph", "tree"})
# keys that could reach the browser's objects (prototype pollution) or open a link
BAD_KEYS = frozenset({"__proto__", "constructor", "prototype", "link", "sublink", "renderItem"})
# text that could run code, draw HTML or load something from the web
BAD_TEXT = re.compile(
    r"javascript\s*:|vbscript\s*:|\bfunction\s*\(|=>|<\s*[a-z/!?]|\bimage://|\bhttps?://|//[\w-]+\.[\w.-]+/|\burl\s*\(|\beval\s*\(",
    re.I)
KIND_TEXT = re.compile(r"^[\w\s()%&+,.'/-]+$")

NOT_ANSWERED = "This question has no rows to chart."
NO_ROWS = "The query returned no rows - there is nothing to chart."
DAILY_LIMIT = "The AI model's daily limit is used up - the AI chart can be made again tomorrow. The table has the rows."
CUT_OFF = "The AI's chart was too long. Please try a simpler chart (or fewer rows)."
BAD_REPLY = "The AI did not give a chart that can be drawn safely ({why}). Please try again."

CHART_SYSTEM_PROMPT = (
    "You make Apache ECharts 6 charts. Reply with ONLY one JSON object: the ECharts option. No words, no code "
    "fences, no comments.\n"
    "Rules:\n"
    "- Plain JSON only: double quotes, no functions, no JavaScript, no HTML, no web addresses.\n"
    "- Top-level keys allowed: " + ", ".join(sorted(ALLOWED_KEYS)) + ".\n"
    "- Series types allowed: " + ", ".join(sorted(SERIES_TYPES)) + ". A target or average line is a markLine "
    "inside a series.\n"
    "- Use only the rows given; never invent values. Numbers as plain JSON numbers (no thousands separators).\n"
    "- Keep it short (under 1,200 tokens): no animation or styling unless the chart needs it. Formatter "
    "strings may use ECharts templates such as b and c in braces.\n"
    "- If the chart asked for cannot be made from these rows, make the closest chart that can."
)
CHART_REQUEST = (
    "Question: {question}\n"
    "Chart wanted: {kind}\n"
    "Columns: {columns}\n"
    "Rows ({row_note}), as JSON arrays in the column order:\n{rows}"
)

# question + rows + the chart wanted -> the ECharts option as JSON
CHART_PROMPT = ChatPromptTemplate.from_messages([("system", CHART_SYSTEM_PROMPT), ("human", CHART_REQUEST)])


def chart_chain(llm):
    return CHART_PROMPT | llm


calls.CHAINS.setdefault("chart", chart_chain)  # so calls.chat() runs it with the app's rate-limit rules


class ChartError(Exception):
    """The AI chart could not be made: str() is the friendly message, status the HTTP status for the API."""

    def __init__(self, message, status=503):
        super().__init__(message)
        self.status = status


class OptionRejected(ValueError):
    """The AI's reply is not a chart that can be drawn safely: str() says why."""


@dataclass
class AiChart:
    option: dict
    tokens: int | None
    model: str
    recorded: bool  # the tokens were added to the question's own count


def kind_problem(kind):
    """Why this chart name cannot be sent to the AI - '' when it is fine."""
    if not kind:
        return "Say which chart to make."
    if len(kind) > MAX_KIND_CHARS:
        return f"Please keep the chart name under {MAX_KIND_CHARS} characters."
    if not KIND_TEXT.match(kind):
        return "The chart name may only have letters, numbers and spaces."
    return ""


def _plain(value):
    """One MySQL value as plain JSON: Decimal -> number, a date -> ISO text, bytes -> text."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, decimal.Decimal):
        return float(value) if value.is_finite() else None
    if isinstance(value, (datetime.date, datetime.datetime, datetime.time)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def chart_values(saved, columns, rows, kind):
    """The values of the chart prompt: the question, the chart wanted, the columns and at most MAX_ROWS rows."""
    shown = rows[:MAX_ROWS]
    note = f"all {len(rows)}" if len(rows) <= MAX_ROWS else f"the first {MAX_ROWS} of {len(rows)}"
    question = saved.text if not saved.understood_as else f"{saved.text} (understood as: {saved.understood_as})"
    return {"question": question, "kind": kind, "columns": ", ".join(str(c) for c in columns), "row_note": note,
            "rows": "\n".join(json.dumps([_plain(v) for v in row], ensure_ascii=False) for row in shown)}


def parse_reply(text):
    """The JSON object in the AI's reply (code fences and words around it are dropped) - OptionRejected when
    there is none."""
    text = (text or "").strip()
    if len(text) > MAX_OPTION_CHARS:
        raise OptionRejected("it is too big")
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S | re.I)
    if fenced:
        text = fenced.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise OptionRejected("it is not JSON")
    try:
        option = json.loads(text[start:end + 1], parse_constant=_no_constant)
    except ValueError:
        raise OptionRejected("it is not valid JSON") from None
    return check_option(option)


def _no_constant(name):
    raise OptionRejected(f"{name} is not a number")


def check_option(option):
    """The option when it is safe to draw, else OptionRejected: a JSON object with a series, only the allowed
    top-level keys and series types, no code-like or HTML text, no web addresses, not too big or deep."""
    if not isinstance(option, dict) or not option:
        raise OptionRejected("it is not a JSON object")
    unknown = sorted(set(option) - ALLOWED_KEYS)
    if unknown:
        raise OptionRejected(f"the key {unknown[0]!r} is not allowed")
    series = option.get("series")
    if isinstance(series, dict):
        series = option["series"] = [series]
    if not isinstance(series, list) or not series:
        raise OptionRejected("it has no series")
    if len(series) > MAX_SERIES:
        raise OptionRejected("it has too many series")
    for one in series:
        if not isinstance(one, dict) or one.get("type") not in SERIES_TYPES:
            kind = one.get("type") if isinstance(one, dict) else None
            raise OptionRejected(f"the series type {kind!r} is not allowed")
    count = 0

    def walk(value, depth):
        nonlocal count
        count += 1
        if count > MAX_NODES:
            raise OptionRejected("it is too big")
        if depth > MAX_DEPTH:
            raise OptionRejected("it is nested too deep")
        if isinstance(value, dict):
            for key, item in value.items():
                if not isinstance(key, str) or key in BAD_KEYS or BAD_TEXT.search(key):
                    raise OptionRejected(f"the key {str(key)[:40]!r} is not allowed")
                walk(item, depth + 1)
        elif isinstance(value, list):
            for item in value:
                walk(item, depth + 1)
        elif isinstance(value, str):
            if BAD_TEXT.search(value):
                raise OptionRejected("it has code, HTML or a web address in a text")
        elif isinstance(value, float):
            if not math.isfinite(value):
                raise OptionRejected("it has a number that is not finite")
        elif value is not None and not isinstance(value, (bool, int)):
            raise OptionRejected("it has a value that is not plain JSON")

    walk(option, 0)
    if len(json.dumps(option)) > MAX_OPTION_CHARS:
        raise OptionRejected("it is too big")
    return option


def make_chart(saved, kind):
    """The AI chart of a saved, answered question -> AiChart. ChartError with a friendly message when it cannot
    be made (the rows cannot run again, no rows, the AI is busy or down, the reply is not a safe chart)."""
    if saved.status != "ok" or not saved.sql:
        raise ChartError(NOT_ANSWERED, 404)
    result, rows_error = services.saved_result(saved, load_rows=True)  # the same re-run as the rows endpoint
    if rows_error:
        raise ChartError(rows_error, 503)
    if not result.rows:
        raise ChartError(NO_ROWS, 400)
    model = agent.model_name()
    request = LcRequest("chart", chart_values(saved, result.columns, result.rows, kind))
    try:
        text, tokens, cut_off = calls.chat(request, MAX_TOKENS, EFFORT, model=model)
    except agent.DailyLimitReached:
        raise ChartError(DAILY_LIMIT, 503) from None
    except agent.AIUnavailable as exc:
        raise ChartError(str(exc) or agent.AI_ERROR, 503) from None
    recorded = record_tokens(saved, model, tokens)
    if cut_off:
        raise ChartError(CUT_OFF, 502)
    try:
        option = parse_reply(text)
    except OptionRejected as exc:
        log.warning("AI chart rejected for question %s: %s", saved.pk, exc)
        raise ChartError(BAD_REPLY.format(why=exc), 502) from None
    return AiChart(option=option, tokens=tokens, model=model, recorded=recorded)


def record_tokens(saved, model, tokens):
    """Add the chart's tokens to the question's own count when the question was answered by the same model
    (the usage box counts a question's tokens under its model). True when they were added."""
    if not tokens or saved.model != model:
        return False
    Question.objects.filter(pk=saved.pk).update(total_tokens=Coalesce(F("total_tokens"), Value(0)) + tokens)
    return True
