"""The chat memory as LangChain objects: a chat history (BaseChatMessageHistory) on our own History DB.

A follow-up ("and for Sep 2026?") needs the chat's earlier questions. They are the saved Question rows
of the same chat (portal/models.py) - one database for the History page and the memory. ChatHistory
gives them to LangChain as messages, one pair per earlier question:
    HumanMessage(the question as typed,  understood_as = how it was written out)
    AIMessage(the answer,                 sql = the SQL that ran)
The question graph (graph.py) loads these messages into its state at the start: the rewrite step shows
them as a numbered list (rewrite_earlier), the SQL step as text with each SQL (sql_earlier).

Saving: agent.ask() saves every question as a full Question row (SQL, rows, tokens, time per step);
LangChain's add_messages() only has the question and the reply text, so it does not write anything.
"""
import re

import sqlglot
from django.db.models.functions import Coalesce
from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from sqlglot import exp

from .. import answer_check, sql_words
from ..rag import agent

LATEST = " (latest)"
CHECKS_SKIPPED = 20  # at most this many check messages between the questions a follow-up builds on


def chat_questions(chat, before=None):
    """The chat's last answered questions (oldest first, at most agent.CONTEXT_SIZE) for a follow-up;
    with before=, only the ones placed before that question (an edit). Refused / failed questions
    and edited-away versions are left out; a deleted chat has no memory (its questions are hidden).
    So are the questions about an earlier answer ("is that correct?", answer_check.py): the next follow-up
    builds on the data question itself, not on the check."""
    if chat.deleted_at is not None:
        return []
    questions = chat.questions.filter(replaced_by__isnull=True,
                                      status__in=("ok", "docs", "nodata", "general")).annotate(
        place=Coalesce("chat_order", "created_at"))
    if before is not None:
        questions = questions.filter(place__lt=before.chat_order or before.created_at)
    found = []
    for question in questions.order_by("-place", "-pk")[:agent.CONTEXT_SIZE + CHECKS_SKIPPED]:
        if answer_check.kind(question.text) is None:
            found.append(question)
        if len(found) == agent.CONTEXT_SIZE:
            break
    return found[::-1]


class ChatHistory(BaseChatMessageHistory):
    """The earlier questions of one chat as LangChain messages (oldest first). Made from the chat's
    saved Questions - chat_questions(chat) or the list agent.ask() was given."""

    def __init__(self, questions=(), session_id=""):
        self.questions = list(questions or [])[-agent.CONTEXT_SIZE:]
        self.session_id = session_id  # the chat's id ('' outside a chat)

    @classmethod
    def for_chat(cls, chat, before=None):
        """The history of a saved chat (Conversation), optionally only before one question (an edit)."""
        return cls(chat_questions(chat, before), session_id=str(chat.pk))

    @property
    def messages(self):
        found = []
        for question in self.questions:  # a saved Question (or anything with its fields)
            understood = getattr(question, "understood_as", "") or ""
            found.append(HumanMessage(question.text, additional_kwargs={"understood_as": understood}))
            found.append(AIMessage(getattr(question, "answer", "") or "",
                                   additional_kwargs={"sql": getattr(question, "sql", "") or ""}))
        return found

    def add_messages(self, messages):
        """Nothing to do: agent.ask() saves the whole Question row (with its SQL, rows and tokens) itself."""

    def clear(self):
        """Nothing to do: chats are kept for the History page and deleted only from the Ask page."""

    def __bool__(self):
        return bool(self.questions)

    def __len__(self):
        return len(self.questions)

    def __iter__(self):
        """The earlier Questions themselves, oldest first."""
        return iter(self.questions)


def messages_of(memory):
    """The chat memory as LangChain messages, from a ChatHistory, a list of earlier Questions (oldest first)
    or messages already (the graph's state). [] when there is none."""
    items = memory.messages if isinstance(memory, ChatHistory) else list(memory or [])
    if items and all(isinstance(item, BaseMessage) for item in items):
        return items
    return ChatHistory(items).messages


