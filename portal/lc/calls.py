"""LangChain step D: one AI call of the app through a LangChain chain, with the app's safety rules.

agent.py builds an LcRequest (which chain + the values of its prompt template) for every AI call and
agent._ask_ai() hands it to chat() here. Around the call agent._ask_ai() keeps: the main model first,
the backup model after a daily limit, the token count and the time per step.

The rules for the errors LangChain's ChatOpenAI raises (openai.*) - Groq and Gemini alike (18-Nov: the model
chain, agent._ask_models, moves on to the next model after each of these errors):
- per-minute limit (429)        -> the main Groq model waits as Groq asks and tries again (at most RATE_LIMIT_RETRIES
                                   times), then ModelBusy; any other model: ModelBusy at once
- daily limit (429 "per day", Gemini's "...PerDay..." quota) -> DailyLimitReached
- request too large (413, or a context-length error) -> RequestTooLarge (a smaller request may still go)
- network error                 -> try once more after 3 s, then ModelDown ("could not be reached")
- a timeout / server error (5xx, Gemini's 503 "high demand") -> ModelDown at once
- any other error (a wrong key, an unknown model, a bad request) -> ModelFailed ("returned an error")
A streamed reply (the final answer on the streamed Ask page) follows the same rules until its first piece is
shown; an error after that is StreamBroken (the answer step then shows the rows without a summary).
"""
import logging
import re
from dataclasses import dataclass, field

import openai

from ..rag import agent
from . import chains, llm

log = logging.getLogger(__name__)

CHAINS = {"sql": chains.sql_chain, "rewrite": chains.rewrite_chain, "answer": chains.answer_chain,
          "route": chains.route_chain, "docs": chains.docs_chain, "general": chains.general_chain}


@dataclass
class LcRequest:
    """One AI call: which chain, and the values its prompt template needs. For 'sql', retries = the earlier
    tries of this question as LangChain messages - the AI's reply (AIMessage), then what was wrong with it
    (HumanMessage, RETRY_PROMPT); the graph's retry step (graph.py) adds them after every failed try."""
    chain: str                                   # 'sql' | 'rewrite' | 'answer' | 'route' | 'docs' | 'general'
    values: dict
    retries: list = field(default_factory=list)
    # an ML Insights SQL request: the backup model's own documents, count, schema and smallest_schema
    # (graph.pick_schema; for_backup swaps them in); the backup's answer request: {"smallest": a function giving its
    # smallest values} (agent.explain). {} = any other request
    backup: dict = field(default_factory=dict)

    def inputs(self):
        """The template's inputs: the values, plus the earlier tries for the SQL chain (and for an answer the app's
        answer check sent back once: its first answer + the correction, answer_verify.py)."""
        if self.chain != "sql" and not self.retries:
            return dict(self.values)
        return {**self.values, "retries": list(self.retries)}


BACKUP_SQL_NOTES = 2           # notes pieces the backup's SQL request keeps (the main model gets agent.TOP_K = 5)
NOTES_BREAK = "\n\n---\n\n"    # how graph.pick_schema joins the notes pieces


def for_backup(request, smallest=False):
    """The request cut to fit the backup model's smaller free tier (tokens a minute).
    18-Nov (question 118): the SQL request is ~6,400 tokens (the rules ~2,950, the schema, five notes pieces) and
    the backup adds 1,000 for its reply - more than the backup may take in a minute, so Groq refused it at once and
    the question ended with "returned an error" although the backup had all its daily tokens left.
    Only the SQL request is that big: the backup gets the closest BACKUP_SQL_NOTES notes pieces and only the last
    earlier try; smallest=True (after Groq still said too large) keeps one piece and leaves out the chat's earlier
    questions too. Other requests are given back as they are (the answer call already sends the backup fewer rows).
    18-Nov (question 124): an ML Insights request (request.backup) gets its own cut instead - one ML note and only
    the ml_ tables the question picks (agent.backup_ml_hits / backup_ml_schema); smallest: the picked tables only.
    18-Nov: an answer request may bring its smallest values too (request.backup["smallest"], a function - agent.explain:
    fewer rows and only the app's facts); smallest=True sends those."""
    if request.chain != "sql":
        smaller = request.backup.get("smallest") if smallest else None
        return LcRequest(request.chain, smaller(), retries=list(request.retries)) if smaller else request
    values = dict(request.values)
    if request.backup:
        values.update(documents=request.backup["documents"], count=request.backup["count"],
                      schema=request.backup["smallest_schema" if smallest else "schema"])
    else:
        pieces = [piece for piece in str(values.get("documents") or "").split(NOTES_BREAK) if piece.strip()]
        keep = 1 if smallest else BACKUP_SQL_NOTES
        if len(pieces) > keep:
            values["documents"], values["count"] = NOTES_BREAK.join(pieces[:keep]), keep
    if smallest:
        values["earlier"] = ""
    return LcRequest(request.chain, values, retries=list(request.retries[-2:]))  # the last try: reply + problem


