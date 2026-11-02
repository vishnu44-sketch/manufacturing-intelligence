"""LangChain step D: one AI call of the app through a LangChain chain, with the classic safety rules.

agent.py builds an LcRequest instead of a message list when USE_LANGCHAIN=on; agent._chat() hands it
to chat() here. Everything around the call stays the classic code (agent._ask_ai): the main model
first, the backup model after a daily limit, the token count, the time per step.

The rules of agent._chat(), for the errors LangChain's ChatOpenAI raises (openai.*, not groq.*):
- per-minute limit (429)        -> wait as Groq asks and try again (at most RATE_LIMIT_RETRIES times)
- daily limit (429 "per day")   -> DailyLimitReached (agent._ask_ai moves to the backup model)
- request too large (413)       -> RequestTooLarge (agent sends the retry again without the full schema)
- network / Groq server error   -> try once more after 3 s, then "could not be reached"
- any other error               -> "returned an error"
"""
import logging
from dataclasses import dataclass, field

import openai
from langchain_core.messages import AIMessage, HumanMessage

from ..rag import agent
from . import chains, llm

log = logging.getLogger(__name__)

CHAINS = {"sql": chains.sql_chain, "rewrite": chains.rewrite_chain, "answer": chains.answer_chain}


@dataclass
class LcRequest:
    """One AI call for the LangChain version: which chain, and the values its prompt template needs.
    For 'sql', messages = the classic message list of this question (agent._answer keeps adding the
    failed tries to it); everything after its first two messages becomes the template's 'retries'."""
    chain: str                                   # 'sql' | 'rewrite' | 'answer'
    values: dict
    messages: list = field(default_factory=list)

    def inputs(self):
        """The template's inputs: the values, plus the earlier tries for the SQL chain."""
        if self.chain != "sql":
            return dict(self.values)
        retries = [AIMessage(m["content"]) if m["role"] == "assistant" else HumanMessage(m["content"])
                   for m in self.messages[2:]]
        return {**self.values, "retries": retries}


def chat(request, max_tokens, effort, model=None):
    """One AI call through the request's chain -> (reply text, total tokens or None, True when cut off) -
    what agent._chat() returns for a classic call."""
    model = model or agent.model_name()
    attempt = 0
    while True:
        attempt += 1
        chain = CHAINS[request.chain](llm.make_llm(model, max_tokens, effort))  # no key -> AIUnavailable
        try:
            text, tokens, cut_off = chains.reply_info(chain.invoke(request.inputs()))
            log.info("Groq tokens (LangChain, %s): total %s", request.chain, "?" if tokens is None else tokens)
            return text, tokens, cut_off
        except openai.RateLimitError as exc:
            if agent.DAILY_LIMIT.search(str(exc)):  # e.g. "tokens per day (TPD): Limit 200000, Used ..."
                log.warning("Groq daily limit reached for %s (LangChain)", model)
                raise agent.DailyLimitReached(model) from None
            wait = agent._retry_after(exc)
            if attempt > agent.RATE_LIMIT_RETRIES or wait > agent.MAX_WAIT_SECS:
                log.warning("Groq rate limit: giving up (wait asked: %.0f s, LangChain)", wait)
                raise agent.AIUnavailable(agent.AI_BUSY) from None
            log.warning("Groq rate limit: waiting %.1f s (retry %s, LangChain)", wait, attempt)
            agent._wait(wait)
        except (openai.APIConnectionError, openai.InternalServerError):  # network / Groq side
            if attempt >= 2:
                raise agent.AIUnavailable(agent.AI_DOWN) from None
            agent._wait(3)
        except openai.APIStatusError as exc:  # 400 / 401 / 413 ...: retrying will not help
            log.error("Groq error %s (LangChain): %s", exc.status_code, str(exc)[:300])
            if exc.status_code == 413:  # more than the tokens a minute allows: a smaller request may go
                raise agent.RequestTooLarge() from None
            raise agent.AIUnavailable(agent.AI_ERROR) from None
        except openai.OpenAIError as exc:
            log.error("Groq error (LangChain): %s", str(exc)[:300])
            raise agent.AIUnavailable(agent.AI_ERROR) from None
