"""Questions ABOUT the previous answer of a chat - "is that correct?", "are you sure?", "how did you get this?" -
answered by our own code: no AI call, no tokens.

16-Nov: after a right answer (a bar chart of the last 5 months' sales, 5 rows) the user asked "is that above answer
is correct". It went to the SQL step like every message, the AI replied NO_SQL and the user got "NOT A COMPANY DATA
QUESTION" - for 6,735 tokens. Now such a message is found by rules (like user_memory.memory_fact) and answered here:
- check ("is that correct", "are you sure", "double check", "can you confirm" ...): the earlier answer's saved SQL
  runs again, read-only (sql_guard.check_sql + warehouse.run_select - the same SQL the History page re-runs; no new
  SQL is ever written). The reply says whether the rows count is the same as before and whether every number of the
  earlier answer is in the rows - honestly, also when something differs;
- how ("how did you get this", "where does this number come from" ...): the earlier answer's SQL in plain words
  (sql_words.describe_sql) - and the SQL runs again too, so the table / chart shows once more.

Only in a chat (the context is an lc.memory.ChatHistory): the MCP server and the eval give no chat, so their
questions take the normal path as before. The earlier answer is the chat's newest answered question (the chat
memory, lc/memory.chat_questions - which leaves these check messages out, so the next follow-up still builds on
the real data question). A check reply is saved as a Question like every message (0 tokens, no model).

The rules are narrow on purpose - a real data question must never be answered this way: every sentence of the
message must be one of the phrases below as a whole, about "that / this / it / the (above) answer / these numbers
..." - so "is Allied Castings our top customer?" or "are sales in Oct correct for export?" are normal questions.
"""
import decimal
import re
import time

from .rag import warehouse
from .rag.sql_guard import GuardError, check_sql

CHECK, HOW = "check", "how"
STEP_LABEL = "Run the same SQL again on MySQL (ss_gold)"   # the step the streamed Ask page shows
MAX_CHARS = 160         # a check message is short
MAX_WORDS = 16          # per sentence

# ------------------------------------------------------------------ the replies
NO_EARLIER = ("There is no earlier answer in this chat that I can check yet. Ask a data question first - then I can "
              "run its query again and show you where the numbers come from.")
FROM_DOCUMENTS = ("My last answer came from the company documents, not from a database query: the document and page "
                  "it used are named under it, so you can check it there.")
NOT_FROM_QUERY = ("My last answer did not come from a database query (the SS Manufacturing data does not have what was asked), so "
                  "there are no numbers of mine to check.")
DID_NOT_RUN = ("I tried to run the same query again, but it did not run this time ({problem}). So I cannot check my "
               "answer right now - please ask the question again.")
FROM_DATABASE = ("The numbers come straight from the database - the AI only wrote the query and the words. You can "
                 "open Show SQL to see the query.")
GO_BY_ROWS = ("The rows below come straight from the database - please go by them. You can open Show SQL to see the "
              "query.")
HOW_FALLBACK = ("the AI wrote one read-only database query for your question and the app ran it on the database. You "
                "can open Show SQL to see the query.")
EVERY_NUMBER = "Every number comes from running this query on the database."

# ------------------------------------------------------------------ the rules
_DET = r"(?:that|this|these|those|it|the|your|ur)"
_ADJ = r"(?:above|previous|prev|last|earlier|given|same|first|whole)"
_NOUN = (r"(?:answers?|ans|results?|reply|replies|response|numbers?|figures?|data|output|values?|totals?|amounts?|"
         r"calculations?|one|query|sql|info|information)")
