"""loader/load_gold.py: the cleaning helpers and the incremental-load key logic.
Pure Python - no MySQL, no Groq, no input files."""
import importlib.util
from datetime import date, datetime
from pathlib import Path

import pytest

LOADER_FILE = Path(__file__).resolve().parents[2] / "loader" / "load_gold.py"
spec = importlib.util.spec_from_file_location("load_gold", LOADER_FILE)
lg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lg)


@pytest.fixture
def fixes():
    return lg.Fixes()


# ---------- dates ----------
@pytest.mark.parametrize("value", ["21/09/26", "21/09/2026", "21-09-2026", "2026-09-21",
                                   datetime(2026, 9, 21), date(2026, 9, 21), 46286])
def test_clean_date_reads_every_known_form(value, fixes):
    assert lg.clean_date(value, "%d/%m/%y", fixes) == date(2026, 9, 21)


def test_clean_date_own_format_keeps_the_old_fix_text(fixes):
    lg.clean_date("02/04/24", "%d/%m/%y", fixes)
    assert fixes.counts == {"text date dd/mm/yy -> DATE": 1}


def test_clean_date_other_format_is_counted_separately(fixes):
    lg.clean_date("2026-09-21", "%d/%m/%Y", fixes)
    assert fixes.counts == {"text date in another format (yyyy-mm-dd) -> DATE": 1}


@pytest.mark.parametrize("value", ["31/02/27", "2026-13-01", "abc"])
def test_clean_date_impossible_date_is_null_and_counted(value, fixes):
    assert lg.clean_date(value, "%d/%m/%y", fixes) is None
    assert fixes.counts == {"bad date -> NULL": 1}


@pytest.mark.parametrize("value", ["NA", "#N/A", "-", "NULL", ""])
def test_clean_date_placeholder_is_null(value, fixes):
    assert lg.clean_date(value, "%d/%m/%y", fixes) is None


def test_clean_date_outside_the_calendar_gets_unknown_date_id(fixes):
    day = lg.clean_date("15/03/28", "%d/%m/%y", fixes)
    assert day == date(2028, 3, 15)
    assert lg.date_id(day) == lg.UNKNOWN


# ---------- numbers ----------
@pytest.mark.parametrize("value, expected", [
    ("1,23,456.00", 123456.0), ("Rs. 4500", 4500.0), ("Rs.4,500.00", 4500.0), ("₹4,500", 4500.0),
    ("4500 INR", 4500.0), (" 4500 ", 4500.0), ("-1,23,456.78", -123456.78), (4500, 4500)])
def test_clean_number_reads_messy_amounts(value, expected, fixes):
    assert lg.clean_number(value, fixes) == expected


@pytest.mark.parametrize("value", ["abc", "12..50", "n.a.5"])
def test_clean_number_bad_amount_is_null_and_counted(value, fixes):
    assert lg.clean_number(value, fixes) is None
    assert fixes.counts["bad number -> NULL"] == 1


# ---------- flags, status, terms, tax, country, rate month ----------
@pytest.mark.parametrize("value, expected", [
    ("YES", "Y"), ("Yes", "Y"), ("y", "Y"), ("TRUE", "Y"), ("1", "Y"), (1, "Y"), (True, "Y"),
    ("NO", "N"), ("no", "N"), ("FALSE", "N"), ("0", "N"), (False, "N")])
def test_clean_yes_no(value, expected, fixes):
    assert lg.clean_yes_no(value, fixes) == expected


@pytest.mark.parametrize("value, expected", [
    ("OPEN", "Open"), ("closed ", "Closed"), ("cancelled", "Canceled"), ("Cancelled", "Canceled"),
    ("CANCELED", "Canceled")])
def test_clean_status(value, expected, fixes):
    assert lg.clean_status(value, fixes) == expected
    assert fixes.counts["status text casing / spelling made consistent"] == 1


def test_clean_status_already_clean_is_not_a_fix(fixes):
    assert lg.clean_status("Canceled", fixes) == "Canceled"
    assert fixes.counts == {}


