"""The Knowledge graph API (/api/graph/search, /node, /similar - knowledge_graph.py): sign-in, GET only, the typed
text only ever as a SQL parameter, the limits, the FY filter (never after today), the Unknown (-1) rows, the PDF
links, similar customers, and warehouse.run_select_params (read-only like run_select).
MySQL is faked here (warehouse.run_select_params answers by the SQL it gets); the last test uses the real
read-only MySQL and is skipped without it. No AI call anywhere.
Run with:  python -m pytest -q portal/tests/test_knowledge_graph.py
"""
import datetime
from decimal import Decimal

import pytest

from portal import knowledge_graph as kg
from portal.rag import warehouse
from portal.tests.test_views_ask import api_get, api_post

pytestmark = pytest.mark.django_db

TODAY = datetime.date(2026, 11, 4)
AURORA = 3680
PAGES = [  # two pages of the demo PDFs, as document_pages() gives them
    {"id": "product_catalogue.pdf#2", "source": "product_catalogue.pdf", "title": "Product Catalogue", "page": 2,
     "text": "5. Hydraulic motors (HM series) Orbital hydraulic motors for conveyors. HM-250 HM-400"},
    {"id": "warranty_and_returns_policy.pdf#1", "source": "warranty_and_returns_policy.pdf",
     "title": "Warranty and Returns Policy", "page": 1,
     "text": "Trochoid pumps (TP series) 18 months. Hydraulic motors (HM series) 24 months."},
]
# every name the search box knows (the "names" query) and the net sales of the customers and products
NAMES = [
    ["customer", "3680", "Aurora Hydraulics Private Limited", "Chennai, Tamil Nadu", ""],
    ["customer", "32", "Aurora Fluid Power Limited", "Gurugram, Haryana", ""],
    ["customer", "14", "Kaveri Pumps Limited", "Coimbatore, Tamil Nadu", ""],
    ["customer", "15", "Tamil Traders", "Mumbai, Maharashtra", ""],              # "tamil" in the name, not the state
    *[["customer", str(100 + i), f"Filler Customer {i:02d}", "Pune, Maharashtra", ""] for i in range(12)],
    ["product", "45", "Hydraulic motor HM-346-1B", "FG00045", "Hydraulic motors"],
    ["product", "46", "Trochoid pump TP-120", "FG00046", "Trochoid pumps"],
    ["category", "Hydraulic motors", "Hydraulic motors", "577 items", ""],
    ["category", "Trochoid pumps", "Trochoid pumps", "30 items", ""],
    ["category", "GCI", "GCI", "12 items", ""],
    ["sales_person", "4", "Priya Iyer", "Sales Manager", ""],
    ["sales_person", "5", "Rekha Pillai", "Area Sales Executive", ""],
    ["sales_person", "6", "Rahul Verma", "", ""],
    ["state", "Tamil Nadu", "Tamil Nadu", "2 customers", ""],
    ["state", "Haryana", "Haryana", "1 customers", ""],
    ["state", "Maharashtra", "Maharashtra", "13 customers", ""],
    ["state", "Germany", "Germany", "1 customers", ""],
]
SALES = [["customer", AURORA, Decimal("29088275.00")], ["customer", 32, Decimal("2691000.00")],
         ["customer", 14, Decimal("5000000.00")], ["customer", 15, Decimal("100.00")],
         *[["customer", 100 + i, Decimal(1000 * (i + 1))] for i in range(12)],
         ["product", 45, Decimal("9000000.00")], ["product", 46, Decimal("100.00")]]


NAME_KINDS = ("customer", "product", "category", "sales_person", "state")


