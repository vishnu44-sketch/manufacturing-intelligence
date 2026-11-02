"""The on/off switch between the classic pipeline (portal/rag/) and the LangChain one (portal/lc/).

.env:  USE_LANGCHAIN=on   -> LangChain version
       USE_LANGCHAIN=off  -> classic version (also when the line is missing - the default)
Read on every question, so a change in .env needs only a restart of the web app.
"""
import os

ON_WORDS = {"on", "1", "true", "yes"}


def use_langchain():
    """True when .env says USE_LANGCHAIN=on (or 1 / true / yes); False otherwise."""
    return os.getenv("USE_LANGCHAIN", "").strip().lower() in ON_WORDS


def pipeline_name():
    """'langchain' or 'classic' - shown in messages and logs, so it is clear which version answered."""
    return "langchain" if use_langchain() else "classic"
