# 17-Nov: a chat started on the ML Insights page is an ML chat (mode 'ml'); '' = a chat of the Assistant

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('portal', '0017_question_status_general'),
    ]

    operations = [
        migrations.AddField(
            model_name='conversation',
            name='mode',
            field=models.CharField(blank=True, default='', max_length=10),
        ),
    ]
