"""LangGraph: the steps of one question as a graph (a StateGraph) instead of plain if / for code.

    START -> load_memories (the user's saved memories) -> rewrite (only in a chat with earlier questions) -> route
    route -> answer_from_documents -> END                     a question about the company PDFs
          -> search_notes -> pick_schema -> write_sql          a question about the data (or 'both')
    write_sql -> END (refused: NO_SQL, or nodata: NO_DATA)
              -> check_sql (SQL guard + checks) -> run_sql (read-only MySQL)
    write_sql / check_sql / run_sql with a problem -> retry -> write_sql again, while tries < MAX_TRIES;
              after the last try -> failed (the "3 tries" answer) -> END
    run_sql -> explain -> END                                  rows came back
            -> check_names -> END (a typed name matches nothing: a fixed answer, no AI call) / explain
    run_sql with ONE row for a line chart / trend -> retry -> write_sql once more (one row per period);
            that try gives no better rows -> keep_first_answer (the first rows) -> explain

A question about the data AND the documents ('both': "top 3 export customers ... and what are the payment terms
for export customers?") takes the data path with every rule as it is; explain then also gets the closest PDF
pieces, so ONE answer covers both parts. When its data part gives no answer (refused, nodata, failed, a name
not found), documents_part still answers the documents part, with one sentence about the data part.

The nodes reuse the functions, rules and texts of rag/agent.py (the router, the document answer, the SQL
checks, explain ...); the graph only says which step comes after which. The state carries the AskResult,
which collects the status, answer, SQL, rows, sources, tokens and seconds per step as before
(agent._ask_ai, agent._timed). An error inside a node leaves the graph as the same exception (LangGraph only
adds a note to it), so agent.ask() turns it into the same friendly message.

Two ways to run it: run() (GRAPH.invoke - the JSON API, the eval, the MCP server) and run_events() for the
streamed Ask page: GRAPH.stream with LangGraph's "custom" stream mode, where each step says when it starts
({"type": "step", "label": ...} with its STEP_NAMES label) and the final answer step sends its reply piece by
piece ({"type": "token", "text": ...}). The steps, prompts and saving are the same in both.

No checkpointer (LangGraph's own store for a conversation): the chat memory is our History DB. run() puts
the chat's earlier questions (lc.memory.ChatHistory, read from MySQL) into the state at the start, and
agent.ask() saves the new Question row with its SQL, rows and tokens - one database for the History page
and the memory.

The user's long-term memory (portal/user_memory.py: "Remember that I only work with export sales") is another
thing: load_memories reads it into the state first, and the SQL, answer and documents prompts get it as their
{preferences} block - in every chat of that user. No memories = the prompts exactly as without it.
"""
import functools
import re
import threading
import time
from typing import TypedDict

from django.db import connections
from django.utils import timezone
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from .. import user_memory
from ..rag import agent, store, warehouse
from ..rag.sql_guard import GuardError
from .calls import LcRequest
from .memory import latest_question, messages_of, sql_earlier

log = agent.log  # the same log lines as before the graph

# one SQL try is up to 4 steps (write, check, run, retry) and the rest of a question about 8:
# 3 tries need about 20 steps; LangGraph stops a run that takes more than this many
RECURSION_LIMIT = 50

# 05-Nov: "for that above answer create one line chart" got a query of ONE row (one month's total), so no chart
# could be drawn. A line chart or a trend needs one row per period: such a question with one row is sent back once.
# A bar / pie chart of one row is not sent back - the Ask page says why there is no chart.
LINE_CHART_WORDS = re.compile(r"\bline\s*-?\s*(?:chart|graph|plot|diagram)s?\b|\btrend(?:s|lines?)?\b|\bover\s+time\b",
                              re.I)
ONE_ROW_LINE_CHART_PROBLEM = ("your query returned only 1 row, but this question asks for a line chart / trend - a "
                              "line chart needs one row per period: return the last periods (e.g. the last 6 NOP "
                              "months, or every period the earlier answer covered), one row per period, ordered by "
                              "period; dim_calendar has one row per day - use SELECT DISTINCT for the period list.")


def line_chart_request(text):
    """True when the question (typed + understood as) asks for a line chart, a line graph or a trend."""
    return bool(LINE_CHART_WORDS.search(text or ""))


