"""A "this year" / "last year" question whose SQL filters a CALENDAR year is sent back once.

19-Nov-2026: "What is our total sales to Sakura Pump Japan this year, and which products do they buy?" got a query
with YEAR(invoice_date) = 2026 and the answer "In calendar year 2026 ... 18.0 Cr", while the business rule
(docs/business_rules.md, "Growth and comparisons") says "this year" / "last year" = the current financial year
(dim_calendar.financial_year of CURDATE(), 01-Apr to 31-Mar) and the one before it, unless the user names the
years, months or dates. The AI still writes the SQL; this check only finds the mix-up and gives the AI a clear
problem text (lc/graph.check_sql sends it back once, like the other SQL checks).

Kept conservative - a false send-back costs a whole extra AI call. It fires only when ALL of these hold:
- the question says "this year" / "current year" / "last year" / "previous year" / "prior year" (also "this year's");
- the question does not say "calendar", names no year (2026, FY 2025-26, '26), no month, no date and no shorter
  period (this month / quarter / week, today, YTD) - those may rightly use calendar dates;
- the SQL reads no ml_ table (the ML results have their own periods);
- the SQL shows no financial-year sign: financial_year / fiscal_* / sales_year / sales_period_no columns, an
  01-Apr or 31-Mar date, MONTH(...) compared with 3 / 4, INTERVAL 3 / 9 MONTH, a sales month 'Apr 2026';
- the SQL does filter by a calendar year: YEAR(...) / EXTRACT(YEAR ...) / DATE_FORMAT(..., '%Y') / LEFT(..., 4)
  compared with something, calendar_year compared with something, an 01-Jan or 31-Dec date ('2026-01-01',
  '%Y-01-01', CONCAT(YEAR(...), '-01-01')), MAKEDATE(..., 1), DAYOFYEAR(...), or LIKE '2026%'.

20-Nov-2026 (the company's local model): "this financial year" / "this year" / "so far" questions got
c.financial_year = '2526' (FY 2025-26, LAST year) while FY 2026-27 ('2627') was running - no calendar year at all, so
the check above stayed quiet. past_fy_problem() sends such a query back once too (the same fy_check_used: at most one
send-back for either mix-up). It fires only when ALL of these hold:
- the question says this year / this financial year / current year / this FY, or (with no shorter period such as this
  month, a month name, last 3 months, today) "so far" / YTD / year to date / till date;
- the question names no year itself (2026, '26, FY 2025-26, FY26, a date, "calendar");
- the SQL reads no ml_ table;
- the SQL's financial_year / sales_year filters (= '2526', IN ('2526', ...), and financial_year_label = 'FY 2025-26')
  name only financial years BEFORE the one of today - none of today's or a later one;
- a question that also says last year / previous year (a comparison) is sent back only when the SQL shows no sign of
  the current year either (no date from its 01-Apr on, no CURDATE() / NOW()).
The FY of today comes from today (agent.today()), never a fixed year.
"""
import datetime
import re

# the question: "this year" (this / current / present) and "last year" (last / previous / prior)
_THIS_YEAR = re.compile(r"\b(?:this|current|present)\s+(?:year|yr)\b", re.I)
_LAST_YEAR = re.compile(r"\b(?:last|previous|prior)\s+(?:year|yr)\b", re.I)

_MONTHS = (r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|june?|july?|aug(?:ust)?|sep(?:t|tember)?"
           r"|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?")
# the user named the period himself (or a shorter one): the SQL may rightly use calendar dates
_NAMED_PERIOD = re.compile(
    r"calendar"
    r"|\b(?:19|20)\d\d\b|\bFY\s*'?\d|\b\d{2}\s*[-/]\s*\d{2}\b|'\d\d\b"                    # 2026, FY 2025-26, '26
    r"|\b\d{1,2}\s*[-/.]\s*\d{1,2}\s*[-/.]\s*\d{2,4}\b"                                     # 19/11/26
    rf"|\b(?:{_MONTHS})\b"
    r"|\b(?:in|of|since|from|until|till|to|for|during)\s+may\b|\bmay\s+(?:this|last|20\d\d|')"   # May, not "may"
    r"|\b(?:months?|quarters?|weeks?|days?|today|yesterday|tomorrow|q[1-4]|mtd|qtd|ytd)\b", re.I)

_ML_TABLE = re.compile(r"\bml_\w+", re.I)

