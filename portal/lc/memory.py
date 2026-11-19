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
import functools
import logging
import re
import time
from pathlib import Path

import sqlglot
from django.conf import settings
from django.db.models.functions import Coalesce
from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from sqlglot import exp

from .. import answer_check, sql_words
from ..rag import agent, warehouse
from ..rag.sql_guard import check_sql

log = logging.getLogger(__name__)

LATEST = " (latest)"
CHECKS_SKIPPED = 20  # at most this many check messages between the questions a follow-up builds on
LOOK_BACK = 30       # previous_query looks back through at most this many older answers with a query (SQL only)


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

    def __init__(self, questions=(), session_id="", chat=None, before=None):
        self.questions = list(questions or [])[-agent.CONTEXT_SIZE:]
        self.session_id = session_id  # the chat's id ('' outside a chat)
        self.chat, self.before = chat, before  # the saved chat (None = a plain list), for older_answers()
        self._older = None                     # older_answers(), read once per question

    @classmethod
    def for_chat(cls, chat, before=None):
        """The history of a saved chat (Conversation), optionally only before one question (an edit)."""
        return cls(chat_questions(chat, before), session_id=str(chat.pk), chat=chat, before=before)

    def older_answers(self):
        """The SQL of the chat's answers with a query placed BEFORE the questions the memory keeps (oldest first, at
        most LOOK_BACK) - for previous_query, so "what does low_inr mean?" still finds an answer of 10 questions ago.
        Read from MySQL only when asked for (SQL only, once per question); [] outside a saved chat."""
        if self._older is None:
            self._older = []
            if self.chat is not None and self.chat.deleted_at is None:
                questions = self.chat.questions.filter(
                    replaced_by__isnull=True, status__in=("ok", "docs", "nodata", "general")).exclude(sql="").exclude(
                    pk__in=[q.pk for q in self.questions if getattr(q, "pk", None)]).annotate(
                    place=Coalesce("chat_order", "created_at"))
                if self.before is not None:
                    questions = questions.filter(place__lt=self.before.chat_order or self.before.created_at)
                if self.questions and getattr(self.questions[0], "pk", None):  # only the ones before the memory's
                    first = self.questions[0]
                    questions = questions.filter(place__lte=getattr(first, "chat_order", None) or first.created_at)
                self._older = list(questions.order_by("-place", "-pk").values_list("sql", flat=True)[:LOOK_BACK])[::-1]
        return self._older

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


# 18-Nov: "what does low_inr mean?", 10 questions after the forecast answer that showed low_inr, got "the meaning of
# low_inr is not in the SS Manufacturing data": that answer was older than the questions the memory keeps, and low_inr
# is a STORED column (no AS in the query to explain it from). Now previous_query also looks through the chat's older
# answers (ChatHistory.older_answers, only when the question may name a column), and a named stored column gets its
# one line from docs/data_dictionary.md as a fact (column_facts).
DICTIONARY_FILE = "data_dictionary.md"
_TABLE_HEAD = re.compile(r"^## ([a-z][a-z0-9_]*) - ")                    # "## ml_sales_forecast - sales forecast ..."
_COLUMN_LINE = re.compile(r"^- `([a-z][a-z0-9_]*)` [^:`]+: (.+)$")      # "- `low_inr` DECIMAL(18,2): Low end of ..."
FACT_CHARS = 300  # each column's meaning is cut to this length (tokens!)


@functools.lru_cache(maxsize=4)
def data_dictionary(path=None):
    """{table: {column: meaning}} of docs/data_dictionary.md (its "## table - ..." sections and "- `column` TYPE:
    meaning" lines), read once per process. {} when the file cannot be read."""
    path = Path(path) if path else Path(settings.BASE_DIR) / "docs" / DICTIONARY_FILE
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    found, table = {}, None
    for line in lines:
        if line.startswith("#"):
            head = _TABLE_HEAD.match(line)
            table = head.group(1) if head else None
            continue
        column = _COLUMN_LINE.match(line) if table else None
        if column:
            found.setdefault(table, {})[column.group(1)] = column.group(2).strip()
    return found


