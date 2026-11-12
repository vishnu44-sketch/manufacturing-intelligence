"""Long-term user memory (like ChatGPT's "Memory"): facts a user asked the app to remember, used in ALL his
later chats. Not the chat memory (lc/memory.py), which is only the last questions of one chat.

Saving - only when the user says so, by rules (no AI call, no tokens). A message is a memory instruction
only when it STARTS with one of these (any case; "please" in front is fine):
    remember (that / to) ... / keep in mind ...   "Remember that I only work with export sales"
    from now on ...                                "From now on show amounts in lakhs"
    always <verb> ... / never <verb> ...           "Always round to whole rupees", "Never show credit notes"
    I (only) work with / on / in ..., I care about ..., I prefer ..., I am (only) interested in ...
    I don't like / don't want ...                  "I don't want service sales in totals"
The rules are narrow on purpose - a normal question must never be saved instead of answered:
- a message with a question mark is a question ("always show rows?", "remember my last question?");
- a fact that starts with a question ("remember who ...") or goes on with one ("I work with export,
  what were sales in Aug") is a question;
- "always" / "never" count only with a verb of ACTION_VERBS ("never mind", "never ordered" are not);
- "I don't like this answer" is feedback, not a preference.
The saved text is the fact itself: "remember that i only work with export sales." -> "I only work with export
sales". At most MAX_MEMORIES per user, MIN_CHARS to UserMemory.MAX_CHARS characters, no exact duplicates.

Using it: the question graph's first node (lc/graph.load_memories) reads texts_for(user); the SQL, answer and
documents prompts get them as a short block (agent.preferences), which is '' when the user has none - the
prompts are then exactly as before.
"""
import re

from .models import UserMemory

MAX_MEMORIES = 20   # per user; then the user deletes some first
MIN_CHARS = 3

SAVED = 'Got it - I will remember: "{text}". You can see or delete it on the Memory page.'
ALREADY = 'I already remember this: "{text}". You can see or delete it on the Memory page.'
FULL = (f"Your memory is full ({MAX_MEMORIES} of {MAX_MEMORIES}). Please delete some memories on the Memory "
        "page first, then try again.")
TOO_SHORT = 'Please tell me what to remember, e.g. "Remember that I only work with export sales".'
TOO_LONG = f"That is too long to remember - please keep one memory under {UserMemory.MAX_CHARS} characters."

_PLEASE = r"(?:please\s+|pls\s+|kindly\s+)?"
# the verbs that make "always ..." / "never ..." an instruction about the answers
ACTION_VERBS = (r"(?:show|give|use|include|exclude|leave|answer|reply|round|display|list|sort|order|report|filter|"
                r"write|mention|convert|express|split|group|count|treat|add|start|keep|put|compare|ignore|hide)")
RULES = [  # each finds the fact to save in a message that is a memory instruction
    re.compile(rf"^{_PLEASE}(?:remember|keep\s+in\s+mind)(?:\s*[:,\-]\s*|\s+)"
               r"(?:that\s+|this\s*:\s*|to\s+)?(?P<fact>.+)$", re.I),
    re.compile(rf"^{_PLEASE}from\s+now\s+on\b[\s,:\-]*(?P<fact>.+)$", re.I),
    re.compile(rf"^{_PLEASE}(?P<fact>(?:always|never)\s+{ACTION_VERBS}\b.+)$", re.I),
    re.compile(r"^(?P<fact>i\s+(?:only\s+|mainly\s+|mostly\s+|usually\s+)?(?:work\s+(?:with|on|in|for)|care\s+about|"
               r"prefer)\b.+)$", re.I),
    re.compile(r"^(?P<fact>(?:i\s+am|i'm)\s+(?:only\s+|mainly\s+|mostly\s+)?(?:interested\s+in|responsible\s+for|"
               r"in\s+charge\s+of)\b.+)$", re.I),
    re.compile(r"^(?P<fact>i\s+(?:do\s+not|don't|dont)\s+(?:like|want)\b.+)$", re.I),
]
_QUESTION_START = re.compile(r"^(?:what|which|who|whom|whose|how|when|where|why|can\s+you|could\s+you|tell\s+me|"
                             r"is\s+there|are\s+there)\b", re.I)
_QUESTION_AFTER = re.compile(r"(?:[,;:.!]|\s[-\u2013]|\band\b|\bbut\b|\bthen\b)\s*(?:what|which|who|how|when|where|"
                             r"why|can\s+you|could\s+you|show\s+me|give\s+me|tell\s+me|list|find)\b", re.I)
_FEEDBACK = re.compile(r"^i\s+(?:do\s+not|don't|dont)\s+(?:like|want)\s+(?:it|this|that|(?:this|that|the|your)\s+"
                       r"(?:answer|result|reply|one))\W*$", re.I)


def _plain(text):
    """One line, with curly apostrophes made straight."""
    return " ".join((text or "").replace("\u2019", "'").replace("\u2018", "'").split())


def memory_fact(text):
    """The fact to remember when the message is a memory instruction ("Remember that I only work with export
    sales" -> "I only work with export sales"); None for a normal question. No AI call."""
    message = _plain(text)
    if not message or "?" in message:
        return None
    if _FEEDBACK.match(message):
        return None
    for rule in RULES:
        found = rule.match(message)
        if not found:
            continue
        fact = found.group("fact")  # the user's own spelling and case
        if _QUESTION_START.match(fact) or _QUESTION_AFTER.search(fact):
            return None
        return clean(fact)
    return None


def clean(text):
    """The fact as it is saved: one line, no quotes or end stop around it, a capital first letter and
    "i" written as "I"."""
    text = _plain(text).strip(" \"'`\u201c\u201d").rstrip(" .!,;:").strip(" \"'`\u201c\u201d")
    text = re.sub(r"(?<![\w'])i(?=\s|'(?:m|ve|d|ll)\b|$)", "I", text)
    return text[:1].upper() + text[1:]


def texts_for(user):
    """The user's memories as texts, oldest first ([] for no user) - what the prompts get."""
    if user is None or not getattr(user, "is_authenticated", False) or not getattr(user, "pk", None):
        return []
    return list(UserMemory.objects.filter(user=user).order_by("created_at", "pk").values_list("text", flat=True))


def remember(user, text, question=None):
    """Save one memory for the user, with the limits. -> (outcome, message for the user, the new UserMemory):
    outcome 'saved'; 'known' when it is already remembered (an exact duplicate, any case); 'refused' when it is
    too short or too long, or the user already has MAX_MEMORIES."""
    text = clean(text)
    if len(text) < MIN_CHARS:
        return "refused", TOO_SHORT, None
    if len(text) > UserMemory.MAX_CHARS:
        return "refused", TOO_LONG, None
    known = user.memories.all()
    if any(memory.text.lower() == text.lower() for memory in known):
        return "known", ALREADY.format(text=text), None
    if len(known) >= MAX_MEMORIES:
        return "refused", FULL, None
    memory = UserMemory.objects.create(user=user, text=text, question=question)
    return "saved", SAVED.format(text=text), memory