class FakeMySQL:
    """Answers each fixed query of knowledge_graph.py by its words and keeps every (sql, params) it was given."""

    def __init__(self):
        self.calls = []
        self.customers = 25            # how many customers a search finds
        self.unknown_product = Decimal("7125.00")
        self.down = False
        self.like_finds = True         # False: the plain (LIKE) search finds nothing
        self.bulk = 0                  # more customers in Madurai, Tamil Nadu, all with the same net sales

    def __call__(self, sql, params=(), max_rows=500):
        self.calls.append((sql, tuple(params)))
        if self.down:
            raise warehouse.WarehouseUnavailable("Cannot connect to MySQL as ai_reader: (2003) refused")
        return {"columns": [], "rows": self.rows(sql, list(params)), "truncated": False}

    def rows(self, sql, params):
        if "FROM dim_calendar WHERE financial_year" in sql:
            years = {"2627": (datetime.date(2026, 4, 1), datetime.date(2027, 3, 31)),
                     "2526": (datetime.date(2025, 4, 1), datetime.date(2026, 3, 31))}
            start, end = years.get(params[0], (None, None))
            return [[start, end, TODAY if start else None]]
        if sql.startswith("SELECT MIN(invoice_date), CURDATE()"):
            return [[datetime.date(2025, 12, 21), TODAY]]
        if "LIKE %s" in sql:  # the search
            if not self.like_finds:
                return []
            if "AS found" in sql:  # how many each type finds in all
                found = {"customer": self.customers, "product": 1}
                return [[kind, found.get(kind, 0)] for kind in NAME_KINDS if f"'{kind}' AS kind" in sql]
            limit = params[-1]  # every part has the same LIMIT %s (offset + limit)
            rows = [["customer", 3000 + i, f"Aurora Customer {i:02d}", "Chennai, Tamil Nadu", 1]
                    for i in range(self.customers)][:limit]
            if "'product' AS kind" in sql:
                rows += [["product", 45, "Hydraulic motor HM-346-1B", "FG00045", 0]]
            return rows
        if "AS more" in sql:  # every name, for type words and close spellings
            return [list(row) for row in NAMES] + [
                ["customer", str(200 + i), f"Bulk Customer {i // 2:02d}", "Madurai, Tamil Nadu", ""]  # pairs share a name
                for i in range(self.bulk)]
        if "GROUP BY f.customer_id)" in sql and " IN (" not in sql:  # the net sales of every customer and product
            return [list(row) for row in SALES] + [["customer", 200 + i, Decimal("777.00")] for i in range(self.bulk)]
        if "FROM dim_customers WHERE customer_id = %s" in sql:
            return [["Aurora Hydraulics Private Limited", "Chennai, Tamil Nadu", "Local Customer"]] if params[0] == AURORA else []
        if "FROM dim_products p WHERE p.product_id = %s" in sql:
            return [["Hydraulic motor HM-346-1B", "FG00045", "Hydraulic motors"]] if params[0] == 45 else []
        if sql.startswith("SELECT DISTINCT COALESCE"):  # every category (the PDF links)
            return [["GCI"], ["Hydraulic motors"], ["Trochoid pumps"]]
        if "FROM dim_products p WHERE p.product_id <> -1 AND" in sql:  # one category
            return [["Hydraulic motors", 577]] if params[0] == "Hydraulic motors" else []
        if sql.startswith("SELECT SUM(f.net_taxable_value), SUM(f.net_quantity)"):  # a node's totals
            counts = {"customer": [105, 2, 1, 2], "product": [5, 1], "category": [525]}
            kind = "customer" if "f.customer_id = %s" in sql else "product" if "f.product_id = %s" in sql else "category"
            unknown = {"customer": [self.unknown_product, Decimal("0")], "product": [Decimal("0")], "category": [Decimal("0")]}
            return [[Decimal("29088275.00"), Decimal("812.000"), 61, 140, datetime.date(2026, 4, 3),
                     datetime.date(2026, 11, 2), *counts[kind], *unknown[kind]]]
        if "AS edge" in sql:  # a node's links
            rows = []
            if "'BOUGHT' AS edge, 'product'" in sql:
                rows += [["BOUGHT", "product", 45, "Hydraulic motor HM-346-1B", "FG00045", Decimal("1250000.00"), Decimal("10.000"), 3],
                         ["BOUGHT", "product", 46, "Trochoid pump TP-120", "FG00046", Decimal("-5000.00"), Decimal("-1.000"), 0]]
            if "'HANDLED_BY'" in sql:
                rows += [["HANDLED_BY", "sales_person", 4, "Priya Iyer", "", Decimal("29000000.00"), Decimal("800"), 60]]
            if "'IN_STATE'" in sql:
                rows += [["IN_STATE", "state", "Tamil Nadu", "Tamil Nadu", "", Decimal("29088275.00"), Decimal("812"), 61]]
            if "'BUYS_AS'" in sql:
                rows += [["BUYS_AS", "sale_type", "Domestic", "Domestic", "", Decimal("29088275.00"), Decimal("812"), 61]]
            if "'BOUGHT' AS edge, 'customer'" in sql:
                rows += [["BOUGHT", "customer", AURORA, "Aurora Hydraulics Private Limited", "Tamil Nadu", Decimal("1250000.00"), Decimal("10"), 3]]
            if "'IN_CATEGORY' AS edge, 'category'" in sql:
                rows += [["IN_CATEGORY", "category", "Hydraulic motors", "Hydraulic motors", "", Decimal("1250000.00"), Decimal("10"), 3]]
            if "'IN_CATEGORY' AS edge, 'product'" in sql:
                rows += [["IN_CATEGORY", "product", 45, "Hydraulic motor HM-346-1B", "FG00045", Decimal("1250000.00"), Decimal("10"), 3]]
            return rows
        if "'category' AS kind" in sql and "'sale_type' AS kind" in sql:  # the small totals
            return [["category", "Hydraulic motors", Decimal("621565971.00")], ["state", "Tamil Nadu", Decimal("468912301.50")],
                    ["sales_person", 4, Decimal("180984185.50")], ["sale_type", "Domestic", Decimal("17808222897.48")]]
        if "AS kind" in sql and " IN (" in sql:  # the totals of the customers / products drawn
            return [["product", 45, Decimal("9000000.00")], ["product", 46, Decimal("100.00")],
                    ["customer", AURORA, Decimal("29088275.00")]]
        if sql.startswith("SELECT DISTINCT f.product_id"):  # similar: this customer's products
            return [[45], [46], [47], [48]] if params[0] == AURORA else []
        if "AS shared" in sql:  # similar: who else bought them
            return [[11, "Small Buyer Ltd", "Delhi", 1, Decimal("1000")], [12, "Twin Buyer Ltd", "Gujarat", 4, Decimal("900")],
                    [13, "Big Buyer Ltd", "Haryana", 4, Decimal("5000")]]
        if "COUNT(DISTINCT CASE WHEN f.product_id <> -1" in sql:  # similar: how many products each of them bought
            return [[11, 1, Decimal("1000")], [12, 4, Decimal("900")], [13, 40, Decimal("99000")]]
        raise AssertionError(f"unexpected SQL in the test: {sql[:120]}")


@pytest.fixture
def mysql(monkeypatch):
    fake = FakeMySQL()
    monkeypatch.setattr(warehouse, "run_select_params", fake)
    monkeypatch.setattr(kg, "document_pages", lambda: PAGES)
    kg.clear_cache()
    yield fake
    kg.clear_cache()