def _dictionary_columns():
    """Every column name of the data dictionary (any table)."""
    return {column for columns in data_dictionary().values() for column in columns}


def may_name_column(text):
    """True when a question may name a column of an earlier answer - it has a word with _ (low_inr, forecast_count),
    or a word like "mean" / "explain" together with a column name of the data dictionary. Only then are the chat's
    older answers read (any other question: no extra query)."""
    text = text or ""
    if re.search(r"[a-z0-9]_[a-z0-9]", text, re.I):
        return True
    return bool(ABOUT_WORDS.search(text)) and any(names_column(column, text) for column in _dictionary_columns())


def column_facts(sql, names):
    """["low_inr (ml_sales_forecast): <its meaning from the data dictionary>"] for the named columns that the query
    takes straight from a table (not a name it made with AS) and that the data dictionary explains; [] for others."""
    if not names:
        return []
    try:
        tree = sqlglot.parse_one(sql, read="mysql")
        items = list(tree.selects) if isinstance(tree, (exp.Select, exp.SetOperation)) else []
    except Exception:  # noqa: BLE001 - only adds a fact: any SQL it cannot read adds none
        return []
    tables = [(table.name.lower(), (table.alias_or_name or "").lower()) for table in tree.find_all(exp.Table)]
    dictionary = data_dictionary()
    wanted = {name.lower() for name in names}
    facts = []
    for item in items:
        column = item.this if isinstance(item, exp.Alias) else item
        if not isinstance(column, exp.Column) or item.alias_or_name.lower() != column.name.lower():
            continue  # a name made by the query: explained from the query itself
        name = column.name.lower()
        if name not in wanted:
            continue
        qualifier = (column.table or "").lower()
        candidates = [table for table, alias in tables if not qualifier or qualifier in (alias, table)]
        for table in dict.fromkeys(candidates):
            meaning = dictionary.get(table, {}).get(name)
            if meaning:
                facts.append(f"{name} ({table}): " + meaning[:FACT_CHARS] + (" ..." if len(meaning) > FACT_CHARS else ""))
                wanted.discard(name)
                break
    return facts


def _names_a_column(columns, text, about):
    """True when the text names one of these query columns (see previous_query)."""
    return any(names_column(name, text) and (about or (made and len(_words(name).split()) > 1))
               for name, made in columns)


def _found(n, sql, columns, text):
    """previous_query's answer: the earlier answer's number (None = older than the memory's questions), SQL, column
    names and - only when a named column is a stored one the data dictionary explains - "facts"."""
    found = {"n": n, "sql": sql, "columns": [name for name, _ in columns]}
    facts = column_facts(sql, [name for name, made in columns if not made and names_column(name, text)])
    if facts:
        found["facts"] = facts
    return found


def previous_query(messages, text, history=None):
    """The earlier answer a question is about, when it is about that answer's own result - {"n": its number in the
    chat's history (as in sql_earlier; None = an older answer), "sql": its SQL, "columns": its column names, and
    "facts" for a named stored column (column_facts)} - else None (then no request gets anything more). A question
    is about it when it
    - names a column the earlier query made itself with a name of 2+ words (e.g. forecast_count = COUNT(*)), or
      names any of its columns together with a word like "mean", "why", "explain" or "column" - the latest answer
      with such a column wins: first among the questions the memory keeps, then (history = the ChatHistory, only when
      may_name_column) among the chat's older answers (ChatHistory.older_answers, at most LOOK_BACK); or
    - says "this column", "previous answer", "your last query", "why did you add ..." - the latest answer with a query
      among the questions the memory keeps.
    Only answers with SQL count (a general or documents answer has no columns)."""
    text = text or ""
    if not text.strip():
        return None
    answered = [(n, ai.additional_kwargs.get("sql") or "") for n, (_, ai) in enumerate(_pairs(messages), start=1)]
    answered = [(n, sql) for n, sql in answered if sql.strip()]
    about = bool(ABOUT_WORDS.search(text))
    for n, sql in reversed(answered):
        columns = query_columns(sql)
        if _names_a_column(columns, text, about):
            return _found(n, sql, columns, text)
    if history is not None and hasattr(history, "older_answers") and may_name_column(text):
        for sql in reversed(history.older_answers()):
            columns = query_columns(sql)
            if _names_a_column(columns, text, about):
                return _found(None, sql, columns, text)
    if answered and REFERS_TO_ANSWER.search(text):
        n, sql = answered[-1]
        return _found(n, sql, query_columns(sql), text)
    return None