# a context-length error of a request that is too big for the model (Gemini: "The input token count (...) exceeds
# the maximum number of tokens allowed"; OpenAI-style: "context_length_exceeded")
TOO_LONG = re.compile(r"context.length|context window|maximum context|exceeds the maximum number of tokens|"
                      r"input token count", re.I)


def chat(request, max_tokens, effort, model=None, on_token=None):
    """One AI call through the request's chain -> (reply text, total tokens or None, True when the reply
    stopped at max_tokens). The main Groq model waits and retries on a per-minute rate limit (429); every other
    error raises (the rules above) and agent._ask_models moves on to the next model of the chain.
    on_token = the reply is streamed (the streamed Ask page): each piece of text goes to on_token while it is
    written. Until the first piece the rules above apply as they are; a failure after it raises StreamBroken."""
    model = model or agent.model_name()
    waits = model == agent.model_name()  # only the main Groq model waits for a per-minute limit (as before)
    attempt = 0
    while True:
        attempt += 1
        chain = CHAINS[request.chain](llm.make_llm(model, max_tokens, effort))  # no key -> AIUnavailable
        try:
            message = chain.invoke(request.inputs()) if on_token is None else _streamed(chain, request, on_token)
            text, tokens, cut_off = chains.reply_info(message)
            _log_usage(request.chain, message, model)
            return text, tokens, cut_off
        except openai.RateLimitError as exc:
            if agent.DAILY_LIMIT.search(str(exc)):  # e.g. "tokens per day (TPD): Limit 200000, Used ..."
                log.warning("Daily limit reached for %s", model)
                raise agent.DailyLimitReached(model) from None
            if not waits:
                log.warning("Per-minute limit of %s - the next model is tried", model)
                raise agent.ModelBusy() from None
            wait = agent._retry_after(exc)
            if attempt > agent.RATE_LIMIT_RETRIES or wait > agent.MAX_WAIT_SECS:
                log.warning("Groq rate limit: giving up (wait asked: %.0f s)", wait)
                raise agent.ModelBusy() from None
            log.warning("Groq rate limit: waiting %.1f s (retry %s)", wait, attempt)
            agent._wait(wait)
        except openai.APITimeoutError:  # a hanging call: the next model, not another wait
            log.warning("%s did not answer in time", model)
            raise agent.ModelDown() from None
        except openai.APIConnectionError:  # network
            if attempt >= 2:
                raise agent.ModelDown() from None
            agent._wait(3)
        except openai.InternalServerError as exc:  # 500 / 502 / 503 / 504: busy or down at the provider
            log.warning("%s is busy or down (%s)", model, exc.status_code)
            raise agent.ModelDown(busy=exc.status_code == 503) from None
        except openai.APIStatusError as exc:  # 400 / 401 / 404 / 413 ...: retrying the same will not help
            if exc.status_code == 413 or TOO_LONG.search(str(exc)):  # a smaller request may go
                log.warning("Request too large for %s (%s)", model, exc.status_code)
                raise agent.RequestTooLarge() from None
            log.warning("%s error %s: %s", model, exc.status_code, str(exc)[:300])
            raise agent.ModelFailed() from None
        except openai.OpenAIError as exc:
            log.warning("%s error: %s", model, str(exc)[:300])
            raise agent.ModelFailed() from None


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


def _log_usage(chain, message, model=""):
    """Log the tokens of one call (the free tiers have daily limits)."""
    usage = getattr(message, "usage_metadata", None) or {}
    details = usage.get("output_token_details") or {}
    log.info("AI tokens (%s, %s): prompt %s, completion %s (reasoning %s), total %s", chain, model,
             usage.get("input_tokens", "?"), usage.get("output_tokens", "?"), details.get("reasoning", "?"),
             usage.get("total_tokens", "?"))
