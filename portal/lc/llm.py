"""LangChain step C: the AI models as LangChain chat models (ChatOpenAI pointed at Groq).

Why ChatOpenAI and not ChatGroq: Groq serves its models through an OpenAI-compatible address
(GROQ_OPENAI_URL), so ChatOpenAI reaches the same model with the same key and the same tokens - and
langchain-groq would need an old groq package (below 1.0).

The model chain (18-Nov; 19-Nov: Groq only, with a second Groq key): every AI call tries these models in turn
until one answers (agent._ask_models):
  groq-main      GROQ_MODEL (default openai/gpt-oss-120b) on GROQ_API_KEY     the full request
  groq-main-2    the SAME model on GROQ_API_KEY_2 (a second Groq account)     the full request
  groq-backup    GROQ_FALLBACK_MODEL (empty = none) on GROQ_API_KEY           the cut request, at most 1,000 tokens
19-Nov, the second key: each Groq account has its own daily (and per-minute) token limits, so when the first key's
limit is reached the same strong model is asked on the second key before the weaker backup - two accounts, twice
the daily tokens. groq-main-2 is left out silently when GROQ_API_KEY_2 is not set. Because groq-main and groq-main-2
send the same model name, a model of the chain is told apart by its id (and its key setting), never by its name
alone: the dedup below, the key make_llm() uses and the resting memory (agent._resting) all go by it.
AI_MODEL_CHAIN (optional, e.g. "groq-main,groq-main-2,groq-backup") sets the order; an id left out is not used, an
unknown id (e.g. one of an older chain) is ignored. An admin's chosen model is the only model asked (no fallback: a
clear error when it cannot answer - agent._ask_models).

The settings: temperature 0, the model's reasoning setting, the smaller limits of the backup model, a 90 s timeout
and max_retries=0 - waiting after a per-minute limit and moving to the next model stay in our own code (calls.py
and agent._ask_ai). Tests swap make_llm() for a fake chat model: no test ever reaches Groq.
"""
import os
import re
from dataclasses import dataclass

from ..rag import agent

GROQ_OPENAI_URL = "https://api.groq.com/openai/v1"  # Groq's OpenAI-compatible address
TIMEOUT_SECS = 90                                    # seconds one Groq call may take
KEY = "GROQ_API_KEY"                                 # the .env setting of the first Groq key
KEY_2 = "GROQ_API_KEY_2"                             # 19-Nov: the .env setting of the second Groq key (optional)
MISSING_KEY = "The AI service is not set up (GROQ_API_KEY is missing in .env)."
MISSING_KEY_2 = "The AI service is not set up (GROQ_API_KEY_2 is missing in .env)."
MISSING_KEYS = {KEY: MISSING_KEY, KEY_2: MISSING_KEY_2}

MODEL_IDS = ("groq-main", "groq-main-2", "groq-backup")  # the fixed ids, default order
# short names for the notes ("Groq's daily limit was reached", "the second Groq key was busy")
SHORT_NAMES = {"groq-main": "Groq", "groq-main-2": "the second Groq key", "groq-backup": "the Groq backup model"}


@dataclass(frozen=True)
class ChainModel:
    """One model of the chain: its fixed id, the .env setting of the Groq key it uses, the model name sent to Groq,
    the name shown on the answer card, and whether it gets the full request (False = the cut one, calls.for_backup)."""
    id: str
    key_env: str         # 'GROQ_API_KEY' | 'GROQ_API_KEY_2' (the setting's name - never the key itself)
    model: str           # e.g. 'openai/gpt-oss-120b'
    label: str           # e.g. 'Groq gpt-oss-120b', 'Groq gpt-oss-120b (2nd key)'
    full_request: bool

    @property
    def short(self):
        return SHORT_NAMES.get(self.id, self.label)


def _key(key_env):
    """The Groq key of this .env setting ('' = not set). Never printed or logged."""
    return os.getenv(key_env, "").strip()


def _family(model):
    """'qwen/qwen3.8-27b' -> 'qwen' (the model family, for the backup's label)."""
    match = re.match(r"[a-z]+", model.split("/")[-1].lower())
    return match.group(0) if match else model


def known_models():
    """{id: ChainModel} of every model that is set up (the second key only when GROQ_API_KEY_2 is set; the backup
    only when GROQ_FALLBACK_MODEL is)."""
    main = agent.model_name()
    label = f"Groq {main.split('/')[-1]}"
    found = {"groq-main": ChainModel("groq-main", KEY, main, label, True)}
    if _key(KEY_2):
        found["groq-main-2"] = ChainModel("groq-main-2", KEY_2, main, f"{label} (2nd key)", True)
    backup = agent.fallback_model_name()
    if backup:
        found["groq-backup"] = ChainModel("groq-backup", KEY, backup, f"Groq {_family(backup)} ({backup})", False)
    return found


def chain_order():
    """The ids in the order of AI_MODEL_CHAIN (unknown ids are left out); the default order when it is empty."""
    wanted = [part.strip().lower() for part in os.getenv("AI_MODEL_CHAIN", "").split(",") if part.strip()]
    order = [model_id for model_id in dict.fromkeys(wanted) if model_id in MODEL_IDS]
    return order or list(MODEL_IDS)


def chain_models():
    """The models every AI call tries, in order (the same model on the same key listed twice is tried once; 19-Nov:
    the same model on the other key is a model of its own - groq-main-2 stays)."""
    found, seen, chain = known_models(), set(), []
    for model_id in chain_order():
        entry = found.get(model_id)
        if entry and (entry.key_env, entry.model) not in seen:
            seen.add((entry.key_env, entry.model))
            chain.append(entry)
    return chain


def find(model):
    """The ChainModel with this model name (the chain first, then any model that is set up); None = not known.
    Both Groq keys send the same name: the first one found is given (they have the same label)."""
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


def make_llm(model, max_tokens, effort, key_env=KEY):
    """A ChatOpenAI for one AI call of `model` on the Groq key of the .env setting key_env (GROQ_API_KEY, or
    GROQ_API_KEY_2 for the second key - ChainModel.key_env): max_tokens for its reply, effort = 'low' / 'medium'
    (how hard a reasoning model thinks). The Groq backup model gets at most agent.FALLBACK_MAX_TOKENS (as in
    agent._ask_ai()). AIUnavailable with a friendly message when that key is missing."""
    from langchain_openai import ChatOpenAI  # imported here: the import itself is slow

    api_key = _key(key_env)
    if not api_key:
        raise agent.AIUnavailable(MISSING_KEYS.get(key_env, MISSING_KEY))
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
