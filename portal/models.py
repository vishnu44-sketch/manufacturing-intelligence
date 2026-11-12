from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class ConversationQuerySet(models.QuerySet):
    def visible(self):
        """The chats that were not deleted (a deleted chat is kept for the audit log, but nobody sees it)."""
        return self.filter(deleted_at__isnull=True)


class Conversation(models.Model):
    """One Ask NOP chat (like a ChatGPT conversation): the questions a user asked in it, listed on
    the left of the Ask page. A chat is only made with its first question, so no empty chats pile up.
    "Remove from list" only hides it (archived) - its questions stay in History; "Delete" hides the
    chat AND its questions everywhere for the user (soft delete, 03-Nov): the rows stay, so the audit
    log never loses what was asked; staff still open those questions from the Audit page."""

    TITLE_CHARS = 60  # the list shows the first question, cut to about this length

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="conversations")
    title = models.CharField(max_length=200)                  # first question, or what the user renamed it to
    created_at = models.DateTimeField(default=timezone.now)   # time of the first question
    updated_at = models.DateTimeField(default=timezone.now)   # time of the last question (list order)
    archived = models.BooleanField(default=False)             # "Remove from list": hidden, still in History
    # "Delete": when and by whom (empty = not deleted); a deleted chat and its questions are hidden for good
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+")

    objects = ConversationQuerySet.as_manager()

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


class QuestionQuerySet(models.QuerySet):
    def visible(self):
        """The questions the user still sees: not in a deleted chat (questions outside a chat count too).
        The AI usage counts every question (usage.py) - tokens of a deleted chat were still used."""
        return self.filter(Q(conversation__isnull=True) | Q(conversation__deleted_at__isnull=True))


class Question(models.Model):
    """One question a user asked on the Ask NOP page, with what came back. It is the audit trail of the
    questions: a deleted chat only hides its questions, they are never removed by the app."""

    # how the question ended
    STATUS_CHOICES = [
        ("ok", "Answered"),        # SQL ran, rows + answer shown
        ("docs", "From documents"),  # answered from the company PDFs (the pages are the sources), no SQL
        ("nodata", "No data"),     # a NOP business question, but its data is not in ai_gold (e.g. profit)
        ("refused", "Refused"),    # not a question about NOP data - no SQL was run
        ("error", "Failed"),       # no working SQL after 3 tries, or a service was down
        ("memory", "Saved to memory"),  # "Remember that ..." - saved as a UserMemory, no SQL and no AI call
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="questions")
    # the chat it was asked in; deleting a chat in the app only hides its questions (empty only for
    # questions saved outside a chat, e.g. by tools)
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

    objects = QuestionQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]  # newest first

    def __str__(self):
        return self.text[:80]

    @property
    def total_tokens_text(self):
        """'4,517' for the History table, '-' when not counted."""
        return "-" if self.total_tokens is None else f"{self.total_tokens:,}"


class UserMemory(models.Model):
    """One fact a user asked the app to remember (like ChatGPT's "Memory"), e.g. "I only work with export
    sales". It is used in ALL the user's later chats (portal/user_memory.py); the user sees and deletes
    them on the Memory page. Saved only when the user says so ("Remember that ...") or adds one there."""

    MAX_CHARS = 300  # one memory is a short sentence

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memories")
    text = models.CharField(max_length=MAX_CHARS)             # the fact, cleaned ("I only work with export sales")
    created_at = models.DateTimeField(default=timezone.now)
    # the question that said "Remember that ..." (empty when added on the Memory page, or that question was deleted)
    question = models.ForeignKey(Question, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="memories")

    class Meta:
        ordering = ["-created_at", "-pk"]  # newest first

    def __str__(self):
        return self.text[:80]


class AuditLog(models.Model):
    """One line of the audit log: who did what and when (sign-ins, people, chats, memories, Excel files,
    MCP calls) - written only by portal/audit.py, read by staff on the Audit page. Read-only: the app
    never changes or deletes a line, and the Django admin only shows them. The questions themselves are
    not copied here - the Question table is their audit trail (a line points to one by its id).
    `details` is a small JSON with what changed - never a password, hash or key."""

    # the action codes, with the plain words the Audit page shows
    ACTIONS = [
        ("login_ok", "Signed in"),
        ("login_failed", "Sign-in failed"),
        ("logout", "Signed out"),
        ("user_created", "Person added"),
        ("user_changed", "Person changed"),
        ("user_roles_changed", "Admin rights changed"),
        ("user_activated", "Person switched on"),
        ("user_deactivated", "Person switched off"),
        ("password_reset", "Password reset"),
        ("chat_renamed", "Chat renamed"),
        ("chat_removed", "Chat removed from list"),
        ("chat_restored", "Chat restored"),
        ("chat_deleted", "Chat deleted"),
        ("question_edited", "Question edited"),
        ("ask_again", "Question asked again"),
        ("memory_added", "Memory added"),
        ("memory_deleted", "Memory deleted"),
        ("memory_delete_all", "All memories deleted"),
        ("excel_downloaded", "Excel downloaded"),
        ("mcp_run_sql", "MCP: SQL run"),
        ("mcp_search_notes", "MCP: notes searched"),
        ("mcp_search_documents", "MCP: documents searched"),
        ("mcp_get_schema", "MCP: schema read"),
    ]
    USER_AGENT_CHARS = 200

    created_at = models.DateTimeField(default=timezone.now)
    # who did it (empty: a failed sign-in, an MCP call, or the person was deleted later - username still says who)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                             related_name="+")
    username = models.CharField(max_length=150, blank=True)   # a copy, so the line stays readable
    action = models.CharField(max_length=30, choices=ACTIONS)
    target = models.CharField(max_length=100, blank=True)     # what it was done to: "chat 12", "user 5", "memory 3"
    details = models.JSONField(default=dict, blank=True)      # small, never a secret
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=USER_AGENT_CHARS, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]  # newest first
        indexes = [models.Index(fields=["created_at"], name="audit_time_idx"),
                   models.Index(fields=["action"], name="audit_action_idx")]

    def __str__(self):
        return f"{self.created_at:%d %b %Y %H:%M} {self.username or '-'} {self.action} {self.target}"

    def save(self, *args, **kwargs):
        """Only new lines are written: a line already saved is never changed."""
        if self.pk is not None and not self._state.adding:
            raise PermissionError("An audit log line cannot be changed.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("An audit log line cannot be deleted.")