class AskState(TypedDict, total=False):
    """What the steps of one question hand on to each other."""
    result: object            # the agent.AskResult the steps fill in (status, answer, SQL, rows, tokens, seconds)
    user: object              # who asks (None = no saved memories are used)
    memories: list            # the user's saved memories as texts, oldest first ([] = none)
    memory: list              # the chat's earlier questions as LangChain messages ([] = none, or a new question)
    asked: str                # the question the router and the SQL step answer (a follow-up written out in full)
    route: str                # 'data' | 'documents' | 'both' (the router's choice)
    pdf_hits: list            # the PDF pieces to answer from ([] = the data path)
    streaming: bool           # run_events(): the steps announce themselves and the answer is streamed
    memories_loaded: bool     # run_events() read the memories before the graph (its steps run in another thread)
    caller_thread: int        # the thread that runs the question (a step in another thread closes its DB link)
    hits: list                # the notes closest to the question
    allowed: set              # the ai_gold tables the SQL may use
    full_schema_shown: bool   # the SQL call already saw every table
    sql_values: dict          # the values of the SQL prompt template
    retries: list             # the failed tries: the AI's reply (AIMessage) + what was wrong (HumanMessage)
    attempt: int              # the SQL try (1 to MAX_TRIES)
    reply: str                # the AI's last SQL reply
    kind: str                 # what that reply was: 'sql' | 'no_sql' | 'no_data' | 'empty'
    sql: str                  # the SQL of that reply
    missing: str              # its MISSING line: one part of the question has no data
    problem: str              # what was wrong with this try ('' = nothing)
    schema_not_needed: bool   # the retry is about values or wording, not tables: no full schema
    schema_note: str          # the full schema, once it was added to a retry
    cleaned: str              # the SQL after the guard and the date fixes
    last_sql: str             # the last SQL the AI wrote (for the error text after 3 failed tries)
    name_check_used: bool     # a query that adds name matches into one number is sent back only once
    profit_switched: bool     # a profit % between two periods is sent back once for the revenue growth
    chart_retry_used: bool    # a chart question of NOP data that got NO_SQL is sent back once
    values_checked: bool      # a query that found no data has its filter values checked once
    year_check_used: bool     # a quarter / month number grouped over all years is sent back once
    today_check_used: bool    # a period not over yet, counted past today, is sent back once
    one_row_retry_used: bool  # a line chart / trend question with only 1 row is sent back once
    first_answer: dict        # the 1-row answer kept while that retry runs ({} = none): its try, SQL, data, notes
    not_found: str            # the fixed answer when a typed name matches nothing


# ------------------------------------------------------------------ the steps (nodes)
def load_memories(state):
    """The user's saved memories (user_memory.texts_for) for the SQL, answer and documents prompts - read
    from MySQL once per question, so a memory saved in one chat is used in every other chat."""
    if state.get("memories_loaded"):  # run_events() read them already, in the question's own thread
        return {}
    return {"memories": user_memory.texts_for(state["user"])}


def rewrite(state):
    """A follow-up ("can I get the above with profit %") is first written out as a full question by its own
    small AI call - far more reliable than asking for it on the side. A question of its own is answered like
    the first one of a chat: an earlier question's period must not slip into it (13-Oct: "top customer in
    japan" after two Sep 2026 questions -> no data)."""
    result = state["result"]
    understood = agent.rewrite_follow_up(result, state["memory"])
    if understood is None:
        return {"memory": []}
    result.understood_as = understood
    return {"asked": result.understood_as or result.text}


def route(state):
    """Data, documents or both (agent.route_question), with the PDF pieces to answer from ([] for the data)."""
    chosen, hits = agent.route_question(state["result"], state["asked"])
    return {"route": chosen, "pdf_hits": hits}


def answer_from_documents(state):
    """A question about the company documents (warranty, discount rules ...) is answered from the PDFs only."""
    agent.answer_from_documents(state["result"], state["pdf_hits"], state["memories"],
                                on_token=_token_sender(state, documents=True))
    return {}


def documents_part(state):
    """A 'both' question whose data part gave no answer: the documents part is still answered from the PDFs,
    with one sentence about the data part (agent.answer_documents_part)."""
    agent.answer_documents_part(state["result"], state["pdf_hits"], state["memories"],
                                on_token=_token_sender(state, documents=True))
    return {}