@pytest.fixture
def signed_in(client, user):
    client.force_login(user)
    return client


def get(client, name, **params):
    return api_get(client, name, data=params)


def sql_text(fake):
    return "\n".join(sql for sql, _ in fake.calls)


# ------------------------------------------------------------------ sign-in, methods, errors
@pytest.mark.parametrize("name", ["api_graph_search", "api_graph_node", "api_graph_similar"])
def test_a_stranger_must_sign_in_and_only_get_works(client, user, mysql, name):
    assert get(client, name, q="Aurora").status_code == 401
    client.force_login(user)
    r = api_post(client, name, {"q": "Aurora"})
    assert r.status_code == 405 and r.json()["detail"] == "Use GET here."
    assert mysql.calls == []


def test_a_normal_user_may_use_the_graph(signed_in, mysql):
    r = get(signed_in, "api_graph_search", q="Aurora")
    assert r.status_code == 200 and r.json()["results"]


def test_mysql_down_is_a_friendly_503_without_its_details(signed_in, mysql):
    mysql.down = True
    r = get(signed_in, "api_graph_search", q="Aurora")
    assert r.status_code == 503
    assert r.json()["detail"] == kg.MYSQL_DOWN and "ai_reader" not in r.content.decode()


# ------------------------------------------------------------------ search
def test_search_sends_the_typed_text_only_as_a_parameter(signed_in, mysql):
    typed = "x' OR 1=1 --"
    r = get(signed_in, "api_graph_search", q=typed)
    assert r.status_code == 200
    assert "OR 1=1" not in sql_text(mysql)                       # never in the SQL text ...
    params = [p for _, ps in mysql.calls for p in ps]
    assert f"%{typed}%" in params and f"{typed}%" in params      # ... only as the LIKE values
    assert "%s" in mysql.calls[0][0]


def test_search_needs_two_characters_and_runs_no_sql_before(signed_in, mysql):
    for q in ("", "a", "  b  "):
        r = get(signed_in, "api_graph_search", q=q)
        assert r.status_code == 400 and "at least 2 characters" in r.json()["detail"]
    assert mysql.calls == []


def test_search_treats_like_signs_as_plain_text(signed_in, mysql):
    get(signed_in, "api_graph_search", q="50%_x")
    params = [p for _, ps in mysql.calls for p in ps]
    assert "%50\\%\\_x%" in params


def test_search_mixes_the_types_and_gives_at_most_20(signed_in, mysql):
    body = get(signed_in, "api_graph_search", q="aur").json()
    ids = [n["id"] for n in body["results"]]
    assert len(ids) == 20 and len(set(ids)) == 20
    assert ids[:2] == ["customer:3000", "product:45"]            # one of each type in turn
    assert "customer:-1" not in ids
    for column in ("customer_id <> -1", "product_id <> -1", "sales_person_id <> -1"):
        assert column in sql_text(mysql)                         # the Unknown rows are never found


def test_search_by_type_and_a_bad_type(signed_in, mysql):
    body = get(signed_in, "api_graph_search", q="dom", types="sale_type").json()
    assert [n["id"] for n in body["results"]] == ["sale_type:Domestic"]
    assert mysql.calls == []                                     # sale types need no SQL
    body = get(signed_in, "api_graph_search", q="warranty", types="document").json()
    assert [n["id"] for n in body["results"]] == ["document:warranty_and_returns_policy.pdf#1"]
    r = get(signed_in, "api_graph_search", q="aur", types="customer,invoice")
    assert r.status_code == 400 and "Unknown node type" in r.json()["detail"]


# ------------------------------------------------------------------ the smarter search box (type words, close spellings)
def ids_of(body):
    return [n["id"] for n in body["results"]]


@pytest.mark.parametrize("q", ["customer", "Customers", "top customers", "  CUSTOMER  "])
def test_a_type_word_gives_the_top_10_customers_by_net_sales(signed_in, mysql, q):
    body = get(signed_in, "api_graph_search", q=q).json()
    assert body["match"] == "top" and body["match_type"] == "customer" and body["fuzzy"] is False
    assert ids_of(body)[:3] == ["customer:3680", "customer:14", "customer:32"]      # the biggest first
    assert len(body["results"]) == 10                                                 # 16 customers, 10 shown
    amounts = [n["amount"] for n in body["results"]]
    assert amounts == sorted(amounts, reverse=True) and body["results"][0]["amount_text"] == "2,90,88,275.00"
    assert body["results"][0]["sub"] == "Chennai, Tamil Nadu" and body["results"][0]["type_name"] == "Customer"
    assert body["note"] == "Top 10 of 16 customers by net sales (all data up to today) - type more to narrow"
    assert body["total"] == 16
    assert "LIKE" not in sql_text(mysql)                                              # no name search for a type word
    sales = next(sql for sql, _ in mysql.calls if "GROUP BY f.customer_id)" in sql)
    assert "SUM(f.net_taxable_value)" in sales and "f.invoice_date <= CURDATE()" in sales   # never after today


@pytest.mark.parametrize("q, first, count", [
    ("product", "product:45", 2), ("items", "product:45", 2),
    ("category", "category:Hydraulic motors", 3), ("categories", "category:Hydraulic motors", 3),
    ("sales person", "sales_person:4", 3), ("sales people", "sales_person:4", 3), ("salesperson", "sales_person:4", 3),
    ("sales reps", "sales_person:4", 3), ("reps", "sales_person:4", 3),
    ("state", "state:Tamil Nadu", 4), ("states", "state:Tamil Nadu", 4), ("countries", "state:Tamil Nadu", 4),
    ("regions", "state:Tamil Nadu", 4),
])
def test_every_type_word_and_its_plural(signed_in, mysql, q, first, count):
    body = get(signed_in, "api_graph_search", q=q).json()
    assert body["match"] == "top" and ids_of(body)[0] == first and len(body["results"]) == count
    assert len({n["type"] for n in body["results"]}) == 1