_FY_SIGNS = re.compile(
    r"\b(?:financial_year(?:_label)?|fiscal_quarter|fiscal_period|sales_year|sales_period_no)\b"
    r"|-0?4-01\b|-03-31\b"                                                   # '2026-04-01', '%Y-04-01', 31-Mar
    r"|\bMONTH\s*\((?:[^()]|\([^()]*\))*\)\s*(?:>=|<=|<|>|=)\s*[34]\b"
    r"|\b[34]\s*(?:>=|<=|<|>|=)\s*MONTH\s*\("
    r"|\bINTERVAL\s+'?[39]'?\s+MONTH\b"
    r"|'Apr\s+20\d\d'", re.I)

_COMPARED_AFTER = re.compile(r"\s*(?:=|<>|!=|>=|<=|>|<|NOT\s+IN\s*\(|IN\s*\(|BETWEEN\b)", re.I)
_COMPARED_BEFORE = re.compile(r"(?:=|<>|!=|>=|<=|>|<)\s*$")
# a calendar-year function call whose result is compared: YEAR(x) = 2026, EXTRACT(YEAR FROM x) = ...,
# DATE_FORMAT(x, '%Y') = '2026', LEFT(x, 4) = '2026'; and MAKEDATE(..., 1) = 01-Jan of a year
_YEAR_CALL = re.compile(r"\b(?:YEAR|EXTRACT|DATE_FORMAT|LEFT|SUBSTR|SUBSTRING|MAKEDATE)\s*\(", re.I)
# what the call is compared with, for the problem text (up to the next AND / OR / end of the line)
_COMPARED_WITH = re.compile(r"[^\n]*?(?=\s+(?:AND|OR|GROUP|ORDER|LIMIT|THEN|HAVING)\b|\n|$)", re.I)
_CALENDAR_SIGNS = re.compile(
    r"\bcalendar_year\b\s*(?:=|<>|!=|>=|<=|>|<|NOT\s+IN\b|IN\b|BETWEEN\b)"
    r"|(?:=|<>|!=|>=|<=|>|<)\s*(?:\w+\.)?calendar_year\b"
    r"|'(?:\d{4}|%Y)?-01-01(?:\s+00:00:00)?'|'(?:\d{4}|%Y)?-12-31(?:\s+23:59:59)?'"          # 01-Jan / 31-Dec
    r"|\bDAYOFYEAR\s*\("
    r"|\bLIKE\s+'(?:19|20)\d\d-?%'", re.I)


def year_words(question):
    """Which of "this year" / "last year" the question says, in that order ([] = neither, or the user named the
    period himself: a calendar year, a year number, a month, a date, a shorter period)."""
    text = question or ""
    found = [word for word, pattern in (("this year", _THIS_YEAR), ("last year", _LAST_YEAR)) if pattern.search(text)]
    if not found or _NAMED_PERIOD.search(text):
        return []
    return found


def _closing(sql, start):
    """The index of the bracket that closes the one at sql[start] (-1 when it is never closed)."""
    depth, quote = 0, ""
    for index in range(start, len(sql)):
        char = sql[index]
        if quote:
            if char == quote:
                quote = ""
        elif char in "'\"":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _compared_year_call(sql):
    """The first calendar-year function call that is compared with something ('' = none)."""
    for match in _YEAR_CALL.finditer(sql):
        name = match.group(0).split("(")[0].strip().upper()
        end = _closing(sql, match.end() - 1)
        if end < 0:
            continue
        call = sql[match.start():end + 1]
        inside = sql[match.end():end]
        if name == "EXTRACT" and not re.match(r"\s*YEAR\s+FROM\b", inside, re.I):
            continue
        if name == "DATE_FORMAT" and not re.search(r",\s*'%Y'\s*$", inside):
            continue
        if name in ("LEFT", "SUBSTR", "SUBSTRING") and not (re.search(r",\s*(?:1\s*,\s*)?4\s*$", inside)
                                                         and re.search(r"date", inside, re.I)):
            continue
        if name == "MAKEDATE":
            if re.search(r",\s*'?1'?\s*$", inside):
                return " ".join(call.split())
            continue
        if _COMPARED_AFTER.match(sql, end + 1):
            return " ".join((call + _COMPARED_WITH.match(sql, end + 1).group(0))[:120].split())
        if _COMPARED_BEFORE.search(sql[:match.start()]):
            return " ".join(call.split())
    return ""


def calendar_year_filter(sql):
    """The part of the SQL that filters by a calendar year ('' = none; also '' when the SQL shows a financial-year
    sign or reads an ml_ table - then nothing is sent back)."""
    sql = sql or ""
    if not sql.strip() or _ML_TABLE.search(sql) or _FY_SIGNS.search(sql):
        return ""
    found = _compared_year_call(sql)
    if found:
        return found
    match = _CALENDAR_SIGNS.search(sql)
    return " ".join(match.group(0).split()) if match else ""