def previous_query_text(found, shown=False):
    """The earlier answer's query for a request (agent.PREVIOUS_QUERY): its columns, its SQL on one line (cut to
    agent.PREVIOUS_QUERY_CHARS) and, when sql_words can read it, the same in plain words (0 tokens to make).
    shown=True (the SQL request, whose 'Earlier in this chat' already lists that SQL): only its number and columns."""
    columns = ", ".join(found["columns"]) or "not known"
    facts = agent.PREVIOUS_QUERY_STORED.format(facts="\n".join(found["facts"])) if found.get("facts") else ""
    if shown and found.get("n"):  # an older answer (n None) is not in 'Earlier in this chat': its SQL is written out
        return agent.PREVIOUS_QUERY_SHOWN.format(n=found["n"], columns=columns) + facts
    sql = " ".join(found["sql"].split())
    limit = agent.PREVIOUS_QUERY_CHARS
    words = " ".join(sql_words.describe_sql(found["sql"]))
    return agent.PREVIOUS_QUERY.format(columns=columns, sql=sql[:limit] + (" ..." if len(sql) > limit else ""),
                                       words=f"\nIn plain words: {words}" if words else "") + facts


# ------------------------------------------------------------------ a name of the previous answer's result
# 18-Nov (ML Insights chat): "which customers might stop buying from us?" listed Aurora Fluid Power Limited first;
# the follow-up "why is aurora on top?" got SQL with customer_name LIKE '%Aurora%' and an answer about another
# customer (Aurora CNC Systems Pvt. Ltd.). previous_names() finds such a word in the earlier answer's rows and gives
# the rewrite and SQL requests one checked fact line (agent.FOLLOW_UP_NAMES_*); the AI still writes SQL and answer.
# The rows are not saved, so the earlier answer's saved SQL runs again (read-only, like answer_check.py) - but only
# when a word of the follow-up is also in that answer's TEXT: any other follow-up costs no query and no tokens.
NAME_WORDS = 3          # at most this many words of one follow-up get a fact line
NAMES_LISTED = 3        # at most this many names are listed for one word
NAME_MAX_CHARS = 80     # a longer text cell is a sentence (a reason, a note), not a name
_ORDINARY = frozenset("""
    about above after again all also and answer answers any are because been before being below best biggest both
    bottom but buy buying can could customer customers data did does doing done down each explain first for from
    get give given gives got had has have her here high higher highest his how into its just last least less list
    low lower lowest made make many may might more most much name names not now number one only other our out over
    please pls previous product products rank ranked ranking reason result results row rows said same sales see she
    should show shown some stop than that the their them then there these they this those three top total two under
    very was were what when where which who whom whose why will with would yes you your
    jan feb mar apr may jun jul aug sep sept oct nov dec january february march april june july august september
    october november december
""".split())


