"""Ask the golden questions with ONE Groq model, grade the answers and keep the score.

python manage.py run_eval quick           the 15 quick questions - after every docs or prompt change
python manage.py run_eval full            all questions - once a week; it stops before the token cap and,
                                          run again the same week, goes on where it stopped
python manage.py run_eval grade FILE      grade a saved run again (no AI)
python manage.py run_eval truth           the right values from our own SQL (no AI)
options: --model main|backup  --cap auto|N  --ids Q38 N02  --out FILE  --memory-store (Qdrant off)

- Nothing goes into History: every question runs inside a transaction that is rolled back.
- Token cap 'auto': tests may use 70 % of a model's daily Groq tokens (the app's questions and the
  eval runs of the last 24 hours count); the other 30 % stay for the people using the app.
- Only the chosen model is asked: no backup model during a main-model run (and the other way round).
- The answers of a run go to eval_results/<set>_<model>_....json (not in git); every run adds one
  score line to eval_results/scores.csv (in git), so we see if answers get better or worse.
"""
import csv
import json
import logging
import os
import subprocess
import tempfile
import time
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from ...evals import grading
from ...evals.questions import ITEMS, QUICK
from ...models import Question
from ...rag import agent

RESULTS_DIR = Path(settings.BASE_DIR) / "eval_results"
SCORE_FIELDS = ["when", "set", "model", "asked", "of", "pass", "partial", "fail", "tokens", "commit",
                "not_pass", "file"]
TEST_SHARE = 140_000          # 70 % of a model's 200,000 daily Groq tokens (Vishnu's rule)
SAFETY = 5_000
ESTIMATE, ESTIMATE_FOLLOW_UP = 7_000, 11_000   # Groq tokens of one question (a follow-up rewrites first)


def pick_items(set_name, ids=()):
    """The items to ask, in golden-set order; a follow-up brings the earlier questions of its chat."""
    wanted = set(ids or (QUICK if set_name == "quick" else [item["id"] for item in ITEMS]))
    unknown = wanted - {item["id"] for item in ITEMS}
    if unknown:
        raise CommandError(f"Not in the golden set: {', '.join(sorted(unknown))}")
    by_id = {item["id"]: item for item in ITEMS}
    todo = list(wanted)
    while todo:
        for earlier in by_id[todo.pop()].get("context", []):
            if earlier not in wanted:
                wanted.add(earlier)
                todo.append(earlier)
    return [item for item in ITEMS if item["id"] in wanted]


def tokens_last_24h(model):
    """Tokens of this model in Groq's rolling 24 hours: the app's saved questions + the eval runs."""
    app = Question.objects.filter(created_at__gte=timezone.now() - timedelta(hours=24), model=model) \
        .aggregate(total=Sum("total_tokens"))["total"] or 0
    cut, evals = datetime.now() - timedelta(hours=24), 0
    for path in RESULTS_DIR.glob("*.json"):
        try:
            results = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue
        for saved in results.values() if isinstance(results, dict) else []:
            if isinstance(saved, dict) and datetime.strptime(saved.get("asked_at", "2000-01-01 00:00:00"),
                                                             "%Y-%m-%d %H:%M:%S") >= cut:
                evals += sum(call.get("total") or 0 for call in saved.get("calls", []) if call.get("model") == model)
    return app, evals


def current_commit():
    """The git commit the answers came from ('+changes' when docs/ or portal/ have changes not committed)."""
    try:
        run = lambda *args: subprocess.run(["git", *args], cwd=settings.BASE_DIR, capture_output=True,  # noqa: E731
                                           text=True, timeout=10).stdout.strip()
        return run("rev-parse", "--short", "HEAD") + ("+changes" if run("status", "--porcelain", "docs", "portal") else "")
    except (OSError, subprocess.SubprocessError):
        return ""


def plain(value):
    return str(value) if isinstance(value, (Decimal, date, datetime)) else value


