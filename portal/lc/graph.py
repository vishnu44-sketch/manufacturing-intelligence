"""LangGraph: the steps of one question as a graph (a StateGraph) instead of plain if / for code.

    START -> load_memories (the user's saved memories) -> rewrite (only in a chat with earlier questions) -> route
    route -> answer_from_documents -> END                     a question about the company PDFs
          -> general_answer -> END                            not about the data or the documents ('general')
          -> search_notes -> pick_schema -> write_sql          a question about the data (or 'both')
    write_sql -> END (refused: NO_SQL, or nodata: NO_DATA)
              -> general_answer -> END (GENERAL: the router did not run, the SQL writer saw it is off-topic)
              -> check_sql (SQL guard + checks) -> run_sql (read-only MySQL)
    write_sql / check_sql / run_sql with a problem -> retry -> write_sql again, while tries < MAX_TRIES;
              after the last try -> failed (the "3 tries" answer) -> END
    run_sql -> explain -> END                                  rows came back
            -> check_names -> END (a typed name matches nothing: a fixed answer, no AI call) / explain
    run_sql with ONE row for a line chart / trend -> retry -> write_sql once more (one row per period);
            that try gives no better rows -> keep_first_answer (the first rows) -> explain
    run_sql with rows that name none of the customers / products ... the question ranks ("top customers of X"
            answered with X's total) -> retry once the same way, keep_first_answer when that try is no better

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

from .. import ai_hints, user_memory
from ..rag import agent, store, warehouse
from ..rag.sql_guard import GuardError
from .calls import LcRequest
from .memory import latest_question, messages_of, previous_names, previous_query, previous_query_text, sql_earlier

log = agent.log  # the same log lines as before the graph

# one SQL try is up to 4 steps (write, check, run, retry) and the rest of a question about 8:
# 3 tries need about 20 steps; LangGraph stops a run that takes more than this many
RECURSION_LIMIT = 50

# 05-Nov: "for that above answer create one line chart" got a query of ONE row (one month's total), so no chart
# could be drawn. A line chart or a trend needs one row per period: such a question with one row is sent back once.
# 16-Nov: "a bar graph for the last 6 month of sales" got one row too - any chart of SEVERAL periods ("last 6
# months", "monthly", "each month") with one row is sent back the same way. A chart of one period is not.
LINE_CHART_WORDS = re.compile(r"\bline\s*-?\s*(?:chart|graph|plot|diagram)s?\b|\btrend(?:s|lines?)?\b|\bover\s+time\b",
                              re.I)
ONE_ROW_LINE_CHART_PROBLEM = ("your query returned only 1 row, but this question asks for a line chart / trend or "
                              "a chart of several periods - it needs one row per period: return the last periods (e.g. the last 6 sales "
                              "months, or every period the earlier answer covered), one row per period, ordered by "
                              "period; dim_calendar has one row per day - use SELECT DISTINCT for the period list.")


def line_chart_request(text):
    """True when the question (typed + understood as) asks for a line chart, a line graph or a trend."""
    return bool(LINE_CHART_WORDS.search(text or ""))


SEVERAL_PERIODS = re.compile(
    r"\b(?:last|past|previous|recent)\s+(?:\d+|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|few|several)"
    r"\s+(?:sales\s+)?(?:calendar\s+)?(?:months?|quarters?|years?|weeks?|days?|periods?)\b"
    r"|\b(?:monthly|quarterly|yearly|weekly|daily|month[\s-]*wise|month[\s-]*by[\s-]*month)\b"
    r"|\b(?:each|every|per|by)\s+(?:sales\s+)?(?:month|quarter|year|week|day|period)\b", re.I)


def several_periods_chart_request(text):
    """True when the question asks for a chart (any kind) of several periods: "a bar graph for the last 6 months",
    "monthly sales as a pie chart". A line chart / trend counts too (line_chart_request)."""
    text = text or ""
    return line_chart_request(text) or bool(agent.CHART_WORDS.search(text) and SEVERAL_PERIODS.search(text))


class AskState(TypedDict, total=False):
    """What the steps of one question hand on to each other."""
    result: object            # the agent.AskResult the steps fill in (status, answer, SQL, rows, tokens, seconds)
    user: object              # who asks (None = no saved memories are used)
    memories: list            # the user's saved memories as texts, oldest first ([] = none)
    memory: list              # the chat's earlier questions as LangChain messages ([] = none, or a new question)
    chat: list                # the same messages, kept also for a new question (the general answer follows the chat)
    history: object           # the lc.memory.ChatHistory of a saved chat (None = none): previous_query reads its
                              # older answers only for a question that may name a column ("what does low_inr mean?")
    previous_query: dict      # the earlier answer this question is about ("what does forecast_count mean?"): its
                              # number, SQL and columns (lc.memory.previous_query; {} = not about one)
    previous_names: str       # the fact lines for a follow-up word that is part of a name in an earlier answer's rows
                              # ("aurora" = Aurora Fluid Power Limited; lc.memory.previous_names; '' = none)
    asked: str                # the question the router and the SQL step answer (a follow-up written out in full)
    route: str                # 'data' | 'documents' | 'both' | 'general' (the router's choice)
    pdf_hits: list            # the PDF pieces to answer from ([] = the data path)
    streaming: bool           # run_events(): the steps announce themselves and the answer is streamed
    memories_loaded: bool     # run_events() read the memories before the graph (its steps run in another thread)
    caller_thread: int        # the thread that runs the question (a step in another thread closes its DB link)
    hits: list                # the notes closest to the question
    allowed: set              # the ss_gold tables the SQL may use
    full_schema_shown: bool   # the SQL call already saw every table
    sql_values: dict          # the values of the SQL prompt template
    backup_values: dict       # ML mode: the backup model's own notes and schema (LcRequest.backup; {} = none)
    retries: list            # the failed tries: the AI's reply (AIMessage) + what was wrong (HumanMessage)
    attempt: int              # the SQL try (1 to MAX_TRIES)
    reply: str                # the AI's last SQL reply
    kind: str                 # what that reply was: 'sql' | 'no_sql' | 'no_data' | 'general' | 'empty' | 'remember' | 'forget'
    sql: str                  # the SQL of that reply
    missing: str              # its MISSING line: one part of the question has no data
    asks_for: str             # its ASKS_FOR line: what the question ranks or lists (ai_hints.asks_for; '' = none)
    periods: object           # its PERIODS line: how many periods the question asks for (int; None = none)
    problem: str              # what was wrong with this try ('' = nothing)
    schema_not_needed: bool   # the retry is about values or wording, not tables: no full schema
    schema_note: str          # the full schema, once it was added to a retry
    cleaned: str              # the SQL after the guard and the date fixes
    last_sql: str             # the last SQL the AI wrote (for the error text after 3 failed tries)
    name_check_used: bool     # a query that adds name matches into one number is sent back only once
    profit_switched: bool     # a profit % between two periods is sent back once for the revenue growth
    chart_retry_used: bool    # a chart question of SS Manufacturing data that got NO_SQL is sent back once
    values_checked: bool      # a query that found no data has its filter values checked once
    year_check_used: bool     # a quarter / month number grouped over all years is sent back once
    today_check_used: bool    # a period not over yet, counted past today, is sent back once
    forecast_check_used: bool  # forecast months added into one number (a "2027 total") are sent back once
    forecast_level_check_used: bool  # product forecast rows read for a question that names no product: sent back once
                                     # (before running, or after 0 rows for a TOTAL forecast month)
    forecast_levels: dict     # agent.forecast_levels(), read once per question when one of those checks needs it
    one_row_retry_used: bool  # a line chart / trend question with only 1 row is sent back once
    entity_check_used: bool   # a ranking of customers / products ... whose rows name none of them is sent back once
    first_answer: dict        # the answer kept while one of those two retries runs ({} = none): its try, SQL, data,
                              # notes, chart kind, and for the ranking check the thing ranked ("entity")
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
    japan" after two Sep 2026 questions -> no data).
    18-Nov: a question about an earlier answer's own result ("forecast_count what it mean this coloums") also gets
    that answer's query and columns (lc.memory.previous_query) - here, and later in the SQL and general requests,
    also when the rewrite says NEW. Any other question gets nothing more.
    18-Nov: a follow-up word that is part of a name in an earlier answer's rows ("why is aurora on top?" after a list
    led by Aurora Fluid Power Limited) gets a fact line with that full name (lc.memory.previous_names) - here and in
    the SQL request. No such word: nothing is added and no query runs."""
    result = state["result"]
    found = previous_query(state["chat"], result.text, state.get("history"))
    names = previous_names(state["chat"], result.text, result)
    understood = agent.rewrite_follow_up(
        result, state["memory"],
        previous=(agent.PREVIOUS_QUERY_REWRITE.format(query=previous_query_text(found)) if found else "")
        + (agent.FOLLOW_UP_NAMES_REWRITE.format(facts=names) if names else ""))
    if understood is None:
        return {"memory": [], "previous_query": found or {}, "previous_names": names}
    result.understood_as = understood
    found = found or previous_query(state["chat"], understood, state.get("history"))  # "Why did you add ... ?"
    return {"asked": result.understood_as or result.text, "previous_query": found or {}, "previous_names": names}