SUBJECT = rf"(?:everything|all\s+of\s+(?:it|this|that)|{_DET}(?:\s+{_ADJ})?(?:\s+{_NOUN})?|{_ADJ}(?:\s+{_NOUN})?|{_NOUN})"
_IS = r"(?:is|are|was|were|r)"
_REALLY = r"(?:(?:really|actually|fully|totally|100\s*%|100\s+percent|exactly|definitely|all|completely)\s+)?"
_CORRECT = r"(?:c[ou]rr?e[ck]?t|corrct|right|rite|true|accurate|acurate|okay|ok|fine|valid|proper|exact|reliable|sure)"
_CORRECT_ALONE = r"(?:c[ou]rr?e[ck]?t|corrct|right|true|accurate|acurate)"   # "correct?" with nothing before it
_WRONG = r"(?:wrong|incorrect|not\s+(?:c[ou]rr?e[ck]?t|right|true|accurate)|off|a\s+mistake|false)"
_OR_NOT = r"(?:\s+or\s+(?:not|wrong|no|incorrect|right))?"
_YOU = r"(?:you|u)"
_ASK = (r"(?:(?:can|could|would|will)\s+(?:you|u)\s+(?:please\s+|pls\s+|plz\s+|kindly\s+)?|"
        r"(?:please|pls|plz|kindly)\s+|let'?s\s+|i\s+want\s+you\s+to\s+)?")
_VERB = (r"(?:double[\s-]?check|re-?check|cross[\s-]?check|check|verify|re-?verify|cross[\s-]?verify|confirm|"
         r"re-?confirm|validate|re-?validate)")
_VERBED = r"(?:double[\s-]?checked|re-?checked|cross[\s-]?checked|checked|verified|confirmed|validated)"
_AGAIN = r"(?:\s+(?:again|once\s+again|once\s+more|one\s+more\s+time|properly|carefully|once))*"
_WHETHER = rf"(?:\s+(?:if|whether|that)?\s*(?:{SUBJECT}\s+)?(?:{_IS}\s+)?{_REALLY}(?:{_CORRECT}|{_WRONG}){_OR_NOT})?"
_GET = (r"(?:get|got|find|found|calculate|calculated|compute|computed|work\s+out|worked\s+out|arrive\s+at|arrived\s+at|"
        r"come\s+up\s+with|came\s+up\s+with|reach|reached|derive|derived|do|did|make|made|figure\s+out|figured\s+out|"
        r"fetch|fetched|pull|pulled|know|knew)")
_DONE = (r"(?:calculated|found|computed|worked\s+out|done|made|arrived\s+at|derived|counted|got|gotten|figured\s+out|"
         r"fetched)")
_STEPS = r"(?:steps|logic|working|workings|method|calculation|formula|query|sql)"