def test_all_categories_come_by_net_sales(signed_in, mysql):
    body = get(signed_in, "api_graph_search", q="categories").json()
    assert ids_of(body) == ["category:Hydraulic motors", "category:GCI", "category:Trochoid pumps"]  # then a-z
    assert body["results"][0]["amount_text"] == "62,15,65,971.00"


@pytest.mark.parametrize("q, expected", [
    ("customer tamil", ["customer:3680", "customer:14", "customer:15"]),     # the state, or the name
    ("customers in haryana", ["customer:32"]),                              # "in" is ignored
    ("customer aurora chennai", ["customer:3680"]),                          # every word: the name and the city
    ("sales person rekha", ["sales_person:5"]),
    ("product hydraulic", ["product:45"]),                                   # the description
    ("products of trochoid pumps", ["product:46"]),                          # the category
    ("item fg00046", ["product:46"]),                                        # the code
    ("state tamil", ["state:Tamil Nadu"]),
])
def test_a_type_word_with_text_filters_that_type(signed_in, mysql, q, expected):
    body = get(signed_in, "api_graph_search", q=q).json()
    assert body["match"] == "type" and ids_of(body) == expected and body["fuzzy"] is False
    assert "LIKE" not in sql_text(mysql)


@pytest.mark.parametrize("q, first", [
    ("aurra", "customer:3680"), ("rekka", "sales_person:5"), ("hydrolic", "category:Hydraulic motors"),
])
def test_a_small_spelling_mistake_gives_close_names_marked_fuzzy(signed_in, mysql, q, first):
    mysql.like_finds = False
    body = get(signed_in, "api_graph_search", q=q).json()
    assert body["fuzzy"] is True and body["match"] == "name" and ids_of(body)[0] == first
    assert all(n["fuzzy"] is True for n in body["results"]) and len(body["results"]) <= kg.FUZZY_LIMIT
    assert body["note"] == f'No exact match for "{q}" - did you mean one of these?'
    assert q not in sql_text(mysql)                                           # matched in Python, never SQL text


def test_close_names_mix_the_types(signed_in, mysql):
    mysql.like_finds = False
    body = get(signed_in, "api_graph_search", q="hydrolic").json()
    assert {"category:Hydraulic motors", "product:45", "customer:3680"} <= set(ids_of(body))  # Aurora Hydraulics


def test_a_type_word_with_a_misspelt_name(signed_in, mysql):
    body = get(signed_in, "api_graph_search", q="sales person rekka").json()
    assert body["match"] == "type" and ids_of(body) == ["sales_person:5"] and body["fuzzy"] is True
    body = get(signed_in, "api_graph_search", q="customers in tamill").json()   # the state (or name), misspelt
    assert ids_of(body) == ["customer:3680", "customer:14", "customer:15"] and body["fuzzy"] is True


def test_close_spellings_only_when_the_plain_search_finds_little(signed_in, mysql):
    body = get(signed_in, "api_graph_search", q="aurra").json()                # the fake LIKE finds 25 + 1
    assert body["fuzzy"] is False and not any(n.get("fuzzy") for n in body["results"])
    assert not any("AS more" in sql for sql, _ in mysql.calls)                 # the names are not even read


@pytest.mark.parametrize("q", ["zzzzqq", "xy", "x' OR 1=1 --", "customer qqqqzz"])
def test_nothing_found_is_still_an_empty_list(signed_in, mysql, q):
    mysql.like_finds = False
    r = get(signed_in, "api_graph_search", q=q)
    assert r.status_code == 200
    body = r.json()
    assert body["results"] == [] and body["fuzzy"] is False and body["q"] == q


def test_injection_text_with_a_type_word_stays_a_parameter(signed_in, mysql):
    mysql.like_finds = False
    typed = "customer x' OR 1=1 --"
    body = get(signed_in, "api_graph_search", q=typed).json()
    assert body["results"] == []                                               # no customer holds those words
    assert "OR 1=1" not in sql_text(mysql)                                     # never in the SQL text ...
    params = [p for _, ps in mysql.calls for p in ps]
    assert f"%{typed}%" in params                                              # ... only a LIKE value (the fallback)


def test_the_length_limit_and_the_type_filter(signed_in, mysql):
    body = get(signed_in, "api_graph_search", q="customer " + "a" * 300).json()
    assert len(body["q"]) == kg.MAX_SEARCH_CHARS
    mysql.calls.clear()
    body = get(signed_in, "api_graph_search", q="b" * 300).json()
    assert len(body["q"]) == kg.MAX_SEARCH_CHARS
    params = [p for _, ps in mysql.calls for p in ps]
    assert "%" + "b" * kg.MAX_SEARCH_CHARS + "%" in params
    mysql.like_finds = False
    body = get(signed_in, "api_graph_search", q="customer", types="product").json()
    assert body["match"] == "name" and body["results"] == []                   # not a type this search looks at


def test_the_names_and_sales_are_read_once_and_kept(signed_in, mysql):
    for q in ("customer", "product", "customer tamil", "sales people"):
        get(signed_in, "api_graph_search", q=q)
    assert sum("AS more" in sql for sql, _ in mysql.calls) == 1
    assert sum("GROUP BY f.customer_id)" in sql for sql, _ in mysql.calls) == 1
    kg.clear_cache()
    get(signed_in, "api_graph_search", q="customer")
    assert sum("AS more" in sql for sql, _ in mysql.calls) == 2