def route(state):
    """Data, documents, both or general (agent.route_question), with the PDF pieces to answer from ([] for the
    data and general)."""
    chosen, hits = agent.route_question(state["result"], state["asked"])
    return {"route": chosen, "pdf_hits": hits}


def general_answer(state):
    """17-Nov, like ChatGPT: a message not about SS Manufacturing's data or documents (the router said 'general',
    or the SQL writer replied GENERAL) is answered by the AI itself, with the chat's earlier questions and answers
    and the user's memories (agent.answer_general) - status 'general', no SQL, no rows. A message about an earlier
    answer's own result also gets that answer's query and columns (agent.PREVIOUS_QUERY_GENERAL)."""
    found = state.get("previous_query")
    agent.answer_general(state["result"], state.get("chat") or [], state["memories"],
                         on_token=_token_sender(state),
                         previous=agent.PREVIOUS_QUERY_GENERAL.format(query=previous_query_text(found)) if found else "")
    return {}


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
    the question before it, so "and for export?" still finds the sales pieces. An ML Insights chat searches a
    few more notes, so the best ML example and the ML rules are among the TOP_K sent (agent.ml_notes)."""
    result = state["result"]
    search_text = state["asked"]
    if state["memory"] and not result.understood_as:
        search_text = f"{latest_question(state['memory'])} {result.text}"
    store.last_search.embed_secs = None
    started = time.perf_counter()
    try:
        if agent.is_ml_mode(result):
            hits = agent.ml_notes(agent.search(search_text, top_k=agent.ML_SEARCH_K))
        else:
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
    """The tables and columns the SQL call shows, and the values of its prompt template. An ML Insights chat
    always shows the ml_ tables and its question gets agent.ML_MODE_NOTE (the Assistant's: neither). A question about
    an earlier answer's own result gets agent.PREVIOUS_QUERY_SQL: a column that query made is explained (GENERAL),
    never NO_DATA. Its SQL is written there only when 'Earlier in this chat' does not list it (the rewrite said NEW)."""
    result, hits = state["result"], state["hits"]
    ml_mode = agent.is_ml_mode(result)
    found = state.get("previous_query")
    previous = (agent.PREVIOUS_QUERY_SQL.format(query=previous_query_text(found, shown=bool(state["memory"])))
                if found else "")
    if state.get("previous_names"):  # "aurora" = Aurora Fluid Power Limited (lc.memory.previous_names)
        previous += agent.FOLLOW_UP_NAMES_SQL.format(facts=state["previous_names"])
    with agent._timed(result, "schema"):
        allowed = warehouse.allowed_tables()
        schema, full_schema_shown = agent.schema_for_prompt(state["asked"], hits, ml_mode)
    sql_values = dict(
        schema=schema,
        count=len(hits),
        documents="\n\n---\n\n".join(agent.compact_notes(h["text"]) for h in hits),
        today=timezone.localdate().strftime("%d-%b-%Y (%A)"),
        preferences=agent.preferences(state["memories"], "sql"),
        earlier=sql_earlier(state["memory"]),
        question=result.text + (f"\n(Written out in full: {result.understood_as})" if result.understood_as else "")
        + (agent.SQL_BOTH_NOTE if state["route"] == "both" else "")
        + (agent.ML_MODE_NOTE if ml_mode else "") + previous,
    )
    backup_values = {}
    if ml_mode:  # 18-Nov (question 124): the backup model gets one ML note and only the ml_ tables the question picks
        note = agent.backup_ml_hits(hits, state["asked"])
        with agent._timed(result, "schema"):
            backup_values = dict(documents="\n\n---\n\n".join(agent.compact_notes(h["text"]) for h in note),
                                 count=len(note), schema=agent.backup_ml_schema(state["asked"], note),
                                 smallest_schema=agent.backup_ml_schema(state["asked"], note, smallest=True))
    return {"allowed": allowed, "full_schema_shown": full_schema_shown, "sql_values": sql_values,
            "backup_values": backup_values}


def write_sql(state):
    """The AI writes the SQL: LangChain's SQL chain with the prompt values and the failed tries so far.
    NO_SQL -> refused (a chart question of SS Manufacturing data: first sent back once); GENERAL -> general_answer;
    NO_DATA -> nodata (or, once, the revenue growth for a profit % between two periods; a NO_DATA about how the
    app's own ML works -> general_answer, agent.no_data_about_app_ml);
    a reply without SQL -> a retry."""
    result, attempt = state["result"], state["attempt"] + 1
    result.tries = attempt
    request = LcRequest("sql", state["sql_values"], retries=list(state["retries"]),
                        backup=state.get("backup_values") or {})
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
    if kind in ("remember", "forget"):
        # 12-Nov, like ChatGPT's memory: the AI understood a memory request in any words and named the fact;
        # our own code saves or removes it, with the same limits as "Remember that ..." (user_memory.py)
        update["sql"] = ""
        user = state.get("user")
        if user is None:  # nobody to remember it for (the eval, a tool)
            result.status, result.answer = "refused", agent.REFUSAL_ANSWER
        elif kind == "remember":
            outcome, result.answer, result.memory = user_memory.remember(user, sql)
            result.status = "error" if outcome == "refused" else "memory"
        else:
            outcome, result.answer = user_memory.forget(user, sql)
            result.status = "error" if outcome == "refused" else "memory"
        return update
    # 17-Nov: the chart the AI said was asked for ("CHART: bar"). A try without a CHART line keeps the one of an
    # earlier try of this question; agent.ask_events clears it when no rows came back
    chart_kind = agent.chart_kind_line(reply)
    if chart_kind:
        result.chart_kind = chart_kind
    # 17-Nov: what the AI said the question ranks or lists ("ASKS_FOR: customers") and how many periods it asks
    # for ("PERIODS: 6") - read by run_sql's checks before their word rules (portal/ai_hints.py). Like CHART, a
    # try without such a line keeps the one of an earlier try
    hint_asks_for, hint_periods = ai_hints.asks_for(reply), ai_hints.periods(reply)
    if hint_asks_for:
        update["asks_for"] = hint_asks_for
    if hint_periods:
        update["periods"] = hint_periods
    if kind in ("no_sql", "general"):  # a request to change data / to bend the rules (NO_SQL), or off-topic (GENERAL)
        if (not state["chart_retry_used"] and attempt < agent.MAX_TRIES
                and agent.chart_request(f"{result.text} {result.understood_as}")):
            # 05-Nov: "Create a line chart of last month's sales" was read as a CREATE: sent back once
            update.update(chart_retry_used=True, schema_not_needed=True, problem=agent.CHART_NOT_A_CHANGE_PROBLEM)
            return update
        if kind == "no_sql" or state["route"] == "both":
            # GENERAL goes on to general_answer; a 'both' question still answers its documents part (as before)
            result.status, result.answer = "refused", agent.REFUSAL_ANSWER
        return update
    no_data, try_question, missing = agent.data_notes(reply)
    if missing and not agent.missing_was_asked(missing, f"{result.text} {result.understood_as}"):
        log.info("MISSING line dropped - the question did not ask for it: %s", missing)
        missing = ""
    update["missing"] = missing
    if (kind in ("no_data", "empty") and state["route"] != "both"
            and agent.no_data_about_app_ml(f"{result.text} {result.understood_as or ''}",
                                           no_data if kind == "no_data" else missing)):
        # 18-Nov safety net: "which model you used for forecast and how accurate it is?" got NO_DATA "How the forecast
        # model works ... is not in the SS Manufacturing data". How the app's own ML works is not missing data: the
        # question goes to the general answer with the ML facts, like a GENERAL reply (one more AI call, counted)
        log.info("NO_DATA about the app's own ML - answered as a general question: %s", no_data or missing)
        update.update(kind="general", missing="")
        return update
    if kind == "no_data":  # an SS Manufacturing business question, but nothing in it is in ss_gold (e.g. profit)
        if (try_question and not state["profit_switched"] and attempt < agent.MAX_TRIES
                and agent.profit_comparison(state["asked"])):
            # the model said "not available" although SS Manufacturing wants the revenue growth + a note:
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
    one number, forecast months added into one number ("2027 total" = Jan 2027 only), a period not over yet
    (FY 2026-27 on 03-Nov-2026) without "up to today". The last try runs as it is."""
    result = state["result"]
    with agent._timed(result, "check"):
        try:
            cleaned = agent.fy_period_dates(agent.order_months_by_date(agent.check_sql(state["sql"], state["allowed"])))
        except GuardError as exc:
            return {"problem": f"the SQL guard refused the query: {exc}"}
        # 16-Nov: a period list of LIMIT n calendar DAYS counts the sales n times - never run, also not on the last
        # try (then the "could not answer" message is better than a number n times too big)
        days = agent.calendar_limit_periods(cleaned)
        if days:
            return {"problem": agent.CALENDAR_LIMIT_PROBLEM.format(column=days[0], limit=days[1]),
                    "schema_not_needed": True}
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
        if not state["forecast_check_used"] and agent.summed_forecast_months(cleaned):
            # 18-Nov: "what is my 2027 total sales" got SUM(forecast_inr) of the 2027 rows (only Jan 2027) as the year
            return {"forecast_check_used": True, "schema_not_needed": True, "problem": agent.FORECAST_SUM_PROBLEM}
        if not state.get("forecast_level_check_used"):
            # 18-Nov 17:07: "sales forecast for August 2027?" read the level 'PRODUCT' rows (only Nov 2026 - Jan 2027)
            problem, levels = agent.forecast_level_problem(f"{result.text} {result.understood_as or ''}", cleaned,
                                                           state.get("forecast_levels"))
            if problem:
                return {"forecast_level_check_used": True, "schema_not_needed": True, "problem": problem,
                        "forecast_levels": levels}
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
    question = f"{result.text} {result.understood_as}"
    first = {"attempt": state["attempt"], "sql": cleaned, "data": data, "missing": state["missing"],
             "notes": list(result.notes), "chart_kind": result.chart_kind}
    if (not state["one_row_retry_used"] and not state["first_answer"] and state["attempt"] < agent.MAX_TRIES
            and len(data["rows"]) == 1
            and (ai_hints.several_periods_chart(question, state.get("periods"), result.chart_kind)
                 or several_periods_chart_request(question))):
        # a line chart needs one row per period: sent back once; the 1-row answer is kept in case that try
        # gives nothing better (keep_first_answer) - an answered question never becomes an error.
        # 17-Nov: the AI's "PERIODS: 6" + a chart wish first (typos: "bar chat of the lst six mnths"), the words after
        return {**update, "one_row_retry_used": True, "schema_not_needed": True,
                "problem": ONE_ROW_LINE_CHART_PROBLEM, "first_answer": first}
    if (not state["entity_check_used"] and not state["first_answer"] and state["attempt"] < agent.MAX_TRIES
            and not agent.found_nothing(data["rows"])):
        # 16-Nov: "Top customers of Coolant pump ..." got the product's total over all its customers, with no
        # customer column, and the answer called it "the top customer". Sent back once, the first answer kept
        # in case that try gives nothing better (keep_first_answer).
        # 17-Nov: the AI's "ASKS_FOR: customers" first (typos: "top clints"), the word rules after
        missing = ai_hints.missing_entity(question, data["columns"], state.get("asks_for", ""))
        if missing:
            return {**update, "entity_check_used": True,
                    "problem": agent.entity_problem(missing[0], missing[1], data["columns"]),
                    "first_answer": {**first, "entity": missing[0]}}
    if (not state.get("forecast_level_check_used") and not state["first_answer"]
            and state["attempt"] < agent.MAX_TRIES and agent.found_nothing(data["rows"])):
        # 18-Nov 17:07: 0 forecast rows for Aug 2027, while its TOTAL row is there - sent back once; the 0-row
        # answer is kept in case that try finds no rows either (keep_first_answer)
        problem, levels = agent.forecast_level_problem(question, cleaned, state.get("forecast_levels"), data["rows"])
        if problem:
            return {**update, "forecast_level_check_used": True, "schema_not_needed": True, "problem": problem,
                    "forecast_levels": levels, "first_answer": {**first, "forecast": True}}
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
    """The line chart retry or the ranking retry gave no better rows (again 1 row / again no column of the thing
    ranked, no rows, NO_SQL / NO_DATA, or a query that failed): the first answer is kept and explained as it was.
    Its tries and tokens still count both SQL calls."""
    result, first = state["result"], state["first_answer"]
    log.info("%s retry gave no better rows - the first answer is kept",
             "Ranking" if first.get("entity") else "Forecast level" if first.get("forecast") else "Line chart")
    result.answer, result.notes = "", list(first["notes"])
    result.chart_kind = first.get("chart_kind", "")  # the chart of the try whose rows are kept
    _keep_rows(result, first["sql"], first["data"], first["missing"])
    return {"problem": ""}


def retry(state):
    """A failed try goes back to the AI: its reply + what was wrong (RETRY_PROMPT). A question whose first
    try saw only some tables now gets every table - the columns of the tables it did not see (the others are
    in the first request above it) - unless the problem was about values or wording."""
    log.info("Manufacturing Intelligence try %s failed: %s", state["attempt"], state["problem"])
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
    log.info("Manufacturing Intelligence try %s failed: %s", state["attempt"], state["problem"])
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
            result.answer += f" Also, this is not in the SS Manufacturing data: {state['missing'].rstrip('.')}."
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
        result.answer = agent.explain(result, state["memories"], both, on_token=_token_sender(state),
                                      on_rewrite=_rewrite_sender(state)) or agent.ROWS_ONLY_ANSWER
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
    "check_names": _LABELS["check"], "explain": _LABELS["answer_ai"], "general_answer": _LABELS["general"],
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


def _rewrite_sender(state):
    """18-Nov: the on_rewrite of the answer step (None when not streamed). The app's answer check (answer_verify.py)
    found the streamed answer wrong and the AI rewrites it once: the page is told to clear the first text
    ({"type": "reset"}) and shows the rewrite as a step; the rewritten answer then streams in its place."""
    if not state.get("streaming"):
        return None
    writer = get_stream_writer()

    def rewrite():
        writer({"type": "step", "label": _LABELS["answer_fix"]})
        writer({"type": "reset"})
    return rewrite


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
    """The documents path, the general answer, or the data path - also for 'both' (its documents part is in the
    explain step)."""
    if state["route"] in ("documents", "general"):
        return state["route"]
    return "data / both"


def retry_or_fail(state):
    """Another try while tries are left, else the "3 tries" answer."""
    return "retry" if state["attempt"] < agent.MAX_TRIES else "failed"


def _both(label, state):
    """A 'both' question still answers its documents part when the data part ends without rows."""
    return f"{label} (both)" if state["route"] == "both" else label


def _first_kept(state):
    """The line chart or ranking retry ran (a try after the first answer): anything but better rows of its own
    keeps the first answer (it is never sent back again)."""
    first = state["first_answer"]
    return bool(first) and state["attempt"] > first["attempt"]


def _no_better_rows(state):
    """The retry's rows are no better than the first answer: for the ranking check, no rows or still no column
    of the thing ranked; for the forecast level check, again no rows; for the line chart, fewer than 2 rows."""
    result, entity = state["result"], state["first_answer"].get("entity")
    if state["first_answer"].get("forecast"):
        return agent.found_nothing(result.rows)
    if entity:
        return agent.found_nothing(result.rows) or not agent.shows_entity(entity, result.columns)
    return len(result.rows) < 2


def after_write_sql(state):
    if state["kind"] in ("remember", "forget"):  # a memory request: saved or removed, nothing to run or to add
        return "refused / nodata"
    if _first_kept(state) and (state["problem"] or state["kind"] in ("no_sql", "no_data", "general")):
        return "keep the first answer"
    if state["problem"]:  # no SQL in the reply, or the profit-growth switch
        return retry_or_fail(state)
    if state["kind"] == "general" and state["route"] != "both":
        return "general"
    return _both("refused / nodata", state) if state["kind"] in ("no_sql", "no_data", "general") else "check"


def after_check_sql(state):
    if state["problem"]:
        return "keep the first answer" if _first_kept(state) else retry_or_fail(state)
    return "run"


def after_run_sql(state):
    if _first_kept(state) and (state["problem"] or _no_better_rows(state)):
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
                 check_sql, run_sql, retry, failed, keep_first_answer, check_names, explain, documents_part,
                 general_answer):
        graph.add_node(node.__name__, _announced(node))
    graph.add_edge(START, "load_memories")
    graph.add_conditional_edges("load_memories", chat_or_not, {"in a chat": "rewrite", "no chat": "route"})
    graph.add_edge("rewrite", "route")
    graph.add_conditional_edges("route", documents_or_data, {"documents": "answer_from_documents",
                                                             "general": "general_answer",
                                                             "data / both": "search_notes"})
    graph.add_edge("answer_from_documents", END)
    graph.add_edge("general_answer", END)
    graph.add_edge("search_notes", "pick_schema")
    graph.add_edge("pick_schema", "write_sql")
    graph.add_conditional_edges("write_sql", after_write_sql, {"refused / nodata": END, "retry": "retry",
                                                               "refused / nodata (both)": "documents_part",
                                                               "failed": "failed", "check": "check_sql",
                                                               "general": "general_answer",
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
        "result": result, "user": user, "memories": [], "memory": messages_of(context), "chat": messages_of(context),
        "previous_query": {}, "previous_names": "", "history": context if hasattr(context, "older_answers") else None,
        "asked": result.text,
        "route": "data", "pdf_hits": [], "hits": [],
        "retries": [], "attempt": 0, "problem": "", "missing": "", "asks_for": "", "periods": None,
        "last_sql": "", "schema_note": "",
        "not_found": "", "schema_not_needed": False, "name_check_used": False, "profit_switched": False,
        "chart_retry_used": False, "one_row_retry_used": False, "entity_check_used": False, "first_answer": {},
        "values_checked": False, "year_check_used": False, "today_check_used": False, "forecast_check_used": False,
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
