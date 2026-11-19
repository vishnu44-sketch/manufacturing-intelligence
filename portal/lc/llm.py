"""LangChain step C: the AI models as LangChain chat models (ChatOpenAI pointed at Groq or Google Gemini).

Why ChatOpenAI and not ChatGroq: Groq serves its models through an OpenAI-compatible address
(GROQ_OPENAI_URL), so ChatOpenAI reaches the same model with the same key and the same tokens - and
langchain-groq would need an old groq package (below 1.0). Google Gemini has an OpenAI-compatible address too
(GEMINI_OPENAI_URL), so the same ChatOpenAI reaches it with the GEMINI_API_KEY (18-Nov).

The model chain (18-Nov): every AI call tries these models in turn until one answers (agent._ask_models):
  groq-main          GROQ_MODEL            (default openai/gpt-oss-120b)    the full request
  gemini-flash       GEMINI_MODEL          (default gemini-flash-latest)    the full request (large context)
  gemini-flash-lite  GEMINI_LITE_MODEL     (default gemini-flash-lite-latest)  the cut request (calls.for_backup)
  groq-backup        GROQ_FALLBACK_MODEL   (empty = none)                   the cut request, at most 1,000 tokens
AI_MODEL_CHAIN (optional, e.g. "groq-main,gemini-flash,gemini-flash-lite,groq-backup") sets the order; an id left
out is not used. The Gemini models are left out silently when GEMINI_API_KEY is not set.
Gemini Flash-Lite only does the small calls (rewrite, route - ALLOWED_CALLS); an admin's chosen model is the only
model asked (no fallback: a clear error when it cannot answer - agent._ask_models).

The settings: temperature 0, the model's reasoning setting, the smaller limits of the backup model, a 90 s
timeout for Groq (45 s for Gemini: a hanging call moves on to the next model sooner) and max_retries=0 -
waiting after a per-minute limit and moving to the next model stay in our own code (calls.py and agent._ask_ai).
Tests swap make_llm() for a fake chat model: no test ever reaches Groq or Gemini.
"""
import os
import re
from dataclasses import dataclass

from ..rag import agent

GROQ_OPENAI_URL = "https://api.groq.com/openai/v1"  # Groq's OpenAI-compatible address
GEMINI_OPENAI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"  # Google's OpenAI-compatible address
TIMEOUT_SECS = 90                                    # seconds one Groq call may take
GEMINI_TIMEOUT_SECS = 45                             # seconds one Gemini call may take (then the next model)
# Gemini models think before they reply and the thinking counts in max_tokens: this much room is added for it,
# so the reply itself still has the app's max_tokens (the thinking is kept short: reasoning_effort "low")
GEMINI_THINKING_ROOM = 2000
DEFAULT_GEMINI_MODEL = "gemini-flash-latest"
DEFAULT_GEMINI_LITE_MODEL = "gemini-flash-lite-latest"
MISSING_KEY = "The AI service is not set up (GROQ_API_KEY is missing in .env)."
GEMINI_MISSING_KEY = "The AI service is not set up (GEMINI_API_KEY is missing in .env)."

MODEL_IDS = ("groq-main", "gemini-flash", "gemini-flash-lite", "groq-backup")  # the fixed ids, default order
# short names for the notes ("Groq's daily limit was reached", "Gemini Flash was busy")
SHORT_NAMES = {"groq-main": "Groq", "gemini-flash": "Gemini Flash", "gemini-flash-lite": "Gemini Flash-Lite",
               "groq-backup": "the Groq backup model"}

# 18-Nov (the Flash-Lite bug): which calls a model may do. The important calls - the SQL ('sql'), the answers
# ('answer', 'docs', 'general') and the AI chart ('chart') - go only to the strong models; Gemini Flash-Lite wrote
# wrong SQL ("no forecast for Aug 2027" while the total forecast was there), so it only does the small calls: the
# follow-up rewrite ('rewrite') and the route ('route'). A model not listed may do every call. The Groq backup stays
# allowed everywhere as the last resort (its card note says so plainly: agent.model_note).
SMALL_CALLS = frozenset({"rewrite", "route"})
ALLOWED_CALLS = {"gemini-flash-lite": SMALL_CALLS}


def may_do(entry, kind):
    """True when this model (a ChainModel) may do this call (an LcRequest's chain: 'sql', 'answer', 'rewrite' ...)."""
    allowed = ALLOWED_CALLS.get(entry.id)
    return allowed is None or kind in allowed


@dataclass(frozen=True)
class ChainModel:
    """One model of the chain: its fixed id, who serves it, the model name sent to that service, the name shown
    on the answer card, and whether it gets the full request (False = the cut one, calls.for_backup)."""
    id: str
    provider: str        # 'groq' | 'gemini'
    model: str           # e.g. 'openai/gpt-oss-120b', 'gemini-flash-latest'
    label: str           # e.g. 'Groq gpt-oss-120b', 'Gemini Flash (gemini-flash-latest)'
    full_request: bool

    @property
    def short(self):
        return SHORT_NAMES.get(self.id, self.label)