def test_the_type_words():
    assert kg._type_query("Customers in Tamil Nadu") == ("customer", ["tamil", "nadu"])
    assert kg._type_query("sales people") == ("sales_person", [])
    assert kg._type_query("Sales-person, Rekha") == ("sales_person", ["rekha"])
    assert kg._type_query("top states") == ("state", [])
    assert kg._type_query("Aurora customers") == (None, [])                     # only at the start
    assert kg._type_query("top") == (None, [])
    assert kg._type_query("salesforce") == (None, [])


# ------------------------------------------------------------------ how many in all, and "Show more" (05-Nov)
def pages(client, q, sizes=(None, 10, 10, 10, 10)):
    """The replies of a search page by page, as "Show more" asks for them (offset = what is shown already)."""
    bodies, shown = [], 0
    for size in sizes:
        params = {"q": q} if size is None else {"q": q, "offset": str(shown), "limit": str(size)}
        r = get(client, "api_graph_search", **params)
        assert r.status_code == 200, r.content
        bodies.append(r.json())
        shown += len(bodies[-1]["results"])
    return bodies


def test_a_type_word_says_how_many_there_are_in_all(signed_in, mysql):
    mysql.bulk = 40
    body = get(signed_in, "api_graph_search", q="customers").json()
    assert body["total"] == 56 and len(body["results"]) == 10
    assert body["note"] == "Top 10 of 56 customers by net sales (all data up to today) - type more to narrow"
    body = get(signed_in, "api_graph_search", q="categories").json()
    assert body["total"] == 3 and body["note"] == "All 3 categories by net sales (all data up to today)"
    assert get(signed_in, "api_graph_search", q="sales person rekha").json()["note"] == \
        '1 sales person matching "rekha" by net sales (all data up to today)'


def test_a_type_word_with_text_counts_the_matches(signed_in, mysql):
    body = get(signed_in, "api_graph_search", q="customer tamil").json()
    assert body["total"] == 3 and body["note"] == '3 customers matching "tamil" by net sales (all data up to today)'
    mysql.bulk = 40
    kg.clear_cache()
    body = get(signed_in, "api_graph_search", q="customers in tamil").json()
    assert body["total"] == 43 and len(body["results"]) == 10
    assert body["note"] == ('10 of 43 customers matching "tamil" by net sales (all data up to today)'
                            " - type more to narrow")


def test_a_name_search_counts_its_matches_with_the_same_like_parameter(signed_in, mysql):
    body = get(signed_in, "api_graph_search", q="aur").json()
    assert len(body["results"]) == 20 and body["total"] == 26                 # 25 customers + 1 product
    assert body["note"] == "20 of 26 matches - type more to narrow"
    counted = [(sql, ps) for sql, ps in mysql.calls if "AS found" in sql]
    assert len(counted) == 1 and counted[0][1] == ("%aur%",)                   # only the customers filled 20
    assert "COUNT(*)" in counted[0][0] and "LIKE %s" in counted[0][0]
    mysql.calls.clear()
    mysql.customers = 5
    body = get(signed_in, "api_graph_search", q="aur").json()
    assert body["total"] == 6 and body["note"] == "" and len(body["results"]) == 6
    assert not any("AS found" in sql for sql, _ in mysql.calls)               # all fit: no COUNT query at all


def test_type_word_pages_give_10_more_each_in_falling_net_sales_without_repeats(signed_in, mysql):
    mysql.bulk = 40                                                             # 40 with the same net sales: ties
    bodies = pages(signed_in, "customer")
    ids = [n["id"] for body in bodies for n in body["results"]]
    assert [len(body["results"]) for body in bodies] == [10, 10, 10, 10, 10]
    assert len(ids) == 50 and len(set(ids)) == 50                               # no repeats, nothing skipped
    amounts = [n["amount"] for body in bodies for n in body["results"]]
    assert amounts == sorted(amounts, reverse=True)
    bulk = [n for body in bodies for n in body["results"] if n["label"].startswith("Bulk")]
    assert [(n["label"], int(n["key"])) for n in bulk] == sorted((n["label"], int(n["key"])) for n in bulk)  # name, id
    assert bodies[1]["note"] == "Top 20 of 56 customers by net sales (all data up to today) - type more to narrow"
    assert all(body["total"] == 56 for body in bodies)
    assert get(signed_in, "api_graph_search", q="customer", offset="10", limit="10").json()["results"] == \
        bodies[1]["results"]                                                    # the same page again: the same nodes


def test_type_and_text_pages_and_name_search_pages_are_stable(signed_in, mysql):
    mysql.bulk = 40
    first, second = pages(signed_in, "customer tamil", (None, 10))
    ids = [n["id"] for n in first["results"] + second["results"]]
    assert len(ids) == 20 and len(set(ids)) == 20 and ids[:3] == ["customer:3680", "customer:14", "customer:200"]
    assert all(n["sub"].endswith("Tamil Nadu") or "Tamil" in n["label"] for n in first["results"] + second["results"])

    mysql.customers = 60
    bodies = pages(signed_in, "aur", (None, 10, 10, 10))
    ids = [n["id"] for body in bodies for n in body["results"]]
    assert ids == ["customer:3000", "product:45"] + [f"customer:{3001 + i}" for i in range(48)]  # the fair mix, kept
    assert all(body["total"] == 61 for body in bodies)
    assert bodies[-1]["note"] == "50 of 61 matches - type more to narrow"


