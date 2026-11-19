"""The golden set: real questions with their right answers, to measure how often Manufacturing Intelligence is right.

questions.py  the questions; the right values come from our own SQL on ss_gold (never from the AI)
grading.py    PASS / PARTIAL / FAIL for one saved answer
Run with:  python manage.py run_eval quick | ml | full [--model gemini-flash]   (see portal/management/commands/run_eval.py)
"""