CHECK_RULES = [re.compile(rule) for rule in (
    # "is that correct", "is the above answer correct", "is that above answer is correct", "are these numbers right"
    rf"{_IS}\s+{SUBJECT}(?:\s+{_IS})?\s+{_REALLY}(?:{_CORRECT}|{_WRONG}){_OR_NOT}",
    # "is that the correct answer", "is it the right number"
    rf"{_IS}\s+(?:it|this|that|these|those)\s+(?:the|a|an)\s+{_REALLY}{_CORRECT}\s+{_NOUN}",
    # "correct or not", "above answer correct or not", "right or wrong"
    rf"(?:{SUBJECT}\s+)?(?:{_IS}\s+)?{_REALLY}{_CORRECT}\s+or\s+(?:not|wrong|no|incorrect)",
    # "this is wrong", "the numbers look wrong", "i think that answer is incorrect", "seems off"
    rf"(?:i\s+(?:think|feel|guess)\s+)?(?:{SUBJECT}\s+(?:{_IS}|looks?|seems?|sounds?)|looks?|seems?)\s+{_REALLY}{_WRONG}",
    # "that doesn't look right"
    rf"{SUBJECT}\s+(?:does\s+not|doesn'?t|do\s+not|don'?t|dont)\s+(?:look|seem|sound)\s+(?:{_CORRECT})",
    # "are you sure", "r u sure", "you sure about this answer"
    rf"(?:(?:are|r)\s+)?{_YOU}\s+{_REALLY}sure(?:\s+(?:about|of|on)\s+{SUBJECT})?",
    # "how sure are you", "how accurate is this answer"
    rf"how\s+(?:sure|confident|certain)\s+(?:are|r)\s+{_YOU}(?:\s+(?:about|of)\s+{SUBJECT})?",
    rf"how\s+(?:accurate|reliable|correct|right|true)\s+{_IS}\s+{SUBJECT}",
    # "double check", "check it again", "verify this", "can you confirm", "check this answer is correct or not"
    rf"{_ASK}{_VERB}(?:\s+{SUBJECT})?{_AGAIN}{_WHETHER}",
    # "did you check it", "have you verified the numbers"
    rf"(?:did|have|had)\s+{_YOU}\s+(?:{_VERBED}|{_VERB})(?:\s+{SUBJECT})?{_AGAIN}{_WHETHER}",
    # "i want to know if this is correct", "tell me whether the answer is right"
    rf"(?:i\s+(?:want|wanna|would\s+like)\s+to\s+know|tell\s+me|let\s+me\s+know)\s+(?:if|whether)\s+{SUBJECT}\s+"
    rf"(?:{_IS}\s+)?{_REALLY}(?:{_CORRECT}|{_WRONG}){_OR_NOT}",
)]
# only with a question mark: "this is correct?", "answer correct?", "correct?" ("that is correct." is the user agreeing)
CHECK_WITH_MARK = re.compile(rf"(?:{SUBJECT}\s+)?(?:{_IS}\s+)?{_REALLY}{_CORRECT_ALONE}")
HOW_RULES = [re.compile(rule) for rule in (
    # "how did you get this", "how did you calculate it", "how you got these numbers", "how do you know"
    rf"how\s+(?:(?:did|do|does|have)\s+)?{_YOU}\s+{_GET}(?:\s+{SUBJECT})?",
    # "how was this calculated", "how is the total worked out"
    rf"how\s+(?:was|is|were|are)\s+{SUBJECT}\s+{_DONE}",
    # "where does this number come from", "where is this from", "where did you get these numbers (from)"
    rf"(?:where|how)\s+(?:does|do|did|is|are)\s+{SUBJECT}\s+(?:come|came|coming)\s+from",
    rf"where\s+(?:is|are|was|were)\s+{SUBJECT}\s+(?:from|coming\s+from|taken\s+from)",
    rf"where\s+(?:did|do)\s+{_YOU}\s+(?:get|got|take|took|find|found)\s+{SUBJECT}(?:\s+from)?",
    rf"what\s+(?:is|was|are)\s+the\s+sources?\s+(?:of|for)\s+{SUBJECT}",
    # "explain how you got it", "can you explain this", "explain the calculation"
    rf"{_ASK}explain(?:\s+(?:me|to\s+me))?(?:\s+(?:how\s+{_YOU}\s+{_GET}(?:\s+{SUBJECT})?|{SUBJECT}|"
    rf"(?:the|your)\s+{_STEPS}|how\s+{SUBJECT}\s+(?:was|is|were|are)\s+{_DONE}))?",
    # "show me how you got it", "tell me the steps"
    rf"{_ASK}(?:show|tell)\s+(?:me\s+)?how\s+{_YOU}\s+{_GET}(?:\s+{SUBJECT})?",
    rf"{_ASK}(?:show|tell|give)\s+(?:me\s+)?(?:the\s+|your\s+)?(?:steps|logic|working|workings|method|calculation)"
    rf"(?:\s+(?:for|of|behind)\s+{SUBJECT})?",
    rf"i\s+(?:want|wanna|would\s+like)\s+to\s+know\s+how\s+{_YOU}\s+{_GET}(?:\s+{SUBJECT})?",
    # "what did you do", "what did you do to get this"
    rf"what\s+(?:did|have)\s+{_YOU}\s+(?:do|done)(?:\s+(?:here|to\s+get\s+{SUBJECT}|for\s+{SUBJECT}))?",
    # "which query did you use", "what tables did you use for this"
    rf"(?:what|which)\s+(?:query|sql|tables?|data|logic|formula|method|steps|calculation)\s+(?:did|do|have)\s+{_YOU}\s+"
    rf"(?:use|used|run|ran|apply|applied|follow|followed|take|took)(?:\s+(?:for|in|to\s+get)\s+{SUBJECT})?",
    # "what is the logic behind this"
    rf"what\s+(?:is|was)\s+(?:the|your)\s+(?:logic|method|calculation|formula|working)(?:\s+(?:behind|for|of)\s+{SUBJECT})?",
)]
_FILLER_START = re.compile(r"^(?:(?:ok(?:ay)?|hey|hi|hello|hmm+|but|so|and|then|wait|sorry|please|pls|plz|kindly|bro|"
                           r"sir|dear|one\s+question|just|actually)\b[\s,:-]*)+")