def financial_year(day):
    """The financial year (01-Apr to 31-Mar) of a date -> (its first calendar year, e.g. 2026 for FY 2026-27)."""
    return day.year if day.month >= 4 else day.year - 1


def _fy(first):
    """2026 -> ('FY 2026-27', '2627', '01-Apr-2026', '31-Mar-2027')."""
    return (f"FY {first}-{(first + 1) % 100:02d}", f"{first % 100:02d}{(first + 1) % 100:02d}",
            f"01-Apr-{first}", f"31-Mar-{first + 1}")


def problem(question, sql, today):
    """The text that sends the query back ('' = nothing wrong): the question says "this year" / "last year", and
    the SQL filters by a calendar year instead of the financial year - or (20-Nov) the question says this year /
    this financial year / so far, and the SQL filters only past financial years. today = the app's date
    (agent.today())."""
    return calendar_year_problem(question, sql, today) or past_fy_problem(question, sql, today)


def calendar_year_problem(question, sql, today):
    """The calendar-year send-back text of problem() ('' = none)."""
    words = year_words(question)
    if not words:
        return ""
    found = calendar_year_filter(sql)
    if not found:
        return ""
    first = financial_year(today)
    label, code, start, end = _fy(first)
    last_label, last_code, last_start, last_end = _fy(first - 1)
    said = " / ".join(f'"{word}"' for word in words)
    parts = [f"the question says {said}, but your query filters by a calendar year ({found}). Per the business "
             f"rules \"this year\" means the current financial year {label} ({start} to {end}; "
             f"dim_calendar.financial_year = '{code}'), not calendar year {today.year}"]
    if "last year" in words:
        parts.append(f"\"last year\" means the financial year before it, {last_label} ({last_start} to {last_end}; "
                     f"financial_year = '{last_code}'), not calendar year {today.year - 1}")
    only_last = words == ["last year"]
    use_code, use_first = (last_code, first - 1) if only_last else (code, first)
    parts.append(f"Filter by the financial year: JOIN dim_calendar c ON c.date_id = <fact>.<x>_date_id WHERE "
                 f"c.financial_year = '{use_code}' (or the dates from '{use_first}-04-01'), as in the example \"What "
                 f"were total net sales this year and last year, and how much did they grow?\"."
                 + ("" if only_last else f" {label} is not over yet: count only up to today (CURDATE()).")
                 + " Use calendar_year only when the user says \"calendar year\".")
    return "; ".join(parts[:-1]) + ". " + parts[-1]


# ------------------------------------------------------------------ 20-Nov: "this year" filtered as a PAST financial year
_THIS_FY = re.compile(r"\b(?:this|current|present)\s+(?:financial\s+|fiscal\s+)?(?:year|yr)\b|\b(?:this|current)\s+fy\b",
                      re.I)
_SO_FAR = re.compile(r"\b(?:so\s+far|ytd|year[\s-]+to[\s-]+date|till\s+date)\b", re.I)
# a year the user names himself: a calendar year (2026, '26, "calendar"), a FY (FY 2025-26, FY26) or a date
_YEAR_NAMED = re.compile(r"calendar|\b(?:19|20)\d\d\b|'\d\d\b|\bFY\s*'?\d{2,4}\b"
                         r"|\b\d{1,2}\s*[-/.]\s*\d{1,2}\s*[-/.]\s*\d{2,4}\b", re.I)
# a shorter period: then "so far" belongs to it ("this month so far"), not to the year
_SHORTER = re.compile(
    rf"\b(?:{_MONTHS})\b|\b(?:in|of|since|from|until|till|to|for|during)\s+may\b"
    r"|\b(?:this|current|last|previous|past|prior|recent|next)\s+(?:\d+\s+)?(?:sales\s+)?(?:months?|quarters?|weeks?|days?)\b"
    r"|\b\d+\s+(?:months?|weeks?|days?)\b|\b(?:today|yesterday|tomorrow|mtd|qtd|q[1-4])\b", re.I)