def search_notes(state):
    """The pieces of docs/ closest to the question. A follow-up that was not written out is read together with
    the question before it, so "and for export?" still finds the sales pieces."""
    result = state["result"]
    search_text = state["asked"]
    if state["memory"] and not result.understood_as:
        search_text = f"{latest_question(state['memory'])} {result.text}"
    store.last_search.embed_secs = None
    started = time.perf_counter()
    try:
        hits = agent.search(search_text, top_k=agent.TOP_K)
    finally:  # the embedding is timed inside the search; the rest is Qdrant's search
        embed_secs = getattr(store.last_search, "embed_secs", None)
        if embed_secs is not None:
            result.add_secs("embed", embed_secs)
        result.add_secs("search", time.perf_counter() - started - (embed_secs or 0.0))
    result.sources = [{"heading": h["heading"], "kind": h["kind"], "source": h["source"],
                       "score": h["score"]} for h in hits]
    return {"hits": hits}


def pick_schema(state):
    """The tables and columns the SQL call shows, and the values of its prompt template."""
    result, hits = state["result"], state["hits"]
    with agent._timed(result, "schema"):
        allowed = warehouse.allowed_tables()
        schema, full_schema_shown = agent.schema_for_prompt(state["asked"], hits)
    sql_values = dict(
        schema=schema,
        count=len(hits),
        documents="\n\n---\n\n".join(agent.compact_notes(h["text"]) for h in hits),
        today=timezone.localdate().strftime("%d-%b-%Y (%A)"),
        preferences=agent.preferences(state["memories"], "sql"),
        earlier=sql_earlier(state["memory"]),
        question=result.text + (f"\n(Written out in full: {result.understood_as})" if result.understood_as else "")
        + (agent.SQL_BOTH_NOTE if state["route"] == "both" else ""),
    )
    return {"allowed": allowed, "full_schema_shown": full_schema_shown, "sql_values": sql_values}


def write_sql(state):
    """The AI writes the SQL: LangChain's SQL chain with the prompt values and the failed tries so far.
    NO_SQL -> refused (a chart question of NOP data: first sent back once); NO_DATA -> nodata (or, once, the revenue growth for a profit % between two periods);
    a reply without SQL -> a retry."""
    result, attempt = state["result"], state["attempt"] + 1
    result.tries = attempt
    request = LcRequest("sql", state["sql_values"], retries=list(state["retries"]))
    try:
        reply = agent._ask_ai(request, agent.SQL_MAX_TOKENS, "medium", result, step="sql")
    except agent.RequestTooLarge:
        # 22-Oct: a retry with the full schema asked for 8,071 tokens, over the 8,000 a minute: send it without
        schema_note = state["schema_note"]
        if not schema_note or schema_note not in request.retries[-1].content:
            raise
        log.info("Retry too large for Groq's tokens per minute - sent again without the full schema")
        request.retries[-1] = HumanMessage(request.retries[-1].content.replace(schema_note, ""))
        reply = agent._ask_ai(request, agent.SQL_MAX_TOKENS, "medium", result, step="sql")
    kind, sql = agent.read_sql_reply(reply)
    update = {"attempt": attempt, "retries": request.retries, "reply": reply, "kind": kind, "sql": sql,
              "problem": "", "schema_not_needed": False}
    if kind == "no_sql":  # off-topic, a request to change data, or an attempt to bend the rules
        if (not state["chart_retry_used"] and attempt < agent.MAX_TRIES
                and agent.chart_request(f"{result.text} {result.understood_as}")):
            # 05-Nov: "Create a line chart of last month's sales" was read as a CREATE: sent back once
            update.update(chart_retry_used=True, schema_not_needed=True, problem=agent.CHART_NOT_A_CHANGE_PROBLEM)
            return update
        result.status, result.answer = "refused", agent.REFUSAL_ANSWER
        return update
    no_data, try_question, missing = agent.data_notes(reply)
    if missing and not agent.missing_was_asked(missing, f"{result.text} {result.understood_as}"):
        log.info("MISSING line dropped - the question did not ask for it: %s", missing)
        missing = ""
    update["missing"] = missing
    if kind == "no_data":  # a NOP business question, but nothing in it is in ai_gold (e.g. profit)
        if (try_question and not state["profit_switched"] and attempt < agent.MAX_TRIES
                and agent.profit_comparison(state["asked"])):
            # the model said "not available" although NOP wants the revenue growth + a note:
            # keep its reason for the answer and ask once more for the revenue SQL
            result.notes.append(agent.MISSING_NOTE.format(missing=(no_data or "profit").rstrip(".")))
            update.update(profit_switched=True, schema_not_needed=True,
                          problem=agent.PROFIT_GROWTH_PROBLEM.format(question=try_question.strip('"')))
        else:
            reason = no_data or agent.NO_DATA_DEFAULT
            result.status = "nodata"
            result.answer = agent.NO_DATA_ANSWER.format(
                reason=reason if reason.endswith((".", "!", "?")) else reason + ".")
            if try_question:
                result.answer += agent.NO_DATA_TRY.format(question=try_question.strip('"'))
    elif kind == "empty":
        update["problem"] = "your reply had no SQL."
    else:
        update["last_sql"] = sql
    return update


