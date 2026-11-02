from django.conf import settings
from django.db import models
from django.utils import timezone


class Conversation(models.Model):
    """One Ask NOP chat (like a ChatGPT conversation): the questions a user asked in it, listed on
    the left of the Ask page. A chat is only made with its first question, so no empty chats pile up.
    "Remove from list" only hides it (archived) - its questions stay in History; "Delete" removes the
    chat AND its questions for good."""

    TITLE_CHARS = 60  # the list shows the first question, cut to about this length

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="conversations")
    title = models.CharField(max_length=200)                  # first question, or what the user renamed it to
    created_at = models.DateTimeField(default=timezone.now)   # time of the first question
    updated_at = models.DateTimeField(default=timezone.now)   # time of the last question (list order)
    archived = models.BooleanField(default=False)             # "Remove from list": hidden, still in History

    class Meta:
        ordering = ["-updated_at", "-pk"]  # most recently used first

    def __str__(self):
        return self.title

    @classmethod
    def title_from(cls, text):
        """'Top 5 customers by invoice value in Aug 2026?' - one line, at most TITLE_CHARS
        characters, cut at a word with an ellipsis when it is longer."""
        line = " ".join((text or "").split()) or "New chat"
        if len(line) <= cls.TITLE_CHARS:
            return line
        cut = line[:cls.TITLE_CHARS - 1].rsplit(" ", 1)[0].rstrip(" ,.;:-")
        return (cut or line[:cls.TITLE_CHARS - 1]) + "…"


class Question(models.Model):
    """One question a user asked on the Ask NOP page, with what came back."""

    # how the question ended
    STATUS_CHOICES = [
        ("ok", "Answered"),        # SQL ran, rows + answer shown
        ("nodata", "No data"),     # a NOP business question, but its data is not in ai_gold (e.g. profit)
        ("refused", "Refused"),    # not a question about NOP data - no SQL was run
        ("error", "Failed"),       # no working SQL after 3 tries, or a service was down
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="questions")
    # the chat it was asked in; deleting a chat deletes its questions (empty only for questions
    # saved outside a chat, e.g. by tools)
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, null=True, blank=True,
                                     related_name="questions")
    text = models.TextField()                       # the question as typed
    sql = models.TextField(blank=True)              # the SQL that was run (only when it ran)
    answer = models.TextField(blank=True)           # the short answer shown
    rows_count = models.IntegerField(null=True, blank=True)  # rows the SQL returned
    secs = models.FloatField(null=True, blank=True)          # how long it took
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="ok")
    error = models.TextField(blank=True)            # what went wrong (for the admin), never a secret
    sources = models.JSONField(default=list, blank=True)  # the docs pieces used: [{heading, kind, ...}]
    tries = models.PositiveSmallIntegerField(default=0)   # how many SQL attempts the AI needed
    model = models.CharField(max_length=100, blank=True, default="")  # Groq model that answered
    # Groq tokens as Groq reported them (empty for questions saved before tokens were counted)
    sql_tokens = models.PositiveIntegerField(null=True, blank=True)     # SQL step, all tries together
    answer_tokens = models.PositiveIntegerField(null=True, blank=True)  # answer-writing step
    total_tokens = models.PositiveIntegerField(null=True, blank=True)   # both steps
    created_at = models.DateTimeField(auto_now_add=True)
    # "Edit" on the Ask page (like ChatGPT): the edited question is a NEW row that takes this one's
    # place in the chat; this one is then hidden from the chat but stays in History, marked edited
    replaced_by = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="replaces")
    chat_order = models.DateTimeField(null=True, blank=True)  # its place in the chat (empty = created_at)
    # a follow-up question ('and for Sep?') written out on its own, as the AI understood it with the
    # chat's earlier questions ('' = the question was understood on its own)
    understood_as = models.TextField(blank=True, default="")
    # seconds per step, e.g. {"embed": 0.05, "sql_ai": 6.5, "mysql": 0.8, "wait": 45.0} (agent.STEP_NAMES);
    # empty for questions saved before the steps were timed (02-Nov)
    step_secs = models.JSONField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]  # newest first

    def __str__(self):
        return self.text[:80]

    @property
    def total_tokens_text(self):
        """'4,517' for the History table, '-' when not counted."""
        return "-" if self.total_tokens is None else f"{self.total_tokens:,}"