def _pairs(messages):
    """[(HumanMessage, AIMessage)] of a history's messages."""
    return list(zip(messages[0::2], messages[1::2]))


def rewrite_earlier(messages):
    """The earlier questions for the rewrite prompt: '1. <understood as, or the question>' ... '(latest)'."""
    pairs = _pairs(messages)
    return "\n".join(f"{n}. {human.additional_kwargs.get('understood_as') or ' '.join(human.content.split())}"
                     + (LATEST if n == len(pairs) else "")
                     for n, (human, _) in enumerate(pairs, 1))


def sql_earlier(messages):
    """The earlier questions for the SQL request ('' when there are none): question, what it was
    understood as, its SQL and answer - cut, to keep the request small (agent.EARLIER_HEAD / EARLIER_ITEM)."""
    pairs = _pairs(messages)
    if not pairs:
        return ""
    items = []
    for n, (human, ai) in enumerate(pairs, start=1):
        understood = human.additional_kwargs.get("understood_as")
        sql = " ".join((ai.additional_kwargs.get("sql") or "(no SQL - not answered with data)").split())
        answer = " ".join((ai.content or "").split())
        items.append(agent.EARLIER_ITEM.format(
            n=n, question=" ".join(human.content.split()),
            understood=f"\n   Understood as: {understood}" if understood else "",
            sql=sql[:agent.CONTEXT_SQL_CHARS] + (" ..." if len(sql) > agent.CONTEXT_SQL_CHARS else ""),
            answer=answer[:agent.CONTEXT_ANSWER_CHARS] + (" ..." if len(answer) > agent.CONTEXT_ANSWER_CHARS else "")))
    return agent.EARLIER_HEAD + "\n" + "\n".join(items) + "\n"


def general_history(messages):
    """The earlier questions and answers for the general answer (agent.answer_general) as a real chat - a
    HumanMessage and an AIMessage per earlier question, oldest first - so "explain it simpler" or "give an
    example" follows the conversation. Each answer is cut to agent.GENERAL_HISTORY_ANSWER_CHARS (tokens!);
    no SQL (a general answer never needs it)."""
    found = []
    for human, ai in _pairs(messages):
        answer = " ".join((ai.content or "").split())
        limit = agent.GENERAL_HISTORY_ANSWER_CHARS
        found.append(HumanMessage(human.additional_kwargs.get("understood_as") or " ".join(human.content.split())))
        found.append(AIMessage(answer[:limit] + (" ..." if len(answer) > limit else "")))
    return found


def latest_question(messages):
    """How the chat's last question was understood (or the question itself) - '' without a history."""
    pairs = _pairs(messages)
    if not pairs:
        return ""
    human = pairs[-1][0]
    return human.additional_kwargs.get("understood_as") or human.content


# ------------------------------------------------------------------ a question about an earlier answer's own result
# 18-Nov: after an answer with the columns horizon_months | forecast_count, "forecast_count what it mean this coloums"
# got DATA NOT AVAILABLE and "why did you add this forecast_count?" got "I added it by mistake": no step saw the
# query that made forecast_count. These word rules only decide whether that query and its columns are ADDED to the
# rewrite, SQL and general requests (agent.PREVIOUS_QUERY_*); the AI still decides and writes the answer.
_COLUMN = r"(?:colu?m[nm]?s?|coloum[ns]?s?|colom[ns]?s?|colmns?|clmns?|fields?|feilds?|headers?|headings?)"
_EARLIER = r"(?:previous|previus|prevous|privious|prev|last|above|earlier|this|that|your|ur)"
_ANSWER = r"(?:answers?|anwers?|anwsers?|answr|ans|results?|reply|response|query|queries|sql|output|table)"
REFERS_TO_ANSWER = re.compile(
    rf"\b(?:this|that|these|those|ths|your|ur)\s+{_COLUMN}\b"          # "this column", "that coloums"
    rf"|\b{_EARLIER}\s+(?:{_EARLIER}\s+)?{_ANSWER}\b"                   # "previous answer", "your last query"
    r"|\bwhy\s+(?:did\s+|do\s+|have\s+|would\s+)?(?:you|u)\s+(?:add|includ|put|show|use|count|make|made|creat|"
    r"give|gave|take|took|pick|chose|choose|calculat|comput)\w*", re.I)   # "why did you add ...", "why u put ..."
