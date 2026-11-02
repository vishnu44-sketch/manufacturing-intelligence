"""Chats (Conversation) replace the single "current chat" start (AskChat).

Existing questions are put into chats: ONE CHAT PER USER PER DAY (India date), titled by that
day's first question. Nothing is deleted. Going back (migrate portal 0005) unlinks the questions
and removes the chats again."""
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models
from django.utils import timezone

TITLE_CHARS = 60  # same rule as Conversation.title_from (copied: a migration must not import app code)


def title_from(text):
    line = " ".join((text or "").split()) or "New chat"
    if len(line) <= TITLE_CHARS:
        return line
    cut = line[:TITLE_CHARS - 1].rsplit(" ", 1)[0].rstrip(" ,.;:-")
    return (cut or line[:TITLE_CHARS - 1]) + "…"


def questions_into_chats(apps, schema_editor):
    """Every question without a chat goes into its user's chat of that day (made when needed)."""
    Question = apps.get_model("portal", "Question")
    Conversation = apps.get_model("portal", "Conversation")
    chats = {}  # (user id, local date) -> Conversation
    for question in Question.objects.filter(conversation__isnull=True).order_by("created_at", "pk"):
        key = (question.user_id, timezone.localtime(question.created_at).date())
        chat = chats.get(key)
        if chat is None:
            chat = chats[key] = Conversation.objects.create(
                user_id=question.user_id, title=title_from(question.text),
                created_at=question.created_at, updated_at=question.created_at)
        chat.updated_at = question.created_at  # the last question of the day so far
        question.conversation_id = chat.pk
        question.save(update_fields=["conversation"])
    for chat in chats.values():
        chat.save(update_fields=["updated_at"])


def chats_back_to_questions(apps, schema_editor):
    """Going back: unlink every question and remove the chats (the questions stay)."""
    apps.get_model("portal", "Question").objects.update(conversation=None)
    apps.get_model("portal", "Conversation").objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('portal', '0005_askchat'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Conversation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=200)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('updated_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('archived', models.BooleanField(default=False)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                           related_name='conversations', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-updated_at', '-pk']},
        ),
        migrations.AddField(
            model_name='question',
            name='conversation',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                                    related_name='questions', to='portal.conversation'),
        ),
        migrations.RunPython(questions_into_chats, chats_back_to_questions),
        migrations.DeleteModel(name='AskChat'),
    ]