@pytest.mark.parametrize("value, expected", [
    ("Net-60 days", "Net-60"), ("NET 30", "Net-30"), ("net-45 days", "Net-45"), ("Net 60 days", "Net-60"),
    ("Net-30", "Net-30"), ("100% ADVANCE", "100% ADVANCE"), ("Immediate Against Supply", "Immediate Against Supply")])
def test_clean_payment_terms(value, expected, fixes):
    assert lg.clean_payment_terms(value, fixes) == expected


def test_clean_payment_terms_keeps_the_old_fix_text(fixes):
    lg.clean_payment_terms("Net-60 days", fixes)
    lg.clean_payment_terms("Net-30", fixes)
    assert fixes.counts == {"payment terms 'Net-60 days' -> 'Net-60'": 1}


@pytest.mark.parametrize("written", ["IGST 18", "igst_18", "IGST-18", "Igst 18%", "IGST18", " igst 18 "])
def test_tax_key(written):
    assert lg.tax_key(written) == "IGST18"


@pytest.mark.parametrize("value, expected", [
    ("Inida", "India"), ("INDIA", "India"), ("india", "India"), ("U.A.E.", "United Arab Emirates"),
    ("UAE", "United Arab Emirates"), ("Unites Arab Emirates", "United Arab Emirates"),
    ("U.S.A.", "United States of America"), ("United State of America", "United States of America"),
    ("U.K.", "United Kingdom"), ("JAPAN", "Japan"), ("Saudi Arabiya", "Saudi Arabia"), ("Japan", "Japan")])
def test_clean_country(value, expected, fixes):
    assert lg.clean_country(value, fixes) == expected


@pytest.mark.parametrize("value, expected", [
    ("Jan-25", "Jan 2025"), ("September 2026", "Sep 2026"), ("jan-27", "Jan 2027"), ("FEB-2027", "Feb 2027"),
    ("2027-03", "Mar 2027"), ("Nov 2026", "Nov 2026"), ("Sept 26", "Sept 26")])
def test_rate_month_label(value, expected, fixes):
    assert lg.rate_month_label(value, fixes) == expected


@pytest.mark.parametrize("written", ["Mr. Rahul Verma", "Mr.  Rahul Verma", "RAHUL VERMA", "rahul verma",
                                     "Mr Rahul Verma", "Rahul  Verma"])
def test_person_key_matches_the_ways_a_name_is_written(written, fixes):
    assert lg.person_key(lg.clean_text(written, fixes)) == "RAHUL VERMA"


def test_sales_people_take_the_most_common_written_form():
    rows = ([{"Sales Employee": "RAHUL VERMA"}] + [{"Sales Employee": "Mr. Rahul Verma"}] * 3
            + [{"Sales Employee": "Ms. Kavya Reddy"}])
    people, info = lg.build_sales_people(rows, [])
    real = {p["sales_person_name"]: p["name_with_title"] for p in people if p["sales_person_id"] != lg.UNKNOWN}
    assert real == {"Kavya Reddy": "Ms. Kavya Reddy", "Rahul Verma": "Mr. Rahul Verma"}
    assert info["fixes"].counts["sales person written in other ways (matched without title / case / spaces)"] == 1


# ---------- incremental load: duplicates, keys, ids ----------
def test_drop_exact_duplicates_ignores_id_and_row_number(fixes):
    rows = [{"id": 1, "source_row_no": 1, "so_number": 5, "qty": 2},
            {"id": 2, "source_row_no": 2, "so_number": 5, "qty": 3},
            {"id": 3, "source_row_no": 9, "so_number": 5, "qty": 2}]
    kept = lg.drop_exact_duplicates(rows, {"id", "source_row_no"}, fixes)
    assert [r["id"] for r in kept] == [1, 2]
    assert fixes.counts == {lg.DUPLICATES_SKIPPED: 1}


def test_line_keys_number_the_lines_inside_each_document():
    rows = [{"doc": "A"}, {"doc": "B"}, {"doc": "A"}, {"doc": "A"}]
    assert lg.line_keys(rows, lambda r: r["doc"]) == [("A", 1), ("B", 1), ("A", 2), ("A", 3)]