def gemini_key():
    """The Gemini key from .env ('' = Gemini is not set up). Never printed or logged."""
    return os.getenv("GEMINI_API_KEY", "").strip()


def _family(model):
    """'qwen/qwen3.8-27b' -> 'qwen' (the model family, for the backup's label)."""
    match = re.match(r"[a-z]+", model.split("/")[-1].lower())
    return match.group(0) if match else model


def known_models():
    """{id: ChainModel} of every model that is set up (Gemini only with its key; the backup only when set)."""
    main = agent.model_name()
    found = {"groq-main": ChainModel("groq-main", "groq", main, f"Groq {main.split('/')[-1]}", True)}
    if gemini_key():
        flash = os.getenv("GEMINI_MODEL", "").strip() or DEFAULT_GEMINI_MODEL
        lite = os.getenv("GEMINI_LITE_MODEL", "").strip() or DEFAULT_GEMINI_LITE_MODEL
        found["gemini-flash"] = ChainModel("gemini-flash", "gemini", flash, f"Gemini Flash ({flash})", True)
        found["gemini-flash-lite"] = ChainModel("gemini-flash-lite", "gemini", lite, f"Gemini Flash-Lite ({lite})",
                                                False)
    backup = agent.fallback_model_name()
    if backup:
        found["groq-backup"] = ChainModel("groq-backup", "groq", backup, f"Groq {_family(backup)} ({backup})", False)
    return found


def chain_order():
    """The ids in the order of AI_MODEL_CHAIN (unknown ids are left out); the default order when it is empty."""
    wanted = [part.strip().lower() for part in os.getenv("AI_MODEL_CHAIN", "").split(",") if part.strip()]
    order = [model_id for model_id in dict.fromkeys(wanted) if model_id in MODEL_IDS]
    return order or list(MODEL_IDS)


def chain_models():
    """The models every AI call tries, in order (a model name listed twice is tried once)."""
    found, seen, chain = known_models(), set(), []
    for model_id in chain_order():
        entry = found.get(model_id)
        if entry and (entry.provider, entry.model) not in seen:
            seen.add((entry.provider, entry.model))
            chain.append(entry)
    return chain


def find(model):
    """The ChainModel with this model name (the chain first, then any model that is set up); None = not known."""
    for entry in chain_models() + list(known_models().values()):
        if entry.model == model:
            return entry
    return None


def label_of(model):
    """The name shown on the answer card for a saved model name ('' for none; an old model: its own name)."""
    if not model:
        return ""
    entry = find(model)
    return entry.label if entry else model


def _provider_of(model):
    entry = find(model)
    if entry:
        return entry.provider
    return "gemini" if model.startswith("gemini") else "groq"


def make_llm(model, max_tokens, effort):
    """A ChatOpenAI for one AI call of `model`: max_tokens for its reply, effort = 'low' / 'medium' (how hard a
    reasoning model thinks). The Groq backup model gets at most agent.FALLBACK_MAX_TOKENS (as in agent._ask_ai()).
    AIUnavailable with a friendly message when the model's key (GROQ_API_KEY / GEMINI_API_KEY) is missing."""
    from langchain_openai import ChatOpenAI  # imported here: the import itself is slow

    if _provider_of(model) == "gemini":
        api_key = gemini_key()
        if not api_key:
            raise agent.AIUnavailable(GEMINI_MISSING_KEY)
        return ChatOpenAI(
            model=model,
            base_url=GEMINI_OPENAI_URL,
            api_key=api_key,
            temperature=0,
            max_tokens=max_tokens + GEMINI_THINKING_ROOM,
            max_retries=0,                     # our own code moves on to the next model (agent._ask_models)
            timeout=GEMINI_TIMEOUT_SECS,
            stream_usage=True,
            use_responses_api=False,
            # Google's setting for its thinking models: think briefly ("low" works for every Gemini Flash model)
            extra_body={"reasoning_effort": "low"},
        )
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise agent.AIUnavailable(MISSING_KEY)
    if model == agent.fallback_model_name():
        max_tokens = min(max_tokens, agent.FALLBACK_MAX_TOKENS)
    return ChatOpenAI(
        model=model,
        base_url=GROQ_OPENAI_URL,
        api_key=api_key,
        temperature=0,
        max_tokens=max_tokens,
        max_retries=0,                     # our own code waits and retries (calls.chat's rules)
        timeout=TIMEOUT_SECS,
        stream_usage=True,                 # a streamed reply (the Ask page's answer) still reports its tokens
        use_responses_api=False,           # Groq's plain chat-completions call
        # Groq's own settings, sent as they are: gpt-oss -> reasoning_effort + include_reasoning False,
        # qwen3 -> reasoning_format hidden (the model's thinking stays out of the reply)
        extra_body=agent._model_options(model, effort) or None,
    )
