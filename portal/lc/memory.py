"""The chat memory as LangChain objects: a chat history (BaseChatMessageHistory) on our own History DB.

A follow-up ("and for Sep 2026?") needs the chat's earlier questions. They are the saved Question rows
of the same chat (portal/models.py) - one database for the History page and the memory. ChatHistory
gives them to LangChain as messages, one pair per earlier question:
    HumanMessage(the question as typed,  understood_as = how it was written out)
    AIMessage(the answer,                 sql = the SQL that ran)
The question graph (graph.py) loads these messages into its state at the start: the rewrite step shows
them as a numbered list (rewrite_earlier), the SQL step as text with each SQL (sql_earlier).

Saving: agent.ask() saves every question as a full Question row (SQL, rows, tokens, time per step);
LangChain's add_messages() only has the question and the reply text, so it does not write anything.
"""
from django.db.models.functions import Coalesce
from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from ..rag import agent

LATEST = " (latest)"


def chat_questions(chat, before=None):
    """The chat's last answered questions (oldest first, at most agent.CONTEXT_SIZE) for a follow-up;
    with before=, only the ones placed before that question (an edit). Refused / failed questions
    and edited-away versions are left out; a deleted chat has no memory (its questions are hidden)."""
    if chat.deleted_at is not None:
        return []
    questions = chat.questions.filter(replaced_by__isnull=True, status__in=("ok", "docs", "nodata")).annotate(
        place=Coalesce("chat_order", "created_at"))
    if before is not None:
        questions = questions.filter(place__lt=before.chat_order or before.created_at)
    return list(questions.order_by("-place", "-pk")[:agent.CONTEXT_SIZE])[::-1]


class ChatHistory(BaseChatMessageHistory):
    """The earlier questions of one chat as LangChain messages (oldest first). Made from the chat's
    saved Questions - chat_questions(chat) or the list agent.ask() was given."""

    def __init__(self, questions=(), session_id=""):
        self.questions = list(questions or [])[-agent.CONTEXT_SIZE:]
        self.session_id = session_id  # the chat's id ('' outside a chat)

    @classmethod
    def for_chat(cls, chat, before=None):
        """The history of a saved chat (Conversation), optionally only before one question (an edit)."""
        return cls(chat_questions(chat, before), session_id=str(chat.pk))

    @property
    def messages(self):
        found = []
        for question in self.questions:  # a saved Question (or anything with its fields)
            understood = getattr(question, "understood_as", "") or ""
            found.append(HumanMessage(question.text, additional_kwargs={"understood_as": understood}))
            found.append(AIMessage(getattr(question, "answer", "") or "",
                                   additional_kwargs={"sql": getattr(question, "sql", "") or ""}))
        return found

    def add_messages(self, messages):
        """Nothing to do: agent.ask() saves the whole Question row (with its SQL, rows and tokens) itself."""

    def clear(self):
        """Nothing to do: chats are kept for the History page and deleted only from the Ask page."""

    def __bool__(self):
        return bool(self.questions)

    def __len__(self):
        return len(self.questions)

    def __iter__(self):
        """The earlier Questions themselves, oldest first."""
        return iter(self.questions)


def messages_of(memory):
    """The chat memory as LangChain messages, from a ChatHistory, a list of earlier Questions (oldest first)
    or messages already (the graph's state). [] when there is none."""
    items = memory.messages if isinstance(memory, ChatHistory) else list(memory or [])
    if items and all(isinstance(item, BaseMessage) for item in items):
        return items
    return ChatHistory(items).messages


def _pairs(messages):
    """[(HumanMessage, AIMessage)] of a history's messages."""
    return list(zip(messages[0::2], messages[1::2]))


def rewrite_earlier(messages):
    """The earlier questions for the rewrite prompt: '1. <understood as, or the question>' ... '(latest)'."""
    pairs = _pairs(messages)
    return "\n".join(f"{n}. {human.additional_kwargs.get('understood_as') or ' '.join(human.content.split())}"
                     + (LATEST if n == len(pairs) else "")
                     for n, (human, _) in enumerate(pairs, 1))


def sql_earlier(messages):
    """The earlier questions for the SQL request ('' when there are none): question, what it was
    understood as, its SQL and answer - cut, to keep the request small (agent.EARLIER_HEAD / EARLIER_ITEM)."""
    pairs = _pairs(messages)
    if not pairs:
        return ""
    items = []
    for n, (human, ai) in enumerate(pairs, start=1):
        understood = human.additional_kwargs.get("understood_as")
        sql = " ".join((ai.additional_kwargs.get("sql") or "(no SQL - not answered with data)").split())
        answer = " ".join((ai.content or "").split())
        items.append(agent.EARLIER_ITEM.format(
            n=n, question=" ".join(human.content.split()),
            understood=f"\n   Understood as: {understood}" if understood else "",
            sql=sql[:agent.CONTEXT_SQL_CHARS] + (" ..." if len(sql) > agent.CONTEXT_SQL_CHARS else ""),
            answer=answer[:agent.CONTEXT_ANSWER_CHARS] + (" ..." if len(answer) > agent.CONTEXT_ANSWER_CHARS else "")))
    return agent.EARLIER_HEAD + "\n" + "\n".join(items) + "\n"


def latest_question(messages):
    """How the chat's last question was understood (or the question itself) - '' without a history."""
    pairs = _pairs(messages)
    if not pairs:
        return ""
    human = pairs[-1][0]
    return human.additional_kwargs.get("understood_as") or human.content