ABOUT_WORDS = re.compile(rf"\b(?:means?|meaning|meant|stands?\s+for|explain\w*|definition|define|why|{_COLUMN})\b",
                         re.I)


def query_columns(sql):
    """[(name, made)] of the columns a SELECT gives back, in order. made = the query named the column itself (an AS
    name over a COUNT, SUM, CASE ... or a renamed column) - a column of that name is in no table. [] when the SQL
    cannot be read."""
    try:
        tree = sqlglot.parse_one(sql, read="mysql")
        items = list(tree.selects) if isinstance(tree, (exp.Select, exp.SetOperation)) else []
    except Exception:  # noqa: BLE001 - only decides whether to add context: any SQL it cannot read adds none
        return []
    found = []
    for item in items:
        name = item.alias_or_name
        if name and name != "*":
            made = isinstance(item, exp.Alias) and not (isinstance(item.this, exp.Column) and item.this.name == name)
            found.append((name, made))
    return found


def _words(text):
    """' forecast count ' for 'FORECAST_COUNT' - lower case, every run of other characters one space."""
    return f" {' '.join(re.findall(r'[a-z0-9]+', (text or '').lower()))} "


def names_column(column, text):
    """True when the text names this column, in any case, with _ or spaces: forecast_count, "forecast count",
    FORECAST_COUNT."""
    key = _words(column)
    return bool(key.strip()) and key in _words(text)


def previous_query(messages, text):
    """The earlier answer a question is about, when it is about that answer's own result - {"n": its number in the
    chat's history (as in sql_earlier), "sql": its SQL, "columns": its column names} - else None (then no request
    gets anything more). A question is about it when it
    - names a column the earlier query made itself with a name of 2+ words (e.g. forecast_count = COUNT(*)), or
      names any of its columns together with a word like "mean", "why", "explain" or "column" - the latest answer
      with such a column wins; or
    - says "this column", "previous answer", "your last query", "why did you add ..." - the latest answer with a query.
    Only answers with SQL count (a general or documents answer has no columns)."""
    text = text or ""
    answered = [(n, ai.additional_kwargs.get("sql") or "") for n, (_, ai) in enumerate(_pairs(messages), start=1)]
    answered = [(n, sql) for n, sql in answered if sql.strip()]
    if not answered or not text.strip():
        return None
    about = bool(ABOUT_WORDS.search(text))
    for n, sql in reversed(answered):
        columns = query_columns(sql)
        if any(names_column(name, text) and (about or (made and len(_words(name).split()) > 1))
               for name, made in columns):
            return {"n": n, "sql": sql, "columns": [name for name, _ in columns]}
    if REFERS_TO_ANSWER.search(text):
        n, sql = answered[-1]
        return {"n": n, "sql": sql, "columns": [name for name, _ in query_columns(sql)]}
    return None


def previous_query_text(found, shown=False):
    """The earlier answer's query for a request (agent.PREVIOUS_QUERY): its columns, its SQL on one line (cut to
    agent.PREVIOUS_QUERY_CHARS) and, when sql_words can read it, the same in plain words (0 tokens to make).
    shown=True (the SQL request, whose 'Earlier in this chat' already lists that SQL): only its number and columns."""
    columns = ", ".join(found["columns"]) or "not known"
    if shown:
        return agent.PREVIOUS_QUERY_SHOWN.format(n=found["n"], columns=columns)
    sql = " ".join(found["sql"].split())
    limit = agent.PREVIOUS_QUERY_CHARS
    words = " ".join(sql_words.describe_sql(found["sql"]))
    return agent.PREVIOUS_QUERY.format(columns=columns, sql=sql[:limit] + (" ..." if len(sql) > limit else ""),
                                       words=f"\nIn plain words: {words}" if words else "")
