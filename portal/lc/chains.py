"""LangChain step C: the chains (LCEL - the | pipe means "then").

    sql_chain(llm)      = SQL_PROMPT     | llm    question + notes + schema -> the AI's reply with the SQL
    answer_chain(llm)   = EXPLAIN_PROMPT | llm    question + SQL + rows     -> the short answer
    rewrite_chain(llm)  = REWRITE_PROMPT | llm    a follow-up               -> the full question

Each chain stops at the AI's reply message (AIMessage), not at plain text: the message also carries
the tokens Groq counted and whether the reply was cut off - the app needs both (History, usage box).
reply_info() reads them; as_text(chain) adds StrOutputParser for when only the text is needed.

One chain = one AI call. The loop around the SQL call (SQL guard -> checks -> read-only MySQL -> on a
problem ask again) stays our own code in agent.py: LCEL has no loops (LangGraph would be the next step).
"""
from langchain_core.output_parsers import StrOutputParser

from .prompts import EXPLAIN_PROMPT, REWRITE_PROMPT, SQL_PROMPT


def sql_chain(llm):
    return SQL_PROMPT | llm


def answer_chain(llm):
    return EXPLAIN_PROMPT | llm


def rewrite_chain(llm):
    return REWRITE_PROMPT | llm


def as_text(chain):
    """The same chain with | StrOutputParser() at the end: it returns only the reply text."""
    return chain | StrOutputParser()


def reply_info(message):
    """(reply text, total tokens or None, True when the reply stopped at max_tokens) of one AIMessage -
    what the classic agent._chat() returns for one Groq call."""
    usage = getattr(message, "usage_metadata", None) or {}
    tokens = usage.get("total_tokens")
    finish = (getattr(message, "response_metadata", None) or {}).get("finish_reason")
    text = message.content if isinstance(message.content, str) else str(message.content)
    return text.strip(), (tokens if isinstance(tokens, int) and tokens >= 0 else None), finish == "length"
