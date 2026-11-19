# 18-Nov: a question keeps why another AI model than the chain's first answered (the answer card's model note)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('portal', '0018_conversation_mode'),
    ]

    operations = [
        migrations.AddField(
            model_name='question',
            name='model_note',
            field=models.CharField(blank=True, default='', max_length=200),
        ),
    ]
