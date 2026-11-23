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

20-Nov, the company's own LOCAL model (chain id "local"): any OpenAI-compatible server inside the company (Ollama's
/v1, LM Studio, llama.cpp server, vLLM) - it runs on a CPU, so an answer can take minutes. It exists only when
LOCAL_LLM_URL (the base address, ending with /v1) and LOCAL_LLM_MODEL (the model's name on that server) are set;
LOCAL_LLM_API_KEY (only if the server asks for one - else a dummy is sent, the OpenAI client needs a value),
LOCAL_LLM_TIMEOUT (seconds per call, default 300) and LOCAL_LLM_LABEL (the name on the card, default
"Local (<model>)") and LOCAL_LLM_THINKING (on = a thinking model may think first; default off) are optional. It is NOT in the Auto chain (that stays Groq): an admin picks it (then only it is
asked, as for every admin choice), or the owner lists "local" in AI_MODEL_CHAIN. It gets the full request, none of
Groq's own settings (extra_body), and its errors have their own plain messages (calls.chat).
python manage.py check_local_llm  sends it one tiny message to see that it works.
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

# 20-Nov: the company's local model (an OpenAI-compatible server inside the company)
LOCAL_ID = "local"
LOCAL_URL = "LOCAL_LLM_URL"              # its base address incl. /v1, e.g. http://10.0.0.5:11434/v1
LOCAL_MODEL = "LOCAL_LLM_MODEL"          # the model's name on that server, e.g. qwen2.5:14b
LOCAL_KEY = "LOCAL_LLM_API_KEY"          # optional: only if the server asks for a key (never printed)
LOCAL_TIMEOUT = "LOCAL_LLM_TIMEOUT"      # optional: seconds one call may take
LOCAL_LABEL = "LOCAL_LLM_LABEL"          # optional: the name on the answer card
LOCAL_THINKING = "LOCAL_LLM_THINKING"    # optional: 'on' lets a thinking model (Qwen3 ...) think first; default off
# 20-Nov: the company's server (llama.cpp, Qwen3.6-35B) spent all 800 tokens of a SQL request thinking (26 s, empty
# answer); with thinking off it wrote the right SQL in 1.8 s. Servers that do not know this setting ignore it.
LOCAL_NO_THINKING = {"chat_template_kwargs": {"enable_thinking": False}}
LOCAL_TIMEOUT_SECS = 300                 # a CPU server: one answer can take minutes
LOCAL_DUMMY_KEY = "local"                # sent when the server needs no key (the OpenAI client needs a value)
LOCAL_HINT = "Runs on the company's CPU server - an answer can take a few minutes"
LOCAL_MISSING = "The local AI model is not set up (LOCAL_LLM_URL / LOCAL_LLM_MODEL missing in .env)."
LOCAL_DOWN = "The local AI model could not be reached (LOCAL_LLM_URL) - check that the server is running."
LOCAL_SLOW = ("The local AI model did not answer within {secs:g} s (LOCAL_LLM_TIMEOUT) - the server may still be busy. "
              "Try again, or raise LOCAL_LLM_TIMEOUT.")
LOCAL_TOO_SMALL = ("The local model's context is too small for this question - set its context to at least 16,000 "
                   "tokens (e.g. Ollama num_ctx).")
LOCAL_BUSY = "The local AI model is busy right now. Try again in a minute, or choose Auto."
LOCAL_NOT_FOUND = ("The local AI server answered 404 - check LOCAL_LLM_MODEL (the model's name on that server) and "
                   "that LOCAL_LLM_URL ends with /v1.")
LOCAL_BAD_KEY = "The local AI server refused the key ({status}) - check LOCAL_LLM_API_KEY."
LOCAL_ERROR = "The local AI model returned an error ({status}). Try again, or choose Auto."
MISSING_KEYS[LOCAL_KEY] = LOCAL_MISSING

MODEL_IDS = ("groq-main", "groq-main-2", "groq-backup", LOCAL_ID)  # the fixed ids
DEFAULT_CHAIN = ("groq-main", "groq-main-2", "groq-backup")         # Auto's order when AI_MODEL_CHAIN is empty
# short names for the notes ("Groq's daily limit was reached", "the second Groq key was busy")
SHORT_NAMES = {"groq-main": "Groq", "groq-main-2": "the second Groq key", "groq-backup": "the Groq backup model",
               LOCAL_ID: "the local AI model"}


@dataclass(frozen=True)
class ChainModel:
    """One model of the chain: its fixed id, the .env setting of the key it uses, the model name sent to the server,
    the name shown on the answer card, whether it gets the full request (False = the cut one, calls.for_backup), and
    (20-Nov) the server's address and the seconds one call may take (Groq's, or the local model's settings)."""
    id: str
    key_env: str         # 'GROQ_API_KEY' | 'GROQ_API_KEY_2' | 'LOCAL_LLM_API_KEY' (the setting's name - never the key)
    model: str           # e.g. 'openai/gpt-oss-120b'
    label: str           # e.g. 'Groq gpt-oss-120b', 'Groq gpt-oss-120b (2nd key)', 'Local (qwen2.5:14b)'
    full_request: bool
    base_url: str = GROQ_OPENAI_URL
    timeout: float = TIMEOUT_SECS

    @property
    def short(self):
        return SHORT_NAMES.get(self.id, self.label)

    @property
    def is_local(self):
        return self.key_env == LOCAL_KEY


def _key(key_env):
    """The Groq key of this .env setting ('' = not set). Never printed or logged."""
    return os.getenv(key_env, "").strip()


def _family(model):
    """'qwen/qwen3.8-27b' -> 'qwen' (the model family, for the backup's label)."""
    match = re.match(r"[a-z]+", model.split("/")[-1].lower())
    return match.group(0) if match else model


def local_timeout():
    """Seconds one call of the local model may take (LOCAL_LLM_TIMEOUT; default / not a positive number: 300)."""
    try:
        secs = float(os.getenv(LOCAL_TIMEOUT, "").strip() or LOCAL_TIMEOUT_SECS)
    except ValueError:
        secs = LOCAL_TIMEOUT_SECS
    return secs if secs > 0 else LOCAL_TIMEOUT_SECS


def local_thinking():
    """True when LOCAL_LLM_THINKING is on / true / yes / 1: the local model may think before it answers."""
    return os.getenv(LOCAL_THINKING, "").strip().lower() in ("on", "true", "yes", "1")


def local_model():
    """The local model's ChainModel, or None when LOCAL_LLM_URL or LOCAL_LLM_MODEL is not set."""
    url, name = os.getenv(LOCAL_URL, "").strip(), os.getenv(LOCAL_MODEL, "").strip()
    if not (url and name):
        return None
    label = os.getenv(LOCAL_LABEL, "").strip() or f"Local ({name})"
    return ChainModel(LOCAL_ID, LOCAL_KEY, name, label, True, base_url=url.rstrip("/"), timeout=local_timeout())


def known_models():
    """{id: ChainModel} of every model that is set up (the second key only when GROQ_API_KEY_2 is set; the backup
    only when GROQ_FALLBACK_MODEL is; 20-Nov: the local model only when LOCAL_LLM_URL and LOCAL_LLM_MODEL are)."""
    main = agent.model_name()
    label = f"Groq {main.split('/')[-1]}"
    found = {"groq-main": ChainModel("groq-main", KEY, main, label, True)}
    if _key(KEY_2):
        found["groq-main-2"] = ChainModel("groq-main-2", KEY_2, main, f"{label} (2nd key)", True)
    backup = agent.fallback_model_name()
    if backup:
        found["groq-backup"] = ChainModel("groq-backup", KEY, backup, f"Groq {_family(backup)} ({backup})", False)
    local = local_model()
    if local:
        found[LOCAL_ID] = local
    return found


def chain_order():
    """The ids in the order of AI_MODEL_CHAIN (unknown ids are left out); the default order when it is empty
    (20-Nov: Groq only - the local model is in the chain only when AI_MODEL_CHAIN lists "local")."""
    wanted = [part.strip().lower() for part in os.getenv("AI_MODEL_CHAIN", "").split(",") if part.strip()]
    order = [model_id for model_id in dict.fromkeys(wanted) if model_id in MODEL_IDS]
    return order or list(DEFAULT_CHAIN)


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


def choosable_models():
    """The models an admin may choose (and run_eval --model may ask): the chain, plus the local model when it is set
    up but not in the chain (20-Nov: it is never in Auto unless AI_MODEL_CHAIN lists it, but it can always be chosen)."""
    chain = chain_models()
    local = local_model()
    if local and all(entry.id != LOCAL_ID for entry in chain):
        chain.append(local)
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
    agent._ask_ai()). AIUnavailable with a friendly message when that key is missing.
    20-Nov: key_env LOCAL_LLM_API_KEY = the company's local model (_local_llm)."""
    from langchain_openai import ChatOpenAI  # imported here: the import itself is slow

    if key_env == LOCAL_KEY:
        return _local_llm(ChatOpenAI, model, max_tokens)
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


def _local_llm(chat_class, model, max_tokens):
    """The ChatOpenAI of the local model (20-Nov): its own address, key (a dummy when none is set) and timeout, the
    full max_tokens, and none of Groq's own settings (reasoning_effort ... - a local server may refuse them).
    Thinking is switched off (LOCAL_NO_THINKING) unless LOCAL_LLM_THINKING=on."""
    local = local_model()
    if local is None:
        raise agent.AIUnavailable(LOCAL_MISSING)
    return chat_class(
        extra_body=None if local_thinking() else LOCAL_NO_THINKING,
        model=model or local.model,
        base_url=local.base_url,
        api_key=_key(LOCAL_KEY) or LOCAL_DUMMY_KEY,
        temperature=0,
        max_tokens=max_tokens,
        max_retries=0,
        timeout=local.timeout,
        stream_usage=True,                 # a server that reports no tokens is fine: they count as none
        use_responses_api=False,           # the plain chat-completions call every OpenAI-compatible server has
    )
