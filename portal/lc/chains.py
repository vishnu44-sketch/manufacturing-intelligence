"""LangChain step C: the chains (LCEL - the | pipe means "then").

    sql_chain(llm)      = SQL_PROMPT     | llm    question + notes + schema -> the AI's reply with the SQL
    answer_chain(llm)   = EXPLAIN_PROMPT | llm    question + SQL + rows     -> the short answer
    rewrite_chain(llm)  = REWRITE_PROMPT | llm    a follow-up + the earlier questions -> the full question
    route_chain(llm)    = ROUTE_PROMPT   | llm    question + closest PDF pieces -> data or documents
    docs_chain(llm)     = DOCS_PROMPT    | llm    question + closest PDF pieces -> the short answer

Each chain stops at the AI's reply message (AIMessage), not at plain text: the message also carries
the tokens Groq counted and whether the reply was cut off - the app needs both (History, usage box).
reply_info() reads them.

One chain = one AI call. LCEL has no loops: the steps around the calls (the router, the SQL guard ->
checks -> read-only MySQL -> on a problem ask again) are a LangGraph graph (graph.py).
"""
from .prompts import DOCS_PROMPT, EXPLAIN_PROMPT, REWRITE_PROMPT, ROUTE_PROMPT, SQL_PROMPT


def sql_chain(llm):
    return SQL_PROMPT | llm


def answer_chain(llm):
    return EXPLAIN_PROMPT | llm


def rewrite_chain(llm):
    return REWRITE_PROMPT | llm


def route_chain(llm):
    return ROUTE_PROMPT | llm


def docs_chain(llm):
    return DOCS_PROMPT | llm


def reply_info(message):
    """(reply text, total tokens or None, True when the reply stopped at max_tokens) of one AIMessage -
    what calls.chat() gives back to the agent for one Groq call."""
    usage = getattr(message, "usage_metadata", None) or {}
    tokens = usage.get("total_tokens")
    finish = (getattr(message, "response_metadata", None) or {}).get("finish_reason")
    text = message.content if isinstance(message.content, str) else str(message.content)
    return text.strip(), (tokens if isinstance(tokens, int) and tokens >= 0 else None), finish == "length"
