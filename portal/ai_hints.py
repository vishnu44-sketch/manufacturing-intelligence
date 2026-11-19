"""What the AI says the question asks for - two short lines the SQL call may write before its SQL.

17-Nov: two checks of lc/graph.run_sql decided only from fixed words in the question, so a typo slipped past them:
"top clints of Coolant pump" (no customers seen) or "bar chat of sales of the lst six mnths" (no chart, no periods
seen). The SQL call already reads the question with its typos, so it now also names what it understood
(agent.SQL_SYSTEM_PROMPT, no extra AI call):
- "ASKS_FOR: customers" - the question asks for a ranking or a list of customers / products / sales people /
  states / countries (not when the name is only a filter, not for a count);
- "PERIODS: 6" - the question asks for several periods ("last 6 months" -> 6).
Our code reads them here; the checks in lc/graph.run_sql use the AI's line first and the old word rules
(agent.missing_entity, graph.several_periods_chart_request) as the fallback. No line = exactly as before.
agent.read_sql_reply drops both lines, so they never reach the SQL.
"""
import re

from .rag import agent

# the AI's words (lower case, plurals and spaces / dashes / underscores taken out) -> our key
_ENTITIES = {
    "customer": "customer", "client": "customer", "buyer": "customer",
    "product": "product", "item": "product",
    "salesperson": "sales_person", "salespeople": "sales_person", "salesman": "sales_person",
    "salesmen": "sales_person", "salesrep": "sales_person",
    "state": "state",
    "country": "country",
}
# our key -> the key of agent.ENTITY_TABLES / ENTITY_COLUMNS ("sales person" is written with a space there)
AGENT_ENTITY = {"customer": "customer", "product": "product", "sales_person": "sales person", "state": "state",
                "country": "country"}
MAX_PERIODS = 120  # 10 years of months; a bigger number is not a real answer


def _line(reply, name):
    """The text after "NAME:" in the AI's reply ('' when there is no such line). Thinking aloud is skipped."""
    text = re.sub(r"<think>.*?</think>", "", reply or "", flags=re.S)
    match = re.search(rf"(?im)^\W*{name}\s*:\s*(.*)$", text)
    return agent.plain_text(match.group(1)).strip(" `*.") if match else ""


def asks_for(reply):
    """The thing the AI said the question ranks or lists, from its "ASKS_FOR: <...>" line: "customer", "product",
    "sales_person", "state" or "country"; '' when there is no such line, "none" or words we do not know."""
    words = _line(reply, "ASKS_FOR").lower()
    words = re.split(r"\s[-–]\s|[(,;:/]|\s(?:and|or)\s", words)[0]   # "customers (by sales)" -> "customers"
    key = re.sub(r"[^a-z]+", "", words)                               # "sales people" -> "salespeople"
    if key in _ENTITIES:
        return _ENTITIES[key]
    if key.endswith("ies") and key[:-3] + "y" in _ENTITIES:           # countries -> country
        return _ENTITIES[key[:-3] + "y"]
    if key.endswith("s") and key[:-1] in _ENTITIES:                   # customers -> customer, salesreps -> salesrep
        return _ENTITIES[key[:-1]]
    return ""


def periods(reply):
    """The number of periods the AI said the question asks for, from its "PERIODS: <n>" line (1 to 120);
    None when there is no such line or no whole number in that range."""
    match = re.fullmatch(r"(\d{1,4})(?:\s+[A-Za-z][\w\s-]*)?", _line(reply, "PERIODS"))  # "6" or "6 months"
    if not match:
        return None
    number = int(match.group(1))
    return number if 1 <= number <= MAX_PERIODS else None


def missing_entity(question, columns, ai_asks_for=""):
    """(what, the words that ask for it) of the thing the question ranks or lists that no result column shows,
    or None - the AI's ASKS_FOR line first (also when its words have a typo the word rules miss), then
    agent.missing_entity's word rules. what is a key of agent.ENTITY_TABLES."""
    what = AGENT_ENTITY.get(ai_asks_for)
    if what and not agent.shows_entity(what, columns):
        phrase = next((words for found, words in agent.ranked_entities(question) if found == what), "")
        return what, phrase or " ".join((question or "").split())[:80]
    return agent.missing_entity(question, columns)


def several_periods_chart(question, ai_periods=None, chart_kind=""):
    """True when the AI's lines say the question asks for a chart of several periods: its PERIODS line says 2 or
    more, and a chart was asked for (its CHART line, or the chart words of the question). lc/graph.run_sql also
    keeps its old word rules (several_periods_chart_request) as the fallback. chart_kind is a chart the USER asked
    for (agent.chart_asked) - 19-Nov: a kind the AI only suggested, or 'none', is not passed / not a chart wish."""
    wants_chart = chart_kind not in ("", "none", None) or bool(agent.CHART_WORDS.search(question or ""))
    return bool(ai_periods and ai_periods >= 2 and wants_chart)