_FILLER_END = re.compile(r"(?:[\s,]+(?:please|pls|plz|kindly|bro|sir|na|now|then|for\s+me|once|again))+$")


def _sentences(text):
    """The message as plain lower-case sentences, with a flag for each: did it end with a question mark."""
    text = " ".join((text or "").replace("’", "'").replace("‘", "'").lower().split())
    found = []
    for piece, mark in re.findall(r"([^?!.;]+)([?!.;]*)", text):
        piece = _FILLER_END.sub("", _FILLER_START.sub("", piece.strip(" ,:-")).strip(" ,:-")).strip(" ,:-")
        if piece:
            found.append((piece, "?" in mark))
    return found


def _sentence_kind(sentence, asked):
    if len(sentence.split()) > MAX_WORDS:
        return None
    if any(rule.fullmatch(sentence) for rule in HOW_RULES):
        return HOW
    if any(rule.fullmatch(sentence) for rule in CHECK_RULES) or (asked and CHECK_WITH_MARK.fullmatch(sentence)):
        return CHECK
    return None


def kind(text):
    """CHECK, HOW or None: is this message a question about the previous answer? Every sentence of it must be one
    (a message with a real question in it is a normal question). HOW wins when the message asks both. No AI call."""
    if not text or len(text) > MAX_CHARS:
        return None
    sentences = _sentences(text)
    if not sentences:
        return None
    kinds = {_sentence_kind(sentence, asked) for sentence, asked in sentences}
    if None in kinds:
        return None
    return HOW if HOW in kinds else CHECK


def in_chat(context):
    """True when the question is asked in a chat (agent.ask got the chat's memory, an lc.memory.ChatHistory) -
    the MCP server and the eval give none, so their questions keep the normal path."""
    from .lc.memory import ChatHistory  # imported here: lc/memory imports this module

    return isinstance(context, ChatHistory)


def about_earlier(text, context):
    """CHECK / HOW when the message asks about the chat's previous answer and it is asked in a chat; else None."""
    return kind(text) if in_chat(context) else None


def earlier_answer(context):
    """The chat's newest earlier answered question (oldest-first memory; check messages are skipped) or None."""
    for question in reversed(list(context or [])):
        if kind(getattr(question, "text", "")) is None:
            return question
    return None


# ------------------------------------------------------------------ the numbers of an answer
_MONTHS = (r"(?:jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|sep|sept|september|"
           r"oct|october|nov|november|dec|december)\b")
# dates, financial years, months with their year and quarters are not amounts: taken out before the numbers are read
_NOT_AMOUNTS = re.compile(rf"\b\d{{1,2}}[-/ ]{_MONTHS}[-/ ,]+\d{{2,4}}\b|\b\d{{4}}-\d{{1,2}}-\d{{1,2}}\b|"
                          rf"\b\d{{1,2}}/\d{{1,2}}/\d{{2,4}}\b|\bfy\s*\d{{2,4}}(?:\s*-\s*\d{{2,4}})?\b|"
                          rf"\b\d{{4}}\s*-\s*\d{{2}}\b|\b{_MONTHS}\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}\b|"
                          rf"\b{_MONTHS}[\s-]+\d{{4}}\b|\bq[1-4]\b", re.I)
_NUMBER = re.compile(r"(?<![\w.,])(-?(?:\d{1,3}(?:,\d{2,3})+|\d+)(?:\.\d+)?)(?![\w,]\d|[a-z])"
                     r"(?:\s*(crores?|cr|lakhs?|lacs?|millions?|mn|billions?|bn|thousand)\b)?", re.I)