def _name_words(text, sql):
    """The follow-up's words that may be part of a name, in order: 3+ letters, not only digits, not an ordinary
    question word (_ORDINARY) and not a word of the SQL itself (its tables, columns and SQL words - its quoted values
    left out), also without a plural s / es: "customers" is not a name when the SQL has customer_name."""
    in_sql = set(_words(re.sub(r"'(?:[^'\\]|\\.)*'", " ", sql or "")).split())
    found = []
    for word in _words(text).split():
        singular = {word, word[:-1] if word.endswith("s") else word, word[:-2] if word.endswith("es") else word}
        if (len(word) >= 3 and not word.isdigit() and word not in _ORDINARY and not singular & in_sql
                and word not in found):
            found.append(word)
    return found


def _names_in_rows(word, rows, typed):
    """{name: its first row number (1 = the first row)} of the text cells that have this word as a whole word and are
    MORE than it ("aurora" in "Aurora Fluid Power Limited", not the cell "Aurora" itself), in row order. A name the
    follow-up already writes out in full, and long text (a sentence), are left out."""
    found = {}
    for number, row in enumerate(rows or [], start=1):
        for cell in row:
            if not isinstance(cell, str) or len(cell) > NAME_MAX_CHARS:
                continue
            key = _words(cell)
            name = " ".join(cell.split())
            if f" {word} " in key and key.strip() != word and key not in typed and name not in found:
                found[name] = number
    return found


def _names_text(words, data, which, text):
    """The fact lines (agent.FOLLOW_UP_NAME_ONE / _SEVERAL) for the words found in the rows - '' when none is. The
    words of a name the follow-up writes out in full ("why is Aurora Fluid Power Limited on top?") get none."""
    typed, facts = _words(text), []
    written_out = {_words(cell) for row in data.get("rows") or [] for cell in row
                   if isinstance(cell, str) and len(cell) <= NAME_MAX_CHARS and _words(cell) in typed}
    for word in words:
        if any(f" {word} " in key for key in written_out):
            continue
        names = _names_in_rows(word, data.get("rows"), typed)
        if not names:
            continue
        listed = list(names.items())[:NAMES_LISTED]
        first = listed[0][1]
        if len(names) == 1:
            facts.append(agent.FOLLOW_UP_NAME_ONE.format(which=which, word=word, name=listed[0][0], row=first))
        else:
            more = len(names) - len(listed)
            facts.append(agent.FOLLOW_UP_NAME_SEVERAL.format(
                which=which, word=word, count=len(names), row=first,
                names=", ".join(f"{name} (row {row})" for name, row in listed),
                more=f" and {more} more" if more else ""))
        if len(facts) == NAME_WORDS:
            break
    return "\n".join(facts)


def previous_names(messages, text, result=None):
    """The fact lines for a follow-up that names part of a name in an earlier answer's result, e.g.
    'In the previous answer, "aurora" = Aurora Fluid Power Limited (row 1 of its result).' - '' for anything else.
    The newest earlier answer with SQL whose answer text has one of the follow-up's name words (_name_words) is used:
    its saved SQL runs again through the guard (sql_guard.check_sql + warehouse.run_select, read-only), and each word
    is looked up in the text cells of its rows. No such answer: no query. The SQL failing (or MySQL down): ''.
    result = the AskResult the query's seconds are added to (step "mysql")."""
    pairs = _pairs(messages)
    for n in range(len(pairs), 0, -1):
        ai = pairs[n - 1][1]
        sql = ai.additional_kwargs.get("sql") or ""
        if not sql.strip():
            continue
        answer = _words(ai.content)
        words = [word for word in _name_words(text, sql) if f" {word} " in answer]
        if not words:
            continue
        started = time.perf_counter()
        try:
            data = warehouse.run_select(check_sql(sql))
        except Exception as exc:  # noqa: BLE001 - only adds a hint: a query that does not run again adds nothing
            log.info("Follow-up names skipped: the earlier SQL did not run again: %s", exc)
            return ""
        finally:
            if result is not None:
                result.add_secs("mysql", time.perf_counter() - started)
        which = "the previous answer" if n == len(pairs) else f"earlier answer {n}"
        return _names_text(words, data, which, text)
    return ""
