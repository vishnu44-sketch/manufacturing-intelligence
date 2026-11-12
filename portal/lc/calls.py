"""LangChain step D: one AI call of the app through a LangChain chain, with the app's safety rules.

agent.py builds an LcRequest (which chain + the values of its prompt template) for every AI call and
agent._ask_ai() hands it to chat() here. Around the call agent._ask_ai() keeps: the main model first,
the backup model after a daily limit, the token count and the time per step.

The rules for the errors LangChain's ChatOpenAI raises (openai.*):
- per-minute limit (429)        -> wait as Groq asks and try again (at most RATE_LIMIT_RETRIES times)
- daily limit (429 "per day")   -> DailyLimitReached (agent._ask_ai moves to the backup model)
- request too large (413)       -> RequestTooLarge (agent sends the retry again without the full schema)
- network / Groq server error   -> try once more after 3 s, then "could not be reached"
- any other error               -> "returned an error"
A streamed reply (the final answer on the streamed Ask page) follows the same rules until its first piece is
shown; an error after that is StreamBroken (the answer step then shows the rows without a summary).
"""
import logging
from dataclasses import dataclass, field

import openai

from ..rag import agent
from . import chains, llm

log = logging.getLogger(__name__)

CHAINS = {"sql": chains.sql_chain, "rewrite": chains.rewrite_chain, "answer": chains.answer_chain,
          "route": chains.route_chain, "docs": chains.docs_chain}


@dataclass
class LcRequest:
    """One AI call: which chain, and the values its prompt template needs. For 'sql', retries = the earlier
    tries of this question as LangChain messages - the AI's reply (AIMessage), then what was wrong with it
    (HumanMessage, RETRY_PROMPT); the graph's retry step (graph.py) adds them after every failed try."""
    chain: str                                   # 'sql' | 'rewrite' | 'answer' | 'route' | 'docs'
    values: dict
    retries: list = field(default_factory=list)

    def inputs(self):
        """The template's inputs: the values, plus the earlier tries for the SQL chain."""
        if self.chain != "sql":
            return dict(self.values)
        return {**self.values, "retries": list(self.retries)}


def chat(request, max_tokens, effort, model=None, on_token=None):
    """One AI call through the request's chain -> (reply text, total tokens or None, True when the reply
    stopped at max_tokens). Waits and retries on a per-minute rate limit (429); raises DailyLimitReached on
    a daily limit, and AIUnavailable with a friendly message when Groq cannot answer (also: no API key).
    on_token = the reply is streamed (the streamed Ask page): each piece of text goes to on_token while it is
    written. Until the first piece the rules above apply as they are; a failure after it raises StreamBroken."""
    model = model or agent.model_name()
    attempt = 0
    while True:
        attempt += 1
        chain = CHAINS[request.chain](llm.make_llm(model, max_tokens, effort))  # no key -> AIUnavailable
        try:
            message = chain.invoke(request.inputs()) if on_token is None else _streamed(chain, request, on_token)
            text, tokens, cut_off = chains.reply_info(message)
            _log_usage(request.chain, message)
            return text, tokens, cut_off
        except openai.RateLimitError as exc:
            if agent.DAILY_LIMIT.search(str(exc)):  # e.g. "tokens per day (TPD): Limit 200000, Used ..."
                log.warning("Groq daily limit reached for %s", model)
                raise agent.DailyLimitReached(model) from None
            wait = agent._retry_after(exc)
            if attempt > agent.RATE_LIMIT_RETRIES or wait > agent.MAX_WAIT_SECS:
                log.warning("Groq rate limit: giving up (wait asked: %.0f s)", wait)
                raise agent.AIUnavailable(agent.AI_BUSY) from None
            log.warning("Groq rate limit: waiting %.1f s (retry %s)", wait, attempt)
            agent._wait(wait)
        except (openai.APIConnectionError, openai.InternalServerError):  # network / Groq side
            if attempt >= 2:
                raise agent.AIUnavailable(agent.AI_DOWN) from None
            agent._wait(3)
        except openai.APIStatusError as exc:  # 400 / 401 / 413 ...: retrying will not help
            log.error("Groq error %s: %s", exc.status_code, str(exc)[:300])
            if exc.status_code == 413:  # more than the tokens a minute allows: a smaller request may go
                raise agent.RequestTooLarge() from None
            raise agent.AIUnavailable(agent.AI_ERROR) from None
        except openai.OpenAIError as exc:
            log.error("Groq error: %s", str(exc)[:300])
            raise agent.AIUnavailable(agent.AI_ERROR) from None


def _streamed(chain, request, on_token):
    """The chain's reply streamed piece by piece (ChatOpenAI with stream_usage, so the last pieces still carry
    Groq's token count of the whole reply) -> the whole reply as one message, with that count once. Each piece
    of text goes to on_token as it arrives.
    An error before the first piece is raised as it is (chat()'s rules: wait, retry, the backup model); after it
    the user has seen part of the reply, so it becomes StreamBroken."""
    message, shown, usage = None, False, None
    try:
        for piece in chain.stream(request.inputs()):
            message = piece if message is None else message + piece
            # the count of the whole reply: 03-Nov, Groq sent it twice at the end and adding the pieces up counted
            # the answer's tokens double - the last count is the one kept
            usage = getattr(piece, "usage_metadata", None) or usage
            text = piece.content if isinstance(piece.content, str) else ""
            if text:
                shown = True
                on_token(text)
    except Exception:
        if shown:
            log.warning("Groq stream broke after the first piece of the reply (%s)", request.chain)
            raise agent.StreamBroken() from None
        raise
    if message is None:  # an empty stream: no reply at all
        raise agent.AIUnavailable(agent.AI_ERROR)
    message.usage_metadata = usage
    return message


def _log_usage(chain, message):
    """Log the Groq tokens of one call (the free tier has a daily token limit)."""
    usage = getattr(message, "usage_metadata", None) or {}
    details = usage.get("output_token_details") or {}
    log.info("Groq tokens (%s): prompt %s, completion %s (reasoning %s), total %s", chain,
             usage.get("input_tokens", "?"), usage.get("output_tokens", "?"), details.get("reasoning", "?"),
             usage.get("total_tokens", "?"))
