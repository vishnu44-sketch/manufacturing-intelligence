"""Check the company's local AI model (20-Nov, lc/llm.py "local"): is it set up, can it be reached, does it answer.

python manage.py check_local_llm            the settings, then ONE tiny chat message ("Reply with only the word OK.")
python manage.py check_local_llm --models   also list the models the server has (GET <LOCAL_LLM_URL>/models) - to
                                            pick the right LOCAL_LLM_MODEL name

Prints the reply, the seconds it took and the tokens (when the server reports them). The key (LOCAL_LLM_API_KEY) is
never printed - only whether it is set. Exit code 1 (CommandError) when it is not set up or does not answer, with a
plain reason: could not be reached, did not answer in time, 404 (a wrong model name, or the URL does not end with /v1).
No Groq call, ever.
"""
import os
import time

import httpx
import openai
from django.core.management.base import BaseCommand, CommandError
from langchain_core.messages import HumanMessage

from ...lc import llm

PROMPT = "Reply with only the word OK."
MAX_TOKENS = 20
LIST_TIMEOUT_SECS = 15
CONTEXT_TIP = ("Tip: the app's SQL request is ~7,000-10,000 tokens - give the model a context of at least 16,000 "
               "tokens (Ollama: num_ctx / OLLAMA_CONTEXT_LENGTH=16384; Ollama cuts a longer request silently).")
DOCKER_TIP = ("In Docker, 'localhost' is the container itself - use the server's IP address, or "
              "host.docker.internal for a server on the same PC.")


def list_models(url, api_key, timeout=LIST_TIMEOUT_SECS):
    """The model ids the server lists (GET <url>/models, the OpenAI-compatible list). Raises httpx errors."""
    response = httpx.get(f"{url.rstrip('/')}/models", headers={"Authorization": f"Bearer {api_key}"},
                         timeout=timeout)
    response.raise_for_status()
    data = response.json()
    rows = data.get("data") if isinstance(data, dict) else None
    if rows is None and isinstance(data, dict):  # Ollama's own /api/tags style: {"models": [{"name": ...}]}
        rows = data.get("models")
    return [str(row.get("id") or row.get("name") or row) if isinstance(row, dict) else str(row) for row in rows or []]


def chat_error(exc, timeout):
    """The plain reason of a failed chat call (openai.* errors as ChatOpenAI raises them)."""
    if isinstance(exc, openai.APITimeoutError):
        return f"The local AI model did not answer within {timeout:g} s (LOCAL_LLM_TIMEOUT) - is the server busy?"
    if isinstance(exc, openai.APIConnectionError):
        return f"{llm.LOCAL_DOWN} {DOCKER_TIP}"
    status = getattr(exc, "status_code", None)
    if status == 404:
        return llm.LOCAL_NOT_FOUND + " Run with --models to see the names the server has."
    if status in (401, 403):
        return llm.LOCAL_BAD_KEY.format(status=status)
    return f"The local AI model returned an error ({f'HTTP {status}' if status else type(exc).__name__}): " \
           f"{str(exc)[:300]}"


class Command(BaseCommand):
    help = "Check the company's local AI model (LOCAL_LLM_URL / LOCAL_LLM_MODEL): one tiny chat message."

    def add_arguments(self, parser):
        parser.add_argument("--models", action="store_true",
                            help="also list the server's models (GET <LOCAL_LLM_URL>/models)")

    def handle(self, *args, **opts):
        url, name = os.getenv(llm.LOCAL_URL, "").strip(), os.getenv(llm.LOCAL_MODEL, "").strip()
        has_key = bool(os.getenv(llm.LOCAL_KEY, "").strip())
        timeout = llm.local_timeout()
        self.stdout.write(f"{llm.LOCAL_URL}:     {url or '(not set)'}")
        self.stdout.write(f"{llm.LOCAL_MODEL}:   {name or '(not set)'}")
        self.stdout.write(f"{llm.LOCAL_KEY}: {'set' if has_key else 'not set (a dummy key is sent)'}")
        self.stdout.write(f"{llm.LOCAL_TIMEOUT}: {timeout:g} s")
        self.stdout.write(f"{llm.LOCAL_THINKING}: {'on' if llm.local_thinking() else 'off (thinking switched off)'}")
        if url and "://" not in url:
            self.stdout.write(self.style.WARNING(f"Note: {llm.LOCAL_URL} must start with http:// "
                                                 "(e.g. http://10.0.0.5:11434/v1)."))
        if url and not url.rstrip("/").endswith("/v1"):
            self.stdout.write(self.style.WARNING(f"Note: {llm.LOCAL_URL} usually ends with /v1 "
                                                 "(e.g. http://10.0.0.5:11434/v1 for Ollama)."))
        if url and opts["models"]:
            self.show_models(url, os.getenv(llm.LOCAL_KEY, "").strip() or llm.LOCAL_DUMMY_KEY)
        if not (url and name):
            raise CommandError(llm.LOCAL_MISSING)

        entry = llm.local_model()
        self.stdout.write(f"Asking {entry.label}: {PROMPT!r} (at most {MAX_TOKENS} tokens) ...")
        started = time.perf_counter()
        try:
            chat = llm.make_llm(entry.model, MAX_TOKENS, "low", key_env=llm.LOCAL_KEY)
            message = chat.invoke([HumanMessage(PROMPT)])
        except openai.OpenAIError as exc:
            secs = time.perf_counter() - started
            raise CommandError(f"{chat_error(exc, timeout)} (after {secs:.1f} s)") from None
        secs = time.perf_counter() - started
        text = message.content if isinstance(message.content, str) else str(message.content)
        self.stdout.write(f"Reply: {text.strip()!r}")
        self.stdout.write(f"Time: {secs:.1f} s")
        usage = getattr(message, "usage_metadata", None) or {}
        if usage:
            self.stdout.write(f"Tokens: prompt {usage.get('input_tokens', '?')}, reply {usage.get('output_tokens', '?')}"
                              f", total {usage.get('total_tokens', '?')}")
        else:
            self.stdout.write("Tokens: the server reported none (they count as 0 in the app)")
        if not text.strip():
            if llm.local_thinking():
                hint = f"set {llm.LOCAL_THINKING}=off (or remove it) in .env"
            else:
                hint = "the server may not support switching thinking off"
            self.stdout.write(self.style.WARNING("The reply was empty - a 'thinking' model may use all "
                                                 f"{MAX_TOKENS} tokens to think; {hint}."))
        self.stdout.write(CONTEXT_TIP)
        self.stdout.write(self.style.SUCCESS(f"OK - the local model answered in {secs:.1f} s."))

    def show_models(self, url, api_key):
        """Print the server's models (a failure here is only a note: the chat check still runs)."""
        try:
            names = list_models(url, api_key)
        except httpx.HTTPStatusError as exc:
            self.stdout.write(self.style.WARNING(f"Could not list the models: HTTP {exc.response.status_code} "
                                                 f"from {url.rstrip('/')}/models (the URL must end with /v1)."))
            return
        except (httpx.HTTPError, ValueError) as exc:
            self.stdout.write(self.style.WARNING(f"Could not list the models: {type(exc).__name__} - "
                                                 "the server could not be reached."))
            return
        self.stdout.write(f"Models on the server ({len(names)}): " + (", ".join(names) or "none"))