def test_sales_order_document_includes_the_financial_year():
    """SO numbers restart every FY: SO 5 of FY 2025-26 is not SO 5 of FY 2026-27."""
    _, document_of = lg.FACT_DOCUMENT["fact_sales_order_lines"]
    assert document_of({"so_number": 5, "order_date": date(2026, 3, 31)}) == (5, 2025)
    assert document_of({"so_number": 5, "order_date": date(2026, 4, 1)}) == (5, 2026)


def test_note_document_is_the_note_number_not_the_invoice():
    _, document_of = lg.FACT_DOCUMENT["fact_invoice_lines"]
    note = {"document_type": "CREDIT_NOTE", "invoice_number": "NOPI/D/2627/5", "note_number": "NOPI/CN/2627/4"}
    invoice = {"document_type": "INVOICE", "invoice_number": "NOPI/D/2627/5", "note_number": None}
    assert document_of(note) == ("CREDIT_NOTE", "NOPI/CN/2627/4")
    assert document_of(invoice) == ("INVOICE", "NOPI/D/2627/5")


def test_plan_dimension_reuses_ids_adds_new_ones_and_skips_a_key_sent_twice():
    gold = [{"customer_id": -1, "customer_code": "UNKNOWN", "customer_name": "Unknown customer"},
            {"customer_id": 1, "customer_code": "C0001", "customer_name": "Orion"},
            {"customer_id": 2, "customer_code": None, "customer_name": "Sapphire Trading Co. 1"}]
    batch = [{"customer_id": -1, "customer_code": "UNKNOWN", "customer_name": "Unknown customer"},
             {"customer_id": 1, "customer_code": "C0041", "customer_name": "Nova Pumps LLP"},
             {"customer_id": 2, "customer_code": "C0001", "customer_name": "Orion (new name)"},
             {"customer_id": 3, "customer_code": "C0041", "customer_name": "Nova Pumps LLP"},
             {"customer_id": 4, "customer_code": None, "customer_name": "SAPPHIRE  Trading Co. 1"}]
    planned, duplicates, max_old_id = lg.plan_dimension(lg.CUSTOMERS, batch, gold, keep_existing=False)
    assert [(r["customer_id"], r["customer_code"]) for r in planned] == [(3, "C0041"), (1, "C0001"), (2, None)]
    assert planned[1]["customer_name"] == "Orion (new name)"     # same key, new values -> update in place
    assert duplicates == 1 and max_old_id == 2


def test_plan_dimension_keep_existing_keeps_the_gold_row():
    gold = [{"sales_person_id": 1, "sales_person_name": "Rahul Verma", "name_with_title": "Mr. Rahul Verma"}]
    batch = [{"sales_person_id": 1, "sales_person_name": "RAHUL VERMA", "name_with_title": "RAHUL VERMA"},
             {"sales_person_id": 2, "sales_person_name": "Kavya Reddy", "name_with_title": "Ms. Kavya Reddy"}]
    planned, _, _ = lg.plan_dimension(lg.SALES_PEOPLE, batch, gold, keep_existing=True)
    assert planned[0] == gold[0]
    assert planned[1]["sales_person_id"] == 2


def test_same_values_compares_text_exactly_and_skips_key_and_row_number():
    sql = lg.same_values(lg.SALES_ORDER_LINES)
    assert "sales_order_line_id" not in sql and "source_row_no" not in sql
    assert "CAST(t.`status` AS BINARY) <=> CAST(s.`status` AS BINARY)" in sql
    assert "t.`total_amount` <=> s.`total_amount`" in sql


def test_reference_file_missing_from_a_batch_comes_from_inputdata(tmp_path):
    batch_dir, base_dir = tmp_path / "batch", tmp_path / "inputdata"
    batch_dir.mkdir()
    base_dir.mkdir()
    (batch_dir / lg.SALES_ORDER_FILE).write_text("x")
    src = lg.Source(batch_dir, reference_folder=base_dir)
    assert src.has(lg.SALES_ORDER_FILE) and not src.has(lg.CLIENT_FILE)
    assert src.reference_path(lg.CLIENT_FILE) == base_dir / lg.CLIENT_FILE
    assert src.reference_path(lg.SALES_ORDER_FILE) == batch_dir / lg.SALES_ORDER_FILE
