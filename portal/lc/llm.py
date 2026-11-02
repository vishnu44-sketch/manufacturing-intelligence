"""LangChain step C: the AI model as a LangChain chat model (ChatOpenAI pointed at Groq).

Why ChatOpenAI and not ChatGroq: every langchain-groq version needs groq below 1.0, and the classic
pipeline uses groq 1.7.0. Groq also serves the same models through an OpenAI-compatible address
(GROQ_OPENAI_URL), so ChatOpenAI reaches the same model with the same key and the same tokens.

The settings are the classic ones (agent.get_groq_client, agent._chat): temperature 0, the model's
reasoning setting (agent._model_options), the smaller limits of the backup model, and max_retries=0 -
waiting after a per-minute limit and switching to the backup model stay in our own code (step D).
"""
import os

from ..rag import agent

GROQ_OPENAI_URL = "https://api.groq.com/openai/v1"  # Groq's OpenAI-compatible address
TIMEOUT_SECS = 90                                    # like agent.get_groq_client()
MISSING_KEY = "The AI service is not set up (GROQ_API_KEY is missing in .env)."


def make_llm(model, max_tokens, effort):
    """A ChatOpenAI for one AI call of `model`: max_tokens for its reply, effort = 'low' / 'medium' (how hard a
    reasoning model thinks). The backup model gets at most agent.FALLBACK_MAX_TOKENS, like in the classic _ask_ai()."""
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
        max_retries=0,                     # our own code waits and retries (agent._chat's rules)
        timeout=TIMEOUT_SECS,
        use_responses_api=False,           # the plain chat-completions call, like the classic client
        # Groq's own settings, sent as they are: gpt-oss -> reasoning_effort + include_reasoning False,
        # qwen3 -> reasoning_format hidden (the model's thinking stays out of the reply)
        extra_body=agent._model_options(model, effort) or None,
    )


def main_llm(max_tokens, effort):
    """The main model (GROQ_MODEL in .env)."""
    return make_llm(agent.model_name(), max_tokens, effort)


def backup_llm(max_tokens, effort):
    """The backup model (GROQ_FALLBACK_MODEL in .env); None when there is no backup."""
    backup = agent.fallback_model_name()
    return make_llm(backup, max_tokens, effort) if backup else None