_SCALE = {"crore": 10 ** 7, "cr": 10 ** 7, "lakh": 10 ** 5, "lac": 10 ** 5, "million": 10 ** 6, "mn": 10 ** 6,
          "billion": 10 ** 9, "bn": 10 ** 9, "thousand": 10 ** 3}


def answer_numbers(text):
    """[(as written, value, scale)] of the amounts and counts in an answer: '12,767,485.00', 'INR 1,955,500.00',
    '2.37 crore' (scale 10 ** 7), plain integers of 10 or more. Dates (21-May-2026), FY 2025-26, 'Aug 2026', years
    (1900-2100) and small counts below 10 ('the top 5', 'the last 3 months') are left out."""
    found = []
    for match in _NUMBER.finditer(_NOT_AMOUNTS.sub(" ", text or "")):
        written, unit = match.group(1), (match.group(2) or "").lower().rstrip("s")
        value = decimal.Decimal(written.replace(",", ""))
        plain = "," not in written and "." not in written and not unit
        if plain and (abs(value) < 10 or 1900 <= value <= 2100):
            continue
        found.append((written + (f" {match.group(2)}" if unit else ""), abs(value), _SCALE.get(unit, 1)))
    return found


def _row_values(rows):
    """Every number in the rows (as absolute Decimals): number cells, and numbers inside text cells (e.g. 'HP-700')."""
    values = set()
    for row in rows:
        for cell in row:
            if isinstance(cell, bool) or cell is None:
                continue
            if isinstance(cell, (int, float, decimal.Decimal)):
                try:
                    values.add(abs(decimal.Decimal(str(cell))))
                except decimal.InvalidOperation:
                    pass
            elif isinstance(cell, str):
                values.update(abs(decimal.Decimal(n.replace(",", "")))
                              for n in re.findall(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?", cell))
    return values


def _in_rows(value, scale, values):
    """True when the answer's number is a row value - as it is, or rounded to the decimals the answer shows."""
    places = max(0, -value.as_tuple().exponent)
    step = decimal.Decimal(1).scaleb(-places)
    for row_value in values:
        shown = row_value / scale if scale != 1 else row_value
        try:
            if shown == value or shown.quantize(step, rounding=decimal.ROUND_HALF_UP) == value:
                return True
        except decimal.InvalidOperation:  # a value too big for the decimals asked
            continue
    return False


def numbers_not_in_rows(answer, rows, also_known=""):
    """(the numbers of the answer that were checked, the ones NOT in the rows) - as written in the answer.
    A number that is also in also_known (the question or the SQL: 'LIMIT 12', 'more than 100,000') and the row
    limit ('more than 500 rows') come from there, not from the rows: they are not checked."""
    known = {decimal.Decimal(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", also_known or "")
             if n.replace(",", "")}
    known.add(decimal.Decimal(warehouse.MAX_ROWS))
    values = _row_values(rows)
    checked, missing = [], []
    for written, value, scale in answer_numbers(answer):
        if scale == 1 and value in known:
            continue
        checked.append(written)
        if not _in_rows(value, scale, values):
            missing.append(written)
    return checked, missing


# ------------------------------------------------------------------ answering
def _rows(n):
    return f"{n:,} row" + ("" if n == 1 else "s")


def _list(items):
    return ", ".join(dict.fromkeys(items))  # each number once, in the answer's order


def check_reply(earlier, data):
    """The words of a check: the rows count against the saved one, and the earlier answer's numbers in the rows."""
    now, before = len(data["rows"]), getattr(earlier, "rows_count", None)
    first = "the first " if data.get("truncated") else ""
    known = " ".join([earlier.text or "", getattr(earlier, "understood_as", "") or "", earlier.sql or "", str(now)])
    checked, missing = numbers_not_in_rows(earlier.answer, data["rows"], known)
    changed = before is not None and before != now
    if changed:
        opening = (f"I ran the same query again on the database: it now gives {first}{_rows(now)}, before it gave "
                   f"{_rows(before)} - the data changed since my answer.")
    else:
        same = "" if before is None else ", the same as before"
        opening = f"I ran the same query again on the database: {first}{_rows(now)}{same}"
    if missing:
        one = len(set(missing)) == 1
        numbers = (f"{'this number' if one else 'these numbers'} of my answer {'is' if one else 'are'} not in the "
                   f"rows{' now' if changed else ''}: {_list(missing)}.")
        middle = f" {numbers[0].upper()}{numbers[1:]}" if changed else f". But {numbers}"
        return f"{opening}{middle} {GO_BY_ROWS}"
    if not checked:
        middle = " My answer has no amounts to compare with the rows." if changed else \
            ". My answer has no amounts to compare with the rows."
    elif changed:
        middle = " Every number in my answer is still in the rows."
    else:
        middle = ", and every number in my answer is in the rows."
    return f"{opening}{middle} {FROM_DATABASE}"


def describe(sql):
    """The SQL in plain sentences (sql_words.describe_sql, written by the other part of this work); [] when that
    module is not there or cannot read this SQL."""
    try:
        from .sql_words import describe_sql
    except ImportError:
        return []
    try:
        return [" ".join(str(line).split()) for line in describe_sql(sql) or [] if str(line).strip()]
    except Exception:  # the plain words are a help: a SQL they cannot read still gets the short reply
        return []


def how_reply(earlier, data):
    """The words of a how-question: the earlier answer's SQL as plain steps."""
    steps = describe(earlier.sql)
    asked = " ".join((earlier.text or "").split())
    if steps:
        text = f'This is how I found my answer to "{asked}": ' + " ".join(
            step if step.endswith((".", "!", "?")) else step + "." for step in steps) + f" {EVERY_NUMBER}"
    else:
        text = f'This is how I found my answer to "{asked}": {HOW_FALLBACK} {EVERY_NUMBER}'
    before, now = getattr(earlier, "rows_count", None), len(data["rows"])
    if before is not None and before != now:
        text += f" (Run again just now it gives {_rows(now)}, before {_rows(before)} - the data changed.)"
    return text


def answer(result, about, context):
    """Fill in the AskResult of a message about the previous answer (agent.ask_events): status, the reply, and for
    an answered data question its SQL run again with the rows. No AI call: 0 tokens, no model. MySQL down raises
    warehouse.WarehouseUnavailable (agent.ask_events turns it into its friendly message)."""
    result.model, result.sql_tokens, result.answer_tokens, result.tries = "", 0, 0, 0
    earlier = earlier_answer(context)
    status = getattr(earlier, "status", "") if earlier is not None else ""
    if earlier is None:
        result.status, result.answer = "error", NO_EARLIER
        return result
    if status == "docs":
        result.status, result.answer = "docs", FROM_DOCUMENTS
        result.sources = list(getattr(earlier, "sources", None) or [])
        return result
    if status != "ok" or not (getattr(earlier, "sql", "") or "").strip():
        result.status, result.answer = "nodata", NOT_FROM_QUERY
        return result
    started = time.perf_counter()
    try:
        data = warehouse.run_select(check_sql(earlier.sql))
    except (GuardError, warehouse.QueryError) as exc:
        result.status, result.error = "error", f"The saved SQL did not run again: {exc}"[:2000]
        result.answer = DID_NOT_RUN.format(problem=" ".join(str(exc).split())[:200].rstrip("."))
        return result
    finally:
        result.add_secs("mysql", time.perf_counter() - started)
    result.status, result.sql = "ok", earlier.sql
    result.columns, result.rows, result.truncated = data["columns"], data["rows"], data["truncated"]
    # the chart / table words of the earlier question go with the rows again (the Ask page picks the chart from
    # them); the chat memory leaves this message out, so the next follow-up never builds on it
    shown = getattr(earlier, "understood_as", "") or earlier.text
    if about == HOW:
        result.answer = how_reply(earlier, data)
        result.understood_as = f"How the answer was found to: {shown}"
    else:
        result.answer = check_reply(earlier, data)
        result.understood_as = f"Check of the answer to: {shown}"
    return result
