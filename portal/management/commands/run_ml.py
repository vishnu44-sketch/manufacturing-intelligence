"""Train the ML scenarios on ss_gold and write the ml_* tables - the same as  python ml/run_ml.py.

python manage.py run_ml            read ss_gold, train, write ml_inputdata/*.csv and the ml_* tables
python manage.py run_ml --dry-run  the same without writing anything into MySQL

It uses the MySQL ADMIN login of .env (MYSQL_USER / MYSQL_PASSWORD, like loader/load_gold.py) and writes only
ml_* tables inside ss_gold. The website reads the results as the read-only user (/api/insights).
"""
from django.core.management.base import BaseCommand

from ml import run_ml


class Command(BaseCommand):
    help = "Train the ML scenarios on ss_gold and write the ml_* result tables (see ml/run_ml.py)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="train and write the CSV files, but not MySQL")

    def handle(self, *args, **options):
        run_ml.run(dry_run=options["dry_run"], out=self.stdout.write)
