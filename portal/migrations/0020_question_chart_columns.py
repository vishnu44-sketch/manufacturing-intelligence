# 19-Nov: a question keeps the result columns its CHART line names to draw ({"value", "label", "series"})

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('portal', '0019_question_model_note'),
    ]

    operations = [
        migrations.AddField(
            model_name='question',
            name='chart_columns',
            field=models.JSONField(blank=True, null=True),
        ),
    ]