def check_sql(state):
    """The SQL guard, then the checks that send a wrong query back before it runs: a month written as text
    compared with BETWEEN / < / >, a quarter / month number over all years, all LIKE name matches added into
    one number, a period not over yet (FY 2026-27 on 03-Nov-2026) without "up to today". The last try runs as
    it is."""
    result = state["result"]
    with agent._timed(result, "check"):
        try:
            cleaned = agent.fy_period_dates(agent.order_months_by_date(agent.check_sql(state["sql"], state["allowed"])))
        except GuardError as exc:
            return {"problem": f"the SQL guard refused the query: {exc}"}
        if state["attempt"] >= agent.MAX_TRIES:
            return {"cleaned": cleaned}
        column = agent.month_text_ranges(cleaned)
        if column:
            return {"problem": agent.MONTH_RANGE_PROBLEM.format(column=column), "schema_not_needed": True}
        if not state["year_check_used"]:
            column = agent.parts_without_year(cleaned)
            if column:
                return {"year_check_used": True, "schema_not_needed": True,
                        "problem": agent.PART_WITHOUT_YEAR_PROBLEM.format(column=column)}
        if not state["name_check_used"]:
            column = agent.summed_name_matches(cleaned)
            if column:
                return {"name_check_used": True, "problem": agent.NAME_MATCHES_PROBLEM.format(column=column)}
        if not state["today_check_used"]:
            # 03-Nov: "FY 2026-27 so far" was summed with the invoices dated up to 20-Mar-2027
            labels = agent.periods_not_over(cleaned)
            if labels:
                return {"today_check_used": True, "schema_not_needed": True,
                        "problem": agent.PERIOD_NOT_OVER_PROBLEM.format(label=" and ".join(labels), today=agent.today())}
    return {"cleaned": cleaned}


def run_sql(state):
    """The checked SQL runs on the read-only MySQL. A query that found no data has its filter values
    checked once: a value the column does not have goes back to the AI."""
    result, cleaned = state["result"], state["cleaned"]
    update = {}
    try:
        with agent._timed(result, "mysql"):
            data = warehouse.run_select(cleaned)
        if (not state["values_checked"] and not state["first_answer"] and state["attempt"] < agent.MAX_TRIES
                and agent.found_nothing(data["rows"])):
            update["values_checked"] = True
            with agent._timed(result, "check"):
                wrong = agent.unknown_values(cleaned, state["allowed"])
            if wrong:
                # 22-Oct: with the full schema the retry was over Groq's 8,000 tokens a minute
                return {**update, "schema_not_needed": True,
                        "problem": agent.UNKNOWN_VALUES_PROBLEM.format(wrong="; ".join(wrong))}
    except warehouse.QueryError as exc:
        return {**update, "problem": f"MySQL returned an error: {exc}"}
    if (not state["one_row_retry_used"] and state["attempt"] < agent.MAX_TRIES and len(data["rows"]) == 1
            and line_chart_request(f"{result.text} {result.understood_as}")):
        # a line chart needs one row per period: sent back once; the 1-row answer is kept in case that try
        # gives nothing better (keep_first_answer) - an answered question never becomes an error
        return {**update, "one_row_retry_used": True, "schema_not_needed": True,
                "problem": ONE_ROW_LINE_CHART_PROBLEM,
                "first_answer": {"attempt": state["attempt"], "sql": cleaned, "data": data,
                                 "missing": state["missing"], "notes": list(result.notes)}}
    _keep_rows(result, cleaned, data, state["missing"])
    return update