_LAST_FY = re.compile(r"\b(?:last|previous|prior)\s+(?:financial\s+|fiscal\s+)?(?:year|yr|fy)\b", re.I)
# the FY codes a query filters by: financial_year / sales_year = '2526' or IN ('2526', ...), either side of the =
_FY_FILTER = re.compile(r"\b(financial_year|sales_year)\s*(?:=\s*'(\d{4})'|IN\s*\(([^)]*)\))", re.I)
_FY_FILTER_BEFORE = re.compile(r"'(\d{4})'\s*=\s*(?:\w+\.)?(financial_year|sales_year)\b", re.I)
_FY_LABEL_FILTER = re.compile(r"\bfinancial_year_label\s*(?:=|IN\s*\()([^)\n]*)", re.I)
_TODAY_SIGN = re.compile(r"\b(?:CURDATE|CURRENT_DATE|NOW|SYSDATE|CURRENT_TIMESTAMP|UTC_DATE)\b", re.I)
_DATE_VALUE = re.compile(r"'((?:19|20)\d\d)-(\d\d)-(\d\d)")


def names_a_year(question):
    """True when the question names a year itself: a calendar year (2026, '26, "calendar"), a FY (FY 2025-26) or a
    date - then "so far" / "this year" may belong to that year: no FY note and no send-back."""
    return bool(_YEAR_NAMED.search(question or ""))


def last_year_said(question):
    """True when the question says last / previous / prior (financial) year and names no year itself."""
    return bool(_LAST_FY.search(question or "")) and not names_a_year(question)


def this_year_words(question):
    """The words of the question that mean the current financial year ('' = none, or the user named a year or a
    shorter period himself): "this financial year", "this year", "current year", "so far", "YTD" ..."""
    text = question or ""
    said = _THIS_FY.search(text)
    so_far = _SO_FAR.search(text)
    if not (said or so_far) or names_a_year(text):
        return ""
    if not said and _SHORTER.search(text):
        return ""
    return " ".join((said or so_far).group(0).split())


def _fy_code(code):
    """'2526' -> 2025 (its first year); None for a value that is not a FY code ('2530', '2026')."""
    if not re.fullmatch(r"\d{4}", code or ""):
        return None
    first, second = int(code[:2]), int(code[2:])
    return 2000 + first if second == (first + 1) % 100 else None


def fy_filters(sql):
    """[(column, code, first year)] of the FY codes the SQL filters by (financial_year / sales_year = or IN, and
    financial_year_label = 'FY 2025-26'), in order, each once."""
    found = []
    for match in _FY_FILTER.finditer(sql or ""):
        codes = [match.group(2)] if match.group(2) else re.findall(r"'(\d{4})'", match.group(3) or "")
        found += [(match.group(1).lower(), code) for code in codes]
    found += [(m.group(2).lower(), m.group(1)) for m in _FY_FILTER_BEFORE.finditer(sql or "")]
    for match in _FY_LABEL_FILTER.finditer(sql or ""):
        found += [("financial_year_label", f"{a[-2:]}{b[-2:]}")
                  for a, b in re.findall(r"'FY\s*(\d{2,4})\s*-\s*(\d{2,4})'", match.group(1), flags=re.I)]
    result = []
    for column, code in found:
        first = _fy_code(code)
        if first is not None and (column, code, first) not in result:
            result.append((column, code, first))
    return result


def _shows_current_year(sql, first):
    """True when the SQL has any sign of the FY that starts in `first`: today (CURDATE() ...) or a date from its
    01-Apr on."""
    if _TODAY_SIGN.search(sql or ""):
        return True
    for year, month, day in _DATE_VALUE.findall(sql or ""):
        try:
            if datetime.date(int(year), int(month), int(day)) >= datetime.date(first, 4, 1):
                return True
        except ValueError:
            continue
    return False


def past_fy_problem(question, sql, today):
    """The send-back text when a "this year" question's SQL filters only financial years before today's ('' = none)."""
    words = this_year_words(question)
    if not words or not (sql or "").strip() or _ML_TABLE.search(sql):
        return ""
    filters = fy_filters(sql)
    first = financial_year(today)
    if not filters or any(year >= first for _, _, year in filters):
        return ""
    if _LAST_FY.search(question or "") and _shows_current_year(sql, first):  # a comparison: this year may be in dates
        return ""
    label, code, start, end = _fy(first)
    last_label, last_code, _, _ = _fy(first - 1)
    used = ", ".join(f"{column} = '{used_code}' = {_fy(year)[0]}" for column, used_code, year in filters)
    return (f"the question says \"{words}\", but your query filters only a past financial year ({used}). Per the "
            f"business rules \"this year\" / \"this financial year\" / \"so far\" means the current financial year "
            f"{label} ({start} to {end}; dim_calendar.financial_year = '{code}', the financial_year of CURDATE()); "
            f"'{last_code}' ({last_label}) is last year. Filter c.financial_year = '{code}' (split by sales month: "
            f"c.sales_year = '{code}'), counted only up to today (CURDATE()); keep last year only where the question "
            f"also asks for it.")