def test_offset_and_limit_never_go_past_50(signed_in, mysql):
    mysql.bulk = 40
    body = get(signed_in, "api_graph_search", q="customer", offset="45", limit="10").json()
    assert len(body["results"]) == 5                                            # 45 + 10 is cut to the 50th
    mysql.customers = 80
    mysql.calls.clear()
    body = get(signed_in, "api_graph_search", q="aur", offset="40", limit="10").json()
    assert len(body["results"]) == 10 and body["total"] == 81
    limits = [ps[-1] for sql, ps in mysql.calls if "LIMIT %s" in sql]
    assert limits and max(limits) == kg.MAX_SEARCH_HITS                         # never more than 50 rows read
    body = get(signed_in, "api_graph_search", q="aur", offset="45").json()     # no limit: 20 would pass 50
    assert len(body["results"]) == 5


@pytest.mark.parametrize("params, words", [
    ({"offset": "50"}, "offset must be between 0 and 49"), ({"offset": "-1"}, "offset must be between 0 and 49"),
    ({"offset": "ten"}, "offset must be a whole number"), ({"offset": "1.5"}, "offset must be a whole number"),
    ({"limit": "0"}, "limit must be between 1 and 10"), ({"limit": "11"}, "limit must be between 1 and 10"),
    ({"limit": "20"}, "limit must be between 1 and 10"), ({"limit": "x' OR 1=1"}, "limit must be a whole number"),
])
def test_a_bad_offset_or_limit_is_a_400_before_any_sql(signed_in, mysql, params, words):
    r = get(signed_in, "api_graph_search", q="customer", **params)
    assert r.status_code == 400 and words in r.json()["detail"]
    assert mysql.calls == []


def test_close_spellings_have_no_total_and_no_pages(signed_in, mysql):
    mysql.like_finds = False
    body = get(signed_in, "api_graph_search", q="aurra").json()
    assert body["fuzzy"] is True and body["results"] and "total" not in body
    later = get(signed_in, "api_graph_search", q="aurra", offset="10", limit="10").json()
    assert later["results"] == [] and "total" not in later                      # nothing more to page through
    body = get(signed_in, "api_graph_search", q="sales person rekka").json()   # a type word, misspelt name
    assert body["fuzzy"] is True and "total" not in body
    assert get(signed_in, "api_graph_search", q="sales person rekka", offset="10").json()["results"] == []


def test_paging_and_counting_keep_the_typed_text_a_parameter(signed_in, mysql):
    mysql.customers = 60
    typed = "x' OR 1=1 --"
    body = get(signed_in, "api_graph_search", q=typed, offset="20", limit="10").json()
    assert len(body["results"]) == 10 and body["total"] == 61
    assert "OR 1=1" not in sql_text(mysql)                                     # not in the list nor the COUNT SQL
    counted = [ps for sql, ps in mysql.calls if "AS found" in sql]
    assert counted == [(f"%{typed}%",)]
    get(signed_in, "api_graph_search", q="50%_x", offset="10", limit="5")
    assert ("%50\\%\\_x%",) in [ps for sql, ps in mysql.calls if "AS found" in sql]   # escape_like kept


# ------------------------------------------------------------------ one node
def test_a_customer_node_with_its_neighbours_edges_and_numbers(signed_in, mysql):
    body = get(signed_in, "api_graph_node", type="customer", id=str(AURORA), fy="2627").json()
    node = body["node"]
    assert node["id"] == f"customer:{AURORA}" and node["label"] == "Aurora Hydraulics Private Limited"
    assert (node["amount"], node["amount_text"]) == (29088275.0, "2,90,88,275.00")   # Indian commas
    assert node["ask"] == "Top products bought by Aurora Hydraulics Private Limited in FY 2026-27 so far"
    assert body["period"]["text"] == "FY 2026-27 so far (01-Apr-2026 to 04-Nov-2026)"
    ids = {n["id"] for n in body["neighbours"]}
    assert {"product:45", "product:46", "sales_person:4", "state:Tamil Nadu", "sale_type:Domestic"} == ids
    sizes = {n["id"]: n["amount"] for n in body["neighbours"]}
    assert sizes["product:45"] == 9000000.0 and sizes["state:Tamil Nadu"] == 468912301.5   # the neighbour's own total
    bought = next(e for e in body["edges"] if e["target"] == "product:45")
    assert bought == {"id": f"customer:{AURORA}|BOUGHT|product:45", "source": f"customer:{AURORA}", "target": "product:45",
                      "type": "BOUGHT", "amount": 1250000.0, "amount_text": "12,50,000.00", "quantity": 10.0,
                      "quantity_text": "10", "invoices": 3, "invoices_text": "3"}
    credit = next(e for e in body["edges"] if e["target"] == "product:46")
    assert credit["amount_text"] == "-5,000.00"                  # a credit note larger than the sales stays negative
    groups = {g["edge"]: (g["shown"], g["total"]) for g in body["groups"]}
    assert groups["BOUGHT"] == (2, 105)


def test_the_fy_filter_counts_only_up_to_today(signed_in, mysql):
    get(signed_in, "api_graph_node", type="customer", id=f"customer:{AURORA}", fy="2627")
    facts = [(sql, params) for sql, params in mysql.calls if "FROM fact_invoice_lines f" in sql]
    assert facts
    for sql, params in facts:
        assert "f.invoice_date <= CURDATE()" in sql
        if "c.financial_year" in sql:
            assert "JOIN dim_calendar c ON c.date_id = f.invoice_date_id" in sql and "2627" in params
    mysql.calls.clear()
    body = get(signed_in, "api_graph_node", type="customer", id=str(AURORA)).json()        # all data
    assert body["period"]["text"] == "All data up to today (21-Dec-2025 to 04-Nov-2026)"
    assert "financial_year = %s AND f.invoice_date" not in sql_text(mysql)
    assert "f.invoice_date <= CURDATE()" in sql_text(mysql)