def _keep_rows(result, cleaned, data, missing):
    """The rows that came back become the answer's rows, with the notes for the answer call."""
    result.status = "ok"
    result.sql = cleaned
    result.columns, result.rows = data["columns"], data["rows"]
    result.truncated = data["truncated"]
    if missing:  # one part of a mixed question has no data: the answer says so
        result.notes.append(agent.MISSING_NOTE.format(missing=missing.rstrip(".")))
    for label in agent.periods_not_over(cleaned):  # the AI kept rows dated after today: the answer says so
        result.notes.append(agent.AFTER_TODAY_NOTE.format(today=agent.today(), label=label))


def keep_first_answer(state):
    """The line chart retry gave no better rows (again 1 row, no rows, NO_SQL / NO_DATA, or a query that failed):
    the first 1-row answer is kept and explained as it was. Its tries and tokens still count both SQL calls."""
    result, first = state["result"], state["first_answer"]
    log.info("Line chart retry gave no better rows - the first answer is kept")
    result.answer, result.notes = "", list(first["notes"])
    _keep_rows(result, first["sql"], first["data"], first["missing"])
    return {"problem": ""}


def retry(state):
    """A failed try goes back to the AI: its reply + what was wrong (RETRY_PROMPT). A question whose first
    try saw only some tables now gets every table - the columns of the tables it did not see (the others are
    in the first request above it) - unless the problem was about values or wording."""
    log.info("Ask NOP try %s failed: %s", state["attempt"], state["problem"])
    text = agent.RETRY_PROMPT.format(problem=state["problem"])
    update = {}
    if not state["full_schema_shown"] and not state["schema_not_needed"]:
        shown = set(state["sql_values"]["schema"].splitlines())
        schema_note = agent.OTHER_TABLES_NOTE.format(
            schema="\n".join(line for line in warehouse.schema_text().splitlines() if line not in shown))
        text += schema_note
        update.update(schema_note=schema_note, full_schema_shown=True)
    update["retries"] = state["retries"] + [AIMessage(state["reply"] or "(empty reply)"), HumanMessage(text)]
    return update


def failed(state):
    """Every try failed: the fixed "3 tries" answer, with the last problem and SQL for the admin."""
    result = state["result"]
    log.info("Ask NOP try %s failed: %s", state["attempt"], state["problem"])
    result.status, result.answer = "error", agent.FAILED_ANSWER
    result.error = f"{agent.MAX_TRIES} tries failed. Last problem: {state['problem']}\nLast SQL:\n{state['last_sql']}"
    return {}


def check_names(state):
    """An empty result: a name typed in the question (LIKE '%...%') that matches nothing gets a fixed, clear
    answer - no second AI call and no tokens. Names that do match become notes for the answer call."""
    result = state["result"]
    with agent._timed(result, "check"):
        not_found, name_notes = agent.name_search_notes(result, state["allowed"])
    if not_found:
        result.answer = not_found
        if state["missing"]:
            result.answer += f" Also, this is not in the NOP data: {state['missing'].rstrip('.')}."
        return {"not_found": not_found}
    result.notes.extend(name_notes)
    return {}


def explain(state):
    """The AI explains the rows in plain English; when it cannot, the rows are still shown. A 'both' question
    also gets the PDF pieces, so the one answer covers the documents part too (and their pages are sources)."""
    result = state["result"]
    both = state["pdf_hits"] if state["route"] == "both" else []
    if both:
        result.sources = result.sources + agent.pdf_sources(both)
    try:
        result.answer = agent.explain(result, state["memories"], both, on_token=_token_sender(state)) \
            or agent.ROWS_ONLY_ANSWER
    except agent.AIUnavailable as exc:  # the rows are still worth showing
        result.answer = agent.ROWS_ONLY_ANSWER
        result.error = f"Answer not written: {exc}"
    else:
        if result.answer != agent.ROWS_ONLY_ANSWER:
            result.answer += agent.unnamed_groups_sentence(result)
    return {}