class Command(BaseCommand):
    help = "Ask the golden questions with one Groq model and grade the answers (quick | full | grade FILE | truth)."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["quick", "full", "grade", "truth"])
        parser.add_argument("file", nargs="?", help="grade: the saved run (.json)")
        parser.add_argument("--model", choices=["main", "backup"], default="main")
        parser.add_argument("--cap", default="auto", help="token cap of this run: auto (70%% rule) or a number")
        parser.add_argument("--ids", nargs="+", default=[], help="only these questions, e.g. Q38 N02")
        parser.add_argument("--out", help="the answers file (default: eval_results/<set>_<model>_<date>.json)")
        parser.add_argument("--memory-store", action="store_true",
                            help="Qdrant not running: build the same docs/ pieces in a store in memory")

    def handle(self, *args, **opts):
        if opts["action"] == "truth":
            for item in pick_items("full", opts["ids"]):
                self.stdout.write(f"{item['id']:4} must {[str(v) for v in grading.truth_values(item.get('must'))]}"
                                  f"  should {[str(v) for v in grading.truth_values(item.get('should'))]}")
        elif opts["action"] == "grade":
            if not opts["file"]:
                raise CommandError("Give the saved run: run_eval grade eval_results/<file>.json")
            results = json.loads(Path(opts["file"]).read_text(encoding="utf-8"))
            self.report(pick_items("full"), results)
        else:
            self.run(opts["action"], opts)

    # ------------------------------------------------------------------ asking
    def run(self, set_name, opts):
        items = pick_items(set_name, opts["ids"])
        main, backup = agent.model_name(), agent.fallback_model_name()
        only = main if opts["model"] == "main" else backup
        if not only:
            raise CommandError("No backup model in .env (GROQ_FALLBACK_MODEL)")
        RESULTS_DIR.mkdir(exist_ok=True)
        year, week, _ = date.today().isocalendar()   # full: one file a week, so a stopped run goes on
        stamp = f"{year}-W{week:02d}" if set_name == "full" else time.strftime("%Y-%m-%d_%H%M")
        out = Path(opts["out"] or RESULTS_DIR / f"{set_name}_{opts['model']}_{stamp}.json")
        results = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
        used = sum(saved.get("tokens") or 0 for saved in results.values())
        if opts["cap"] == "auto":   # what is left of the test share (this file's own tokens are counted again below)
            app, evals = tokens_last_24h(only)
            cap = TEST_SHARE - app - evals - SAFETY + used
            self.stdout.write(f"budget {only}: app {app:,} + eval runs {evals:,} in the last 24 h -> cap {cap:,}")
        else:
            cap = int(opts["cap"])
        user = get_user_model().objects.filter(is_superuser=True).first() or get_user_model().objects.first()
        if user is None:
            raise CommandError("No user yet: make one with  python manage.py createsuperuser")
        self.stdout.write(f"{set_name} set, {len(items)} questions, model {only}, cap {cap:,}, already used {used:,}")
        self.stdout.write(f"answers file: {out}")

        calls, logs = [], []
        with OneModel(only, opts["model"] == "backup", calls, logs, opts["memory_store"]):
            for item in items:
                qid = item["id"]
                if qid in results:
                    continue
                estimate = ESTIMATE_FOLLOW_UP if item.get("context") else ESTIMATE
                if used + estimate > cap:
                    self.stdout.write(f"STOP before {qid}: {used:,} used + about {estimate:,} would pass the cap {cap:,}"
                                      " - run the same command again later; it goes on from here")
                    break
                context = [SimpleNamespace(text=results[c]["question"], sql=results[c]["sql"],
                                           answer=results[c]["answer"], understood_as=results[c]["understood_as"])
                           for c in item.get("context", []) if c in results and results[c]["status"] in ("ok", "nodata")]
                c0, l0 = len(calls), len(logs)
                with transaction.atomic():   # nothing of the eval stays in History
                    result = agent.ask(item["question"], user, context=context)
                    transaction.set_rollback(True)
                tokens = sum(call["total"] or 0 for call in calls[c0:])
                used += tokens
                results[qid] = {"question": item["question"], "status": result.status, "model": result.model,
                                "tries": result.tries, "secs": result.secs, "understood_as": result.understood_as,
                                "sql": result.sql, "answer": result.answer, "error": result.error,
                                "notes": result.notes, "columns": result.columns,
                                "rows": [[plain(v) for v in row] for row in result.rows[:12]],
                                "row_count": result.row_count, "calls": calls[c0:], "tokens": tokens,
                                "log": [m for m in logs[l0:] if not m.startswith("Groq tokens")],
                                "asked_at": time.strftime("%Y-%m-%d %H:%M:%S")}
                out.write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
                verdict, why = grading.grade(item, results[qid])
                self.stdout.write(f"{qid}: {verdict} | {result.status} | {result.secs} s | {tokens:,} tokens"
                                  f" | total {used:,} | {'; '.join(why)}")

        counts, not_pass = self.report(items, results)
        asked = sum(counts.values())
        with_header = not (RESULTS_DIR / "scores.csv").exists()
        with open(RESULTS_DIR / "scores.csv", "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, SCORE_FIELDS)
            if with_header:
                writer.writeheader()
            writer.writerow({"when": time.strftime("%Y-%m-%d %H:%M"), "set": set_name, "model": only,
                             "asked": asked, "of": len(items), "pass": counts["PASS"], "partial": counts["PARTIAL"],
                             "fail": counts["FAIL"], "tokens": used, "commit": current_commit(),
                             "not_pass": " ".join(not_pass), "file": out.name})
        self.stdout.write(f"score line added to {RESULTS_DIR / 'scores.csv'}")

    def report(self, items, results):
        """Print every graded answer and the total -> (counts, ['Q54:FAIL', 'N02:PARTIAL', ...])."""
        graded, counts = grading.grade_results(items, results)
        for item, saved, verdict, why in graded:
            self.stdout.write(f"{item['id']:4} {verdict:7} {saved.get('secs', 0):5.1f} s {saved.get('tokens', 0):6,} tok"
                              f"  {item['question'][:55]:55} {'; '.join(why)}")
        not_asked = len(items) - len(graded)
        self.stdout.write(f"TOTAL: PASS {counts['PASS']}, PARTIAL {counts['PARTIAL']}, FAIL {counts['FAIL']}"
                          + (f", not asked yet {not_asked}" if not_asked else ""))
        return counts, [f"{item['id']}:{verdict}" for item, _, verdict, _ in graded if verdict != "PASS"]


class OneModel:
    """While a run lasts: only the chosen model is asked, its tokens are recorded, the agent's log is kept,
    and (with --memory-store) the docs come from a store in memory. Everything is put back at the end."""

    def __init__(self, only, backup, calls, logs, memory_store):
        self.only, self.backup, self.calls, self.logs, self.memory_store = only, backup, calls, logs, memory_store

    def __enter__(self):
        self.saved = {"_chat": agent._chat, "get_groq_client": agent.get_groq_client, "search": agent.search,
                      "_main_resting_until": agent._main_resting_until}
        self.saved_fallback = os.environ.get("GROQ_FALLBACK_MODEL")
        original_chat, original_client, only, calls = agent._chat, agent.get_groq_client, self.only, self.calls

        if self.backup:
            agent._main_resting_until = time.monotonic() + 10 ** 9   # as after the main model's daily limit
        else:
            os.environ["GROQ_FALLBACK_MODEL"] = ""                   # no backup during a main-model run

        def one_model_chat(client, messages, max_tokens, effort, model=None):
            if (model or agent.model_name()) != only:
                raise agent.DailyLimitReached(model)                 # never spend the other model's tokens
            return original_chat(client, messages, max_tokens, effort, model)

        def recording_client():
            client = original_client()
            create = client.chat.completions.create

            def recording(**kwargs):
                response = create(**kwargs)
                calls.append({"model": kwargs.get("model"), "total": response.usage.total_tokens,
                              "finish": getattr(response.choices[0], "finish_reason", None)})
                return response
            client.chat.completions.create = recording
            return client

        agent._chat, agent.get_groq_client = one_model_chat, recording_client
        if self.memory_store:
            from ...rag import store
            from ...rag.chunking import load_docs
            path = Path(tempfile.mkdtemp(prefix="nop_eval_store_"))
            store.rebuild(load_docs(Path(settings.BASE_DIR) / "docs"), path=path)
            agent.search = lambda question, top_k=5: store.search(question, top_k=top_k, path=path)

        logs = self.logs

        class Keep(logging.Handler):
            def emit(self, record):
                logs.append(record.getMessage())
        self.handler, self.logger = Keep(), logging.getLogger("portal")
        self.old_level = self.logger.level
        self.logger.addHandler(self.handler)
        self.logger.setLevel(logging.INFO)
        return self

    def __exit__(self, *exc):
        for name, value in self.saved.items():
            setattr(agent, name, value)
        if self.saved_fallback is None:
            os.environ.pop("GROQ_FALLBACK_MODEL", None)
        else:
            os.environ["GROQ_FALLBACK_MODEL"] = self.saved_fallback
        self.logger.removeHandler(self.handler)
        self.logger.setLevel(self.old_level)
        return False