def test_a_finished_fy_is_not_so_far_and_a_strange_fy_is_refused(signed_in, mysql):
    body = get(signed_in, "api_graph_node", type="customer", id=str(AURORA), fy="2526").json()
    assert body["period"]["text"] == "FY 2025-26 (01-Apr-2025 to 31-Mar-2026)" and not body["period"]["so_far"]
    assert "in FY 2025-26" in body["node"]["ask"]
    for fy in ("26-27", "2628", "x"):
        assert get(signed_in, "api_graph_node", type="customer", id=str(AURORA), fy=fy).status_code == 400
    r = get(signed_in, "api_graph_node", type="customer", id=str(AURORA), fy="2324")      # not in the calendar
    assert r.status_code == 400 and "not in the calendar" in r.json()["detail"]


def test_the_neighbour_limit(signed_in, mysql):
    get(signed_in, "api_graph_node", type="customer", id=str(AURORA))
    links = next(params for sql, params in mysql.calls if "AS edge" in sql)
    assert links.count(kg.DEFAULT_LIMIT) == 4                    # the top 25 of each of the 4 edge types
    mysql.calls.clear()
    get(signed_in, "api_graph_node", type="customer", id=str(AURORA), limit="5")
    links = next(params for sql, params in mysql.calls if "AS edge" in sql)
    assert links.count(5) == 4
    for limit in ("0", "51", "many"):
        r = get(signed_in, "api_graph_node", type="customer", id=str(AURORA), limit=limit)
        assert r.status_code == 400 and "limit" in r.json()["detail"]


def test_bad_type_bad_id_and_unknown_node(signed_in, mysql):
    r = get(signed_in, "api_graph_node", type="invoice", id="1")
    assert r.status_code == 400 and "Unknown node type" in r.json()["detail"]
    assert get(signed_in, "api_graph_node", type="customer", id="abc").status_code == 400
    assert get(signed_in, "api_graph_node", type="customer", id="").status_code == 400
    r = get(signed_in, "api_graph_node", type="customer", id="999999")
    assert r.status_code == 404 and "No customer" in r.json()["detail"]
    assert get(signed_in, "api_graph_node", type="category", id="Pumps of Mars").status_code == 404
    assert get(signed_in, "api_graph_node", type="sale_type", id="Barter").status_code == 404
    assert get(signed_in, "api_graph_node", type="document", id="nothing.pdf#9").status_code == 404


def test_the_unknown_rows_are_never_nodes_but_their_amount_is_named(signed_in, mysql):
    r = get(signed_in, "api_graph_node", type="customer", id="-1")
    assert r.status_code == 404 and "Unknown customer (-1) is not drawn" in r.json()["detail"]
    assert get(signed_in, "api_graph_node", type="product", id="product:-1").status_code == 404
    assert get(signed_in, "api_graph_similar", customer_id="-1").status_code == 404
    mysql.calls.clear()
    body = get(signed_in, "api_graph_node", type="customer", id=str(AURORA)).json()
    assert "Unknown product (service lines, or items not in the master): 7,125.00 is in the total but not drawn." in body["notes"]
    links = next(sql for sql, _ in mysql.calls if "AS edge" in sql)
    assert "f.product_id <> -1" in links and "f.sales_person_id <> -1" in links
    assert all(not n["id"].endswith(":-1") for n in body["neighbours"])
    mysql.unknown_product = Decimal("0")
    kg.clear_cache()
    body = get(signed_in, "api_graph_node", type="customer", id=str(AURORA)).json()
    assert body["notes"] == []


def test_a_category_is_covered_by_the_pdf_pages_that_name_it(signed_in, mysql):
    body = get(signed_in, "api_graph_node", type="category", id="Hydraulic motors", fy="2627").json()
    covered = [e for e in body["edges"] if e["type"] == "COVERED_BY"]
    assert {e["target"] for e in covered} == {"document:product_catalogue.pdf#2", "document:warranty_and_returns_policy.pdf#1"}
    assert all(e["source"] == "category:Hydraulic motors" for e in covered)
    mentions = {e["target"]: e["mentions"] for e in covered}
    assert mentions["document:product_catalogue.pdf#2"] == 5     # 'Hydraulic motors' twice + 'HM' three times
    assert kg.document_links() == {
        "Hydraulic motors": [("product_catalogue.pdf#2", 5), ("warranty_and_returns_policy.pdf#1", 2)],
        "Trochoid pumps": [("warranty_and_returns_policy.pdf#1", 2)],
    }                                                            # GCI: no page names it


def test_a_product_is_covered_through_its_category(signed_in, mysql):
    body = get(signed_in, "api_graph_node", type="product", id="45").json()
    covered = [e for e in body["edges"] if e["type"] == "COVERED_BY"]
    assert covered and all(e["through"] == "Hydraulic motors" for e in covered)
    assert {"category:Hydraulic motors", f"customer:{AURORA}"} <= {n["id"] for n in body["neighbours"]}


def test_a_document_page_node(signed_in, mysql):
    body = get(signed_in, "api_graph_node", type="document", id="product_catalogue.pdf#2").json()
    assert body["node"]["label"] == "Product Catalogue, page 2" and body["node"]["text"].startswith("5. Hydraulic")
    assert [n["id"] for n in body["neighbours"]] == ["category:Hydraulic motors"]
    assert body["neighbours"][0]["amount_text"] == "62,15,65,971.00"