# ------------------------------------------------------------------ the streamed run
# the label each step shows on the streamed Ask page while it runs (the time box's labels, agent.STEP_NAMES);
# steps without one (memories, retry, failed) are quick and need no line of their own
_LABELS = dict(agent.STEP_NAMES)
NODE_LABELS = {
    "rewrite": _LABELS["rewrite"], "route": _LABELS["pdf_search"], "answer_from_documents": _LABELS["answer_ai"],
    "documents_part": _LABELS["answer_ai"], "search_notes": _LABELS["search"], "pick_schema": _LABELS["schema"],
    "write_sql": _LABELS["sql_ai"], "check_sql": _LABELS["check"], "run_sql": _LABELS["mysql"],
    "check_names": _LABELS["check"], "explain": _LABELS["answer_ai"],
}


def _announced(node):
    """The step, telling the streamed Ask page when it starts (a 'step' event; a later SQL try says which try).
    LangGraph runs a streamed step in a thread of its own: a database link that step opened is closed after it."""
    @functools.wraps(node)
    def step(state):
        if not state.get("streaming"):
            return node(state)
        label = NODE_LABELS.get(node.__name__)
        if label:
            if node.__name__ == "write_sql" and state["attempt"]:
                label += f" - try {state['attempt'] + 1}"
            get_stream_writer()({"type": "step", "label": label})
        try:
            return node(state)
        finally:
            if threading.get_ident() != state.get("caller_thread"):
                connections.close_all()
    return step


NOT_IN_DOCUMENTS = "NOT_IN_DOCUMENTS"


def _token_sender(state, documents=False):
    """The on_token of the final answer step: each piece of the reply as a 'token' event (None when not
    streamed). documents=True: the first characters wait until it is clear the reply is not the one-line
    NOT_IN_DOCUMENTS (that reply is never shown as text: the final card says it in plain words)."""
    if not state.get("streaming"):
        return None
    writer = get_stream_writer()
    held = {"text": "", "mode": "wait" if documents else "send"}

    def send(text):
        if held["mode"] == "send":
            writer({"type": "token", "text": text})
            return
        if held["mode"] == "quiet":
            return
        held["text"] += text
        start = held["text"].lstrip().upper()
        if len(start) < len(NOT_IN_DOCUMENTS) and NOT_IN_DOCUMENTS.startswith(start):
            return  # still could be NOT_IN_DOCUMENTS
        held["mode"] = "quiet" if start.startswith(NOT_IN_DOCUMENTS) else "send"
        if held["mode"] == "send":
            writer({"type": "token", "text": held["text"]})
    return send


# ------------------------------------------------------------------ which step comes next (edges)
def chat_or_not(state):
    return "in a chat" if state["memory"] else "no chat"


def documents_or_data(state):
    """The documents path, or the data path - also for 'both' (its documents part is in the explain step)."""
    return "documents" if state["route"] == "documents" else "data / both"


def retry_or_fail(state):
    """Another try while tries are left, else the "3 tries" answer."""
    return "retry" if state["attempt"] < agent.MAX_TRIES else "failed"


def _both(label, state):
    """A 'both' question still answers its documents part when the data part ends without rows."""
    return f"{label} (both)" if state["route"] == "both" else label


def _first_kept(state):
    """The line chart retry ran (a try after the 1-row one): anything but rows of its own keeps the first answer
    (it is never sent back again)."""
    first = state["first_answer"]
    return bool(first) and state["attempt"] > first["attempt"]


def after_write_sql(state):
    if _first_kept(state) and (state["problem"] or state["kind"] in ("no_sql", "no_data")):
        return "keep the first answer"
    if state["problem"]:  # no SQL in the reply, or the profit-growth switch
        return retry_or_fail(state)
    return _both("refused / nodata", state) if state["kind"] in ("no_sql", "no_data") else "check"


def after_check_sql(state):
    if state["problem"]:
        return "keep the first answer" if _first_kept(state) else retry_or_fail(state)
    return "run"


