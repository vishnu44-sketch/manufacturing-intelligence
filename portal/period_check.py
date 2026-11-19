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
"""
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
    the SQL filters by a calendar year instead of the financial year. today = the app's date (agent.today())."""
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
