"""LangChain step C: the AI model as a LangChain chat model (ChatOpenAI pointed at Groq).

Why ChatOpenAI and not ChatGroq: Groq serves its models through an OpenAI-compatible address
(GROQ_OPENAI_URL), so ChatOpenAI reaches the same model with the same key and the same tokens - and
langchain-groq would need an old groq package (below 1.0).

The settings: temperature 0, the model's reasoning setting (agent._model_options), the smaller limits of
the backup model, a 90 s timeout and max_retries=0 - waiting after a per-minute limit and switching to
the backup model stay in our own code (calls.py and agent._ask_ai, step D).
Tests swap make_llm() for a fake chat model: no test ever reaches Groq.
"""
import os

from ..rag import agent

GROQ_OPENAI_URL = "https://api.groq.com/openai/v1"  # Groq's OpenAI-compatible address
TIMEOUT_SECS = 90                                    # seconds one AI call may take
MISSING_KEY = "The AI service is not set up (GROQ_API_KEY is missing in .env)."


def make_llm(model, max_tokens, effort):
    """A ChatOpenAI for one AI call of `model`: max_tokens for its reply, effort = 'low' / 'medium' (how hard a
    reasoning model thinks). The backup model gets at most agent.FALLBACK_MAX_TOKENS (as in agent._ask_ai()).
    AIUnavailable with a friendly message when GROQ_API_KEY is missing."""
    from langchain_openai import ChatOpenAI  # imported here: the import itself is slow

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