def after_run_sql(state):
    if _first_kept(state) and (state["problem"] or len(state["result"].rows) < 2):
        return "keep the first answer"
    if state["problem"]:
        return retry_or_fail(state)
    return "rows" if state["result"].rows else "no rows"


def after_failed(state):
    return _both("done", state)


def after_check_names(state):
    return _both("name not found", state) if state["not_found"] else "explain"


def build():
    """The graph of one question (not compiled)."""
    graph = StateGraph(AskState)
    for node in (load_memories, rewrite, route, answer_from_documents, search_notes, pick_schema, write_sql,
                 check_sql, run_sql, retry, failed, keep_first_answer, check_names, explain, documents_part):
        graph.add_node(node.__name__, _announced(node))
    graph.add_edge(START, "load_memories")
    graph.add_conditional_edges("load_memories", chat_or_not, {"in a chat": "rewrite", "no chat": "route"})
    graph.add_edge("rewrite", "route")
    graph.add_conditional_edges("route", documents_or_data, {"documents": "answer_from_documents",
                                                             "data / both": "search_notes"})
    graph.add_edge("answer_from_documents", END)
    graph.add_edge("search_notes", "pick_schema")
    graph.add_edge("pick_schema", "write_sql")
    graph.add_conditional_edges("write_sql", after_write_sql, {"refused / nodata": END, "retry": "retry",
                                                               "refused / nodata (both)": "documents_part",
                                                               "failed": "failed", "check": "check_sql",
                                                               "keep the first answer": "keep_first_answer"})
    graph.add_conditional_edges("check_sql", after_check_sql, {"retry": "retry", "failed": "failed", "run": "run_sql",
                                                               "keep the first answer": "keep_first_answer"})
    graph.add_conditional_edges("run_sql", after_run_sql, {"retry": "retry", "failed": "failed", "rows": "explain",
                                                           "no rows": "check_names",
                                                           "keep the first answer": "keep_first_answer"})
    graph.add_edge("retry", "write_sql")
    graph.add_edge("keep_first_answer", "explain")
    graph.add_conditional_edges("failed", after_failed, {"done": END, "done (both)": "documents_part"})
    graph.add_conditional_edges("check_names", after_check_names, {"name not found": END, "explain": "explain",
                                                                   "name not found (both)": "documents_part"})
    graph.add_edge("explain", END)
    graph.add_edge("documents_part", END)
    return graph


GRAPH = build().compile()  # compiled once, used by every question


def start_state(result, context=(), user=None):
    """The state a question starts with: its AskResult, the chat's memory (a lc.memory.ChatHistory read
    from the History DB, or the earlier Questions) as messages, and who asks (load_memories reads his
    saved memories)."""
    return {
        "result": result, "user": user, "memories": [], "memory": messages_of(context), "asked": result.text,
        "route": "data", "pdf_hits": [], "hits": [],
        "retries": [], "attempt": 0, "problem": "", "missing": "", "last_sql": "", "schema_note": "",
        "not_found": "", "schema_not_needed": False, "name_check_used": False, "profit_switched": False,
        "chart_retry_used": False, "one_row_retry_used": False, "first_answer": {},
        "values_checked": False, "year_check_used": False, "today_check_used": False,
    }


def run(result, context=(), user=None):
    """Answer one question through the graph; fills in the AskResult. user = whose saved memories are used."""
    GRAPH.invoke(start_state(result, context, user), {"recursion_limit": RECURSION_LIMIT})
    return result


def run_events(result, context=(), user=None):
    """run() for the streamed Ask page: a generator that yields the progress events while the graph runs -
    {"type": "step", "label": ...} as each step starts and {"type": "token", "text": ...} for each piece of the
    final answer (LangGraph's "custom" stream mode) - and returns the filled-in AskResult. The user's memories
    are read here, in the question's own thread (LangGraph runs streamed steps in a thread of its own)."""
    state = start_state(result, context, user)
    state.update(streaming=True, memories_loaded=True, memories=user_memory.texts_for(user),
                 caller_thread=threading.get_ident())
    yield from GRAPH.stream(state, {"recursion_limit": RECURSION_LIMIT}, stream_mode="custom")
    return result


def mermaid():
    """The graph as a Mermaid flowchart (text; design/langgraph_flow.mmd)."""
    return GRAPH.get_graph().draw_mermaid()
