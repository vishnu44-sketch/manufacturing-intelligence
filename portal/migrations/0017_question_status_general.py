# 17-Nov: a question not about the data or the documents gets a general answer (status 'general')

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('portal', '0016_question_chart_kind'),
    ]

    operations = [
        migrations.AlterField(
            model_name='question',
            name='status',
            field=models.CharField(choices=[('ok', 'Answered'), ('docs', 'From documents'), ('nodata', 'No data'), ('general', 'General answer'), ('refused', 'Refused'), ('error', 'Failed'), ('memory', 'Saved to memory')], default='ok', max_length=10),
        ),
    ]