# ------------------------------------------------------------------ similar customers
def test_similar_customers_by_shared_products_then_overlap(signed_in, mysql):
    body = get(signed_in, "api_graph_similar", customer_id=str(AURORA), fy="2627").json()
    assert body["products"] == 4
    found = [(c["label"], c["shared_products"], c["score_text"]) for c in body["similar"]]
    assert found == [("Twin Buyer Ltd", 4, "100%"), ("Big Buyer Ltd", 4, "10%"), ("Small Buyer Ltd", 1, "25%")]
    assert body["similar"][0]["amount_text"] == "900.00"         # its own net sales (the node's size)
    assert {e["type"] for e in body["edges"]} == {"BUYS_LIKE"}
    assert body["edges"][0]["source"] == f"customer:{AURORA}"
    mine = next(sql for sql, _ in mysql.calls if sql.startswith("SELECT DISTINCT f.product_id"))
    assert "f.product_id <> -1" in mine                          # service lines are not "the same product"
    body = get(signed_in, "api_graph_similar", customer_id=str(AURORA), limit="1").json()
    assert len(body["similar"]) == 1
    assert get(signed_in, "api_graph_similar", customer_id=str(AURORA), limit="26").status_code == 400
    assert get(signed_in, "api_graph_similar", customer_id="999999").status_code == 404


# ------------------------------------------------------------------ numbers and the read-only session
def test_indian_commas():
    assert kg.indian(29088275) == "2,90,88,275.00"
    assert kg.indian(-1234567.891) == "-12,34,567.89"
    assert kg.indian(999) == "999.00" and kg.indian(1000) == "1,000.00" and kg.indian(100000, 0) == "1,00,000"
    assert kg.quantity_text(Decimal("2462.000")) == "2,462" and kg.quantity_text(Decimal("12.500")) == "12.5"


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.description = [("name",)]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.conn.executed.append((sql, params))

    def fetchmany(self, n):
        return [("row",)] * min(n, 4)


class FakeConnection:
    def __init__(self):
        self.executed = []
        self.closed = False

    def cursor(self):
        return FakeCursor(self)

    def close(self):
        self.closed = True


def test_run_select_params_uses_the_same_read_only_session_as_run_select(monkeypatch):
    made = []
    monkeypatch.setattr(warehouse, "connect", lambda: made.append(FakeConnection()) or made[-1])
    reply = warehouse.run_select_params("SELECT customer_name FROM dim_customers WHERE customer_name LIKE %s",
                                        ["%x' OR 1=1 --%"], max_rows=3)
    plain = warehouse.run_select("SELECT 1", max_rows=3)
    with_params, without = made
    assert with_params.executed[:2] == without.executed[:2] == [
        ("SET SESSION TRANSACTION READ ONLY", None), (f"SET SESSION MAX_EXECUTION_TIME = {warehouse.TIME_LIMIT_MS}", None)]
    assert with_params.executed[2] == ("SELECT customer_name FROM dim_customers WHERE customer_name LIKE %s",
                                       ("%x' OR 1=1 --%",))                 # pymysql quotes the value itself
    assert without.executed[2] == ("SELECT 1", None)                         # no parameters: '%' stays as it is
    assert with_params.closed and without.closed
    assert reply == plain == {"columns": ["name"], "rows": [["row"]] * 3, "truncated": True}


# ------------------------------------------------------------------ the real data (skipped without MySQL)
def test_real_mysql_search_node_and_similar(client, user):
    """With the real read-only MySQL: a customer found by search opens as a node with its links, the injection
    text finds nothing, and similar customers come back. No PDFs and no AI."""
    try:
        warehouse.allowed_tables()
    except Exception as exc:
        pytest.skip(f"read-only MySQL not available: {exc}")
    kg.clear_cache()
    client.force_login(user)
    found = get(client, "api_graph_search", q="Aurora", types="customer").json()["results"]
    assert found and all(n["type"] == "customer" and "aurora" in n["label"].lower() for n in found)
    assert get(client, "api_graph_search", q="x' OR 1=1 --", types="customer").json()["results"] == []
    top = get(client, "api_graph_search", q="customers").json()
    amounts = [n["amount"] for n in top["results"]]
    assert top["match"] == "top" and 0 < len(amounts) <= 10 and amounts == sorted(amounts, reverse=True)
    best =warehouse.run_select_params(
        "SELECT f.customer_id FROM fact_invoice_lines f JOIN dim_customers cu ON cu.customer_id = f.customer_id "
        "WHERE cu.customer_name LIKE %s AND f.product_id <> -1 AND f.invoice_date <= CURDATE() "
        "GROUP BY f.customer_id ORDER BY COUNT(*) DESC LIMIT 1", ["Aurora%"])["rows"][0][0]
    body = get(client, "api_graph_node", type="customer", id=str(best), limit="5").json()
    assert body["node"]["id"] == f"customer:{best}" and body["node"]["amount"] is not None
    assert body["period"]["to"] == datetime.date.today().strftime("%d-%b-%Y")
    bought = [e for e in body["edges"] if e["type"] == "BOUGHT"]
    assert 0 < len(bought) <= 5 and all(e["source"] == f"customer:{best}" for e in bought)
    assert not any(n["id"] in ("customer:-1", "product:-1", "sales_person:-1") for n in body["neighbours"])
    similar = get(client, "api_graph_similar", customer_id=str(best), limit="3").json()
    assert len(similar["similar"]) <= 3
    kg.clear_cache()
