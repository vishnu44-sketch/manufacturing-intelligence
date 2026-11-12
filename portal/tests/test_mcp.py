"""Ask NOP as an MCP server: the access key, the MCP protocol (Streamable HTTP) and the tools."""
import datetime
from decimal import Decimal

import pytest
from starlette.testclient import TestClient

from portal import mcp_server
from portal.lc import llm, pdfs
from portal.models import Question
from portal.rag import agent, store, warehouse
from portal.rag.store import VectorStoreUnavailable

KEY = "k" * 40
HEADERS = {"Authorization": f"Bearer {KEY}", "Accept": "application/json, text/event-stream",
           "Content-Type": "application/json"}
SCHEMA = {"fact_invoice_lines": ["invoice_date", "invoice_date_key", "customer_id", "net_taxable_value"],
          "dim_calendar": ["date_key", "nop_sales_month", "financial_year"],
          "dim_customers": ["customer_id", "customer_name", "state"]}


def rpc(method, params=None, id_=1):
    return {"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}}


def call_tool(test_client, name, arguments):
    response = test_client.post("/mcp", headers=HEADERS, json=rpc("tools/call", {"name": name, "arguments": arguments}))
    return response.json()["result"]


@pytest.fixture
def client(monkeypatch):
    """The default server: the caller's own LLM writes the SQL and the answer."""
    monkeypatch.delenv("MCP_USE_OUR_LLM", raising=False)
    with TestClient(mcp_server.build_app(key=KEY), base_url="http://127.0.0.1:8090") as test_client:
        yield test_client


@pytest.fixture
def our_llm_client(monkeypatch):
    """MCP_USE_OUR_LLM=on: ask_nop with Ask NOP's own Groq."""
    monkeypatch.setenv("MCP_USE_OUR_LLM", "on")
    with TestClient(mcp_server.build_app(key=KEY), base_url="http://127.0.0.1:8090") as test_client:
        yield test_client


class FakeMySQL:
    """ai_gold for run_sql: remembers every query; the invoice dates for the data-dates note."""

    def __init__(self, rows=None, error=None):
        self.rows, self.error, self.ran = rows or [], error, []

    def run_select(self, sql, max_rows=500):
        if "MIN(invoice_date)" in sql:
            return {"columns": ["first", "last"], "rows": [[datetime.date(2025, 12, 21), datetime.date(2027, 3, 20)]],
                    "truncated": False}
        self.ran.append(sql)
        if self.error:
            raise warehouse.QueryError(self.error)
        return {"columns": ["state", "net_sales_inr"], "rows": self.rows, "truncated": False}


@pytest.fixture
def mysql(monkeypatch):
    db = FakeMySQL(rows=[["Telangana", Decimal("4038014938.00")], ["Kerala", Decimal("5440490.00")]])
    monkeypatch.setattr(warehouse, "schema", lambda: SCHEMA)
    monkeypatch.setattr(warehouse, "run_select", db.run_select)
    monkeypatch.setattr(mcp_server, "today", lambda: datetime.date(2026, 11, 2))  # FY 2026-27 is not over
    return db


@pytest.mark.parametrize("authorization", [None, "Bearer wrong-key", f"Basic {KEY}", KEY])
def test_without_the_right_key_nothing_is_answered(client, authorization):
    headers = {k: v for k, v in HEADERS.items() if k != "Authorization"}
    if authorization:
        headers["Authorization"] = authorization
    response = client.post("/mcp", json=rpc("tools/list"), headers=headers)
    assert response.status_code == 401 and response.json() == {"error": "missing or wrong access key"}


def test_the_tools_are_listed(client):
    """30-Oct: by default the caller's LLM does the work - ask_nop (our Groq) is not offered."""
    response = client.post("/mcp", json=rpc("tools/list"), headers=HEADERS)
    assert response.status_code == 200
    tools = {tool["name"]: tool for tool in response.json()["result"]["tools"]}
    assert set(tools) == {"search_notes", "get_schema", "run_sql", "nop_example_questions", "search_documents"}
    assert tools["search_notes"]["inputSchema"]["required"] == ["question"]
    assert tools["run_sql"]["inputSchema"]["required"] == ["sql"]


def test_with_our_llm_on_ask_nop_is_offered(our_llm_client):
    response = our_llm_client.post("/mcp", json=rpc("tools/list"), headers=HEADERS)
    tools = {tool["name"]: tool for tool in response.json()["result"]["tools"]}
    assert set(tools) == {"ask_nop", "nop_example_questions"}
    assert tools["ask_nop"]["inputSchema"]["required"] == ["question"]


@pytest.mark.django_db
def test_ask_nop_answers_through_mcp(our_llm_client, monkeypatch):
    client = our_llm_client
    asked = []

    def fake_ask(question, user, context=None):
        asked.append((question, user.username))
        return agent.AskResult(text=question, status="ok", answer="Telangana bought the most.", sql="SELECT 1",
                               columns=["state", "net_sales_inr", "invoice_date"],
                               rows=[["Telangana", Decimal("4038014938.00"), None]] * 60)
    monkeypatch.setattr(agent, "ask", fake_ask)

    response = client.post("/mcp", headers=HEADERS, json=rpc("tools/call", {
        "name": "ask_nop", "arguments": {"question": "Which state bought the most in FY 2026-27?"}}))

    result = response.json()["result"]
    assert not result.get("isError")
    answer = result["structuredContent"]
    assert answer["status"] == "ok" and answer["answer"] == "Telangana bought the most."
    assert answer["rows"][0] == ["Telangana", "4,038,014,938.00", "-"]          # formatted like the Ask page
    assert answer["row_count"] == 60 and answer["rows_shown"] == mcp_server.ROWS_FOR_CALLER
    assert asked == [("Which state bought the most in FY 2026-27?", mcp_server.MCP_USERNAME)]


@pytest.mark.django_db
def test_the_mcp_user_cannot_log_in():
    user = mcp_server.service_user()
    assert user.username == "mcp" and not user.has_usable_password()
    assert mcp_server.service_user().pk == user.pk                             # made only once


def test_example_questions_come_from_the_docs():
    questions = mcp_server.nop_example_questions()
    assert len(questions) == 40 and "Which items are below their minimum inventory level right now?" in questions


@pytest.mark.parametrize("key", ["", "short"])
def test_the_server_does_not_start_without_a_safe_key(monkeypatch, key):
    monkeypatch.setenv("MCP_ACCESS_KEY", key)
    monkeypatch.delenv("MCP_AUTH", raising=False)
    with pytest.raises(ValueError, match="Set MCP_ACCESS_KEY"):
        mcp_server.build_app()


def test_with_mcp_auth_off_the_link_alone_is_enough(monkeypatch):
    """27-Oct (Vishnu): MCP_AUTH=off in .env - no key needed, also when no key is set."""
    monkeypatch.setenv("MCP_AUTH", "off")
    monkeypatch.setenv("MCP_ACCESS_KEY", "")
    monkeypatch.delenv("MCP_USE_OUR_LLM", raising=False)
    headers = {k: v for k, v in HEADERS.items() if k != "Authorization"}
    with TestClient(mcp_server.build_app(), base_url="http://127.0.0.1:8090") as open_client:
        response = open_client.post("/mcp", json=rpc("tools/list"), headers=headers)
    assert response.status_code == 200 and len(response.json()["result"]["tools"]) == 5


@pytest.mark.django_db
def test_a_real_question_is_saved_in_the_history(monkeypatch):
    """The tool runs the normal Ask NOP flow: the question is saved like one from the Ask page."""
    monkeypatch.setattr(agent, "_answer", lambda result, context, user=None: setattr(result, "status", "refused")
                        or setattr(result, "answer", agent.REFUSAL_ANSWER))
    answer = mcp_server.ask_nop("delete all credit notes")
    assert answer["status"] == "refused" and answer["rows"] == []
    saved = Question.objects.get()
    assert saved.user.username == "mcp" and saved.text == "delete all credit notes"


# ------------------------------------------------------------------ the caller's own LLM (30-Oct)
def test_search_notes_gives_the_rules_the_notes_and_the_columns(client, mysql, monkeypatch):
    hits = [{"text": "Net sales = SUM(net_taxable_value).", "source": "rules.md", "heading": "Net sales",
             "kind": "rule", "score": 0.81}]
    searched = []
    monkeypatch.setattr(mcp_server, "search", lambda question, top_k: searched.append((question, top_k)) or hits)

    result = call_tool(client, "search_notes", {"question": "net sales by state in Aug 2026"})

    assert not result.get("isError")
    notes = result["structuredContent"]
    assert searched == [("net sales by state in Aug 2026", agent.TOP_K)]
    assert notes["notes"] == [{"heading": "Net sales", "kind": "rule", "text": "Net sales = SUM(net_taxable_value)."}]
    assert "fact_invoice_lines: invoice_date" in notes["schema"]
    assert "Rules for the SQL:" in notes["sql_rules"] and "NOT in ai_gold" in notes["sql_rules"]
    assert "Reply in exactly one" not in notes["sql_rules"]                   # Groq's reply format is not for them
    assert notes["answer_rules"].startswith("- Use ONLY numbers")
    assert "run_sql" in notes["how_to_use"] and notes["today"]


def test_get_schema_gives_every_table_or_the_named_ones(mysql):
    assert mcp_server.get_schema().count("\n") == len(SCHEMA) - 1
    assert mcp_server.get_schema(["DIM_CUSTOMERS"]) == "dim_customers: customer_id, customer_name, state"


def test_get_schema_names_the_tables_when_one_does_not_exist(client, mysql):
    result = call_tool(client, "get_schema", {"tables": ["profit"]})
    assert result["isError"] and "fact_invoice_lines" in result["content"][0]["text"]


def test_run_sql_runs_a_checked_select_and_gives_rows_and_notes(client, mysql):
    sql = ("SELECT cu.state, ROUND(SUM(il.net_taxable_value), 2) AS net_sales_inr FROM fact_invoice_lines il "
           "JOIN dim_calendar c ON c.date_key = il.invoice_date_key JOIN dim_customers cu ON cu.customer_id = "
           "il.customer_id WHERE c.nop_sales_month = 'Aug 2026' GROUP BY cu.state ORDER BY net_sales_inr DESC")

    result = call_tool(client, "run_sql", {"sql": f"```sql\n{sql}\n```"})

    assert not result.get("isError")
    answer = result["structuredContent"]
    assert answer["check_first"] == [] and answer["must_tell_user"] == []
    assert answer["columns"] == ["state", "net_sales_inr"]                      # no note_for_user column needed
    assert answer["rows"] == [["Telangana", "4,038,014,938.00"], ["Kerala", "5,440,490.00"]]
    assert answer["row_count"] == 2 and answer["rows_shown"] == 2
    assert "LIMIT 500" in answer["sql"] and mysql.ran == [answer["sql"]]       # the guard's SQL is what ran
    assert any("NOP sales month Aug 2026 = 21-Jul-2026 to 20-Aug-2026" in note for note in answer["notes"])


@pytest.mark.parametrize("sql", ["DELETE FROM fact_invoice_lines",
                                 "SELECT 1; DROP TABLE dim_customers",
                                 "SELECT * FROM mysql.user",
                                 "SELECT * FROM nop_portal.auth_user"])
def test_run_sql_refuses_anything_but_one_select_on_the_nop_tables(client, mysql, sql):
    """An error, not a field: a chatbot that shows its LLM only a preview of the rows always shows an error."""
    result = call_tool(client, "run_sql", {"sql": sql})
    assert result["isError"] and "The SQL guard refused the query" in result["content"][0]["text"]
    assert mysql.ran == []                                                     # nothing reached MySQL


def test_run_sql_sends_back_the_mysql_error_to_fix(client, mysql):
    mysql.error = "Unknown column 'il.amount' in 'field list'"
    result = call_tool(client, "run_sql", {"sql": "SELECT il.amount FROM fact_invoice_lines il"})
    assert result["isError"] and "Unknown column 'il.amount'" in result["content"][0]["text"]


QUARTER_OVER_ALL_YEARS = ("SELECT c.fiscal_quarter, SUM(il.net_taxable_value) AS net_sales_inr FROM fact_invoice_lines il "
                          "JOIN dim_calendar c ON c.date_key = il.invoice_date_key GROUP BY c.fiscal_quarter")


def test_a_known_mistake_is_an_error_and_nothing_runs(client, mysql):
    result = call_tool(client, "run_sql", {"sql": QUARTER_OVER_ALL_YEARS})
    text = result["content"][0]["text"]
    assert result["isError"] and mysql.ran == []
    assert "Fix the SQL and call run_sql again (no rows were sent):\n1. " in text and "fiscal_quarter" in text
    assert "checked=true" in text


def test_checked_runs_it_anyway_and_still_lists_the_mistake(client, mysql):
    """Our check can be wrong: the caller's LLM can still run a query it is sure of."""
    answer = call_tool(client, "run_sql", {"sql": QUARTER_OVER_ALL_YEARS, "checked": True})["structuredContent"]
    assert len(mysql.ran) == 1 and answer["row_count"] == 2
    assert len(answer["check_first"]) == 1 and "fiscal_quarter" in answer["check_first"][0]


THEIR_KPI_SQL = ("SELECT \n  ROUND(SUM(il.net_taxable_value),2) AS net_sales_inr,\n  COUNT(DISTINCT il.invoice_number) "
                 "AS num_invoices,\n  COUNT(DISTINCT il.customer_id) AS num_customers\nFROM fact_invoice_lines il\n"
                 "JOIN dim_calendar c ON c.date_id = il.invoice_date_id\nWHERE c.financial_year = '2627';")


def test_the_callers_kpi_query_gets_its_three_mistakes_pointed_out(client, mysql):
    """02-Nov: the other person's chatbot ran this for 'net sales, invoices and active customers in FY 2026-27'
    and answered 33,078 invoices / 4,197 customers for the whole FY - with rows dated after today."""
    result = call_tool(client, "run_sql", {"sql": THEIR_KPI_SQL})
    assert result["isError"] and mysql.ran == []
    assert result["content"][0]["text"].endswith(mcp_server.fix_first([
        mcp_server.INVOICE_COUNT_PROBLEM, mcp_server.UNKNOWN_CUSTOMER_PROBLEM,
        mcp_server.PERIOD_NOT_OVER_PROBLEM.format(label="Financial year 2627 (FY 2026-27)",
                                                  today=datetime.date(2026, 11, 2))]))
    assert "02-Nov-2026" in result["content"][0]["text"] and "CURDATE()" in result["content"][0]["text"]

    answer = call_tool(client, "run_sql", {"sql": THEIR_KPI_SQL, "checked": True})["structuredContent"]
    assert answer["must_tell_user"][-1] == (
        "These numbers include data dated after today (02-Nov-2026) for Financial year 2627 (FY 2026-27): "
        "say so, or run the query again up to today.")
    assert answer["columns"][-1] == "note_for_user"                            # in the rows too: a preview shows it
    assert answer["rows"][0][-1] == " ".join(answer["must_tell_user"]) and answer["rows"][1][-1] == ""


THEIR_SECOND_KPI_SQL = (  # 02-Nov, the same question again: credit notes flipped, invoice LINES counted
    "SELECT\n  ROUND(SUM(CASE WHEN il.document_type = 'INVOICE' THEN il.net_taxable_value\n"
    "                WHEN il.document_type = 'CREDIT_NOTE' THEN -il.net_taxable_value\n"
    "                WHEN il.document_type = 'DEBIT_NOTE' THEN il.net_taxable_value\n           END), 2) AS net_sales_inr,\n"
    "  COUNT(CASE WHEN il.document_type = 'INVOICE' THEN 1 END) AS invoice_count,\n"
    "  COUNT(DISTINCT CASE WHEN il.customer_id > 0 THEN il.customer_id END) AS active_customers\n"
    "FROM fact_invoice_lines il\nJOIN dim_calendar c ON c.date_id = il.invoice_date_id\nWHERE c.financial_year = '2627';")


def test_flipped_credit_notes_and_counted_invoice_lines_are_errors(client, mysql):
    """Their answer: INR 21,546,976,297.22 (credit notes added, not taken off) and 100,293 'invoices' (lines)."""
    result = call_tool(client, "run_sql", {"sql": THEIR_SECOND_KPI_SQL})
    assert result["isError"] and mysql.ran == []
    assert result["content"][0]["text"].endswith(mcp_server.fix_first([
        mcp_server.CREDIT_SIGN_PROBLEM, mcp_server.INVOICE_LINES_PROBLEM,
        mcp_server.PERIOD_NOT_OVER_PROBLEM.format(label="Financial year 2627 (FY 2026-27)",
                                                  today=datetime.date(2026, 11, 2))]))


@pytest.mark.parametrize("sql, flipped, lines", [
    ("SELECT SUM(il.net_taxable_value) - SUM(CASE WHEN il.document_type = 'CREDIT_NOTE' "
     "THEN il.net_taxable_value END) AS x FROM fact_invoice_lines il", True, False),
    ("SELECT SUM(ABS(il.net_taxable_value)) AS x FROM fact_invoice_lines il", True, False),
    ("SELECT COUNT(*) AS invoices FROM fact_invoice_lines il WHERE il.document_type = 'INVOICE'", False, True),
    ("SELECT COUNT(il.invoice_number) AS n FROM fact_invoice_lines il", False, True),
    ("SELECT COUNT(*) AS invoice_lines FROM fact_invoice_lines il", False, False),     # lines on purpose
    ("SELECT ROUND(SUM(il.net_taxable_value), 2) AS net, COUNT(DISTINCT il.invoice_number) AS n "
     "FROM fact_invoice_lines il WHERE il.document_type = 'INVOICE'", False, False),
])
def test_the_credit_sign_and_invoice_line_checks(sql, flipped, lines):
    assert mcp_server.flips_credit_notes(sql) is flipped and mcp_server.counts_invoice_lines(sql) is lines


def test_the_right_kpi_query_runs_without_warnings(client, mysql):
    sql = ("SELECT ROUND(SUM(il.net_taxable_value), 2) AS net_sales_inr, "
           "COUNT(DISTINCT CASE WHEN il.document_type = 'INVOICE' THEN il.invoice_number END) AS num_invoices, "
           "COUNT(DISTINCT CASE WHEN il.customer_id <> -1 THEN il.customer_id END) AS num_customers "
           "FROM fact_invoice_lines il JOIN dim_calendar c ON c.date_id = il.invoice_date_id "
           "WHERE c.financial_year = '2627' AND il.invoice_date <= CURDATE()")
    answer = call_tool(client, "run_sql", {"sql": sql})["structuredContent"]
    assert answer["check_first"] == []
    assert answer["must_tell_user"] == []        # "data only up to 20-Mar-2027" is no news for a FY counted to today


@pytest.mark.parametrize("sql", [
    "SELECT COUNT(DISTINCT invoice_number) AS n FROM fact_invoice_lines WHERE document_type = 'INVOICE'",
    "SELECT COUNT(DISTINCT customer_id) AS n FROM fact_invoice_lines WHERE customer_id <> -1",
    "SELECT COUNT(DISTINCT so_number, financial_year) AS n FROM fact_sales_order_lines",
])
def test_counts_with_their_filter_in_the_where_are_fine(sql):
    assert not mcp_server.counts_all_documents(sql) and not mcp_server.counts_the_unknown_customer(sql)


def test_a_finished_period_is_not_called_unfinished(mysql):
    assert mcp_server.periods_not_over("SELECT 1 FROM dim_calendar c WHERE c.financial_year = '2526'") == []
    assert mcp_server.periods_not_over("SELECT 1 FROM dim_calendar c WHERE c.nop_sales_month = 'Nov 2026'") == [
        "NOP sales month Nov 2026"]


def test_the_period_check_is_ask_nops_own(monkeypatch, mysql):
    """03-Nov: one check for both - Ask NOP's SQL step and run_sql - with the MCP server's today()."""
    asked = []
    monkeypatch.setattr(agent, "periods_not_over", lambda sql, now=None: asked.append((sql, now)) or ["FY x"])
    assert mcp_server.periods_not_over("SELECT 1") == ["FY x"]
    assert asked == [("SELECT 1", datetime.date(2026, 11, 2))]
    assert mcp_server.PERIOD_NOT_OVER_PROBLEM is agent.PERIOD_NOT_OVER_PROBLEM


def test_the_real_data_dates_must_be_told(client, mysql):
    """FY 2025-26 starts on 01-Apr-2025, but the invoice data only on 21-Dec-2025 - their chatbot left it out."""
    sql = ("SELECT il.sale_type, ROUND(SUM(il.net_taxable_value), 2) AS net_sales_inr FROM fact_invoice_lines il "
           "JOIN dim_calendar c ON c.date_id = il.invoice_date_id WHERE c.financial_year = '2526' GROUP BY il.sale_type")
    answer = call_tool(client, "run_sql", {"sql": sql})["structuredContent"]
    assert len(answer["must_tell_user"]) == 1
    assert "the invoice data covers only 21-Dec-2025 to 31-Mar-2026" in answer["must_tell_user"][0]
    assert answer["columns"] == ["state", "net_sales_inr", "note_for_user"]
    assert answer["rows"][0][2] == answer["must_tell_user"][0]


def test_run_sql_tells_the_rules_that_are_often_missed(client):
    tools = {tool["name"]: tool for tool in client.post("/mcp", json=rpc("tools/list"), headers=HEADERS)
             .json()["result"]["tools"]}
    description = tools["run_sql"]["description"]
    assert "share_pct = ROUND(100 * SUM(x) / SUM(SUM(x)) OVER (), 2)" in description
    assert "document_type = 'INVOICE'" in description and "customer_id = -1" in description
    assert "CURDATE()" in description and "note_for_user" in description
    assert "never flip their sign" in description and "not COUNT(*) or rows" in description
    assert "checked=true" in description and set(tools["run_sql"]["inputSchema"]["required"]) == {"sql"}
    assert "never flip their sign" in tools["search_notes"]["description"]


def test_mysql_down_gives_a_friendly_message(client, monkeypatch):
    def down():
        raise warehouse.WarehouseUnavailable("connection refused")
    monkeypatch.setattr(warehouse, "allowed_tables", down)
    result = call_tool(client, "run_sql", {"sql": "SELECT 1"})
    assert result["isError"] and result["content"][0]["text"].endswith(agent.DB_DOWN)


def test_the_callers_tools_never_use_our_groq(client, mysql, monkeypatch):
    """The point of 30-Oct: no Groq call (and no Groq token) of Ask NOP for the caller's questions."""
    def no_groq(*args, **kwargs):
        raise AssertionError("Groq was used")
    monkeypatch.setattr(llm, "make_llm", no_groq)
    monkeypatch.setattr(mcp_server, "search", lambda question, top_k: [])
    assert not call_tool(client, "search_notes", {"question": "net sales by state"}).get("isError")
    assert not call_tool(client, "run_sql", {"sql": "SELECT state FROM dim_customers"}).get("isError")
    monkeypatch.setattr(mcp_server, "search_pdfs", lambda question, k: PDF_HITS)
    assert not call_tool(client, "search_documents", {"question": "warranty on gear pumps"}).get("isError")


def test_run_sql_says_a_limited_result_is_not_the_full_list(client, mysql):
    """03-Nov: the top N rows of a LIMIT N are not all the data - the caller's LLM gets the same note as ours."""
    sql = ("SELECT cu.state, ROUND(SUM(il.net_taxable_value), 2) AS net_sales_inr FROM fact_invoice_lines il "
           "JOIN dim_calendar c ON c.date_key = il.invoice_date_key JOIN dim_customers cu ON cu.customer_id = "
           "il.customer_id WHERE c.nop_sales_month = 'Aug 2026' GROUP BY cu.state ORDER BY net_sales_inr DESC LIMIT 2")
    answer = call_tool(client, "run_sql", {"sql": sql})["structuredContent"]
    assert any(note.startswith("Rows: the SQL asked for only the first 2 rows (LIMIT 2)") for note in answer["notes"])


# ------------------------------------------------------------------ the company PDFs (03-Nov)
PDF_HITS = [{"text": "Gear pumps carry a warranty of 18 months from the invoice date.", "source":
             "warranty_and_returns_policy.pdf", "title": "Warranty and Returns Policy", "page": 1, "score": 0.83},
            {"text": "Wear parts (seals, gaskets) are not covered.", "source": "warranty_and_returns_policy.pdf",
             "title": "Warranty and Returns Policy", "page": 2, "score": 0.71}]


def test_search_documents_is_listed_with_its_how_to(client):
    tools = {tool["name"]: tool for tool in client.post("/mcp", json=rpc("tools/list"), headers=HEADERS)
             .json()["result"]["tools"]}
    tool = tools["search_documents"]
    assert tool["inputSchema"]["required"] == ["question"] and "k" in tool["inputSchema"]["properties"]
    assert "warranty" in tool["description"] and "page" in tool["description"]
    assert "search_documents" in mcp_server.INSTRUCTIONS                       # their chatbot always sees this


def test_search_documents_gives_the_closest_pieces_with_their_page(client, monkeypatch):
    searched = []
    monkeypatch.setattr(mcp_server, "search_pdfs", lambda question, k: searched.append((question, k)) or PDF_HITS)

    result = call_tool(client, "search_documents", {"question": "How long is the warranty on gear pumps?", "k": 50})

    assert not result.get("isError")
    found = result["structuredContent"]
    assert searched == [("How long is the warranty on gear pumps?", mcp_server.MAX_DOCUMENT_PIECES)]  # at most 8
    assert found["pieces"][0] == {"title": "Warranty and Returns Policy", "file": "warranty_and_returns_policy.pdf",
                                  "page": 1, "text": PDF_HITS[0]["text"], "score": 0.83}
    assert [piece["page"] for piece in found["pieces"]] == [1, 2]
    assert "Answer ONLY from these pieces" in found["how_to_use"] and "page" in found["how_to_use"]
    assert "do not have it" in found["how_to_use"]


def test_search_documents_asks_4_pieces_by_default(monkeypatch):
    searched = []
    monkeypatch.setattr(mcp_server, "search_pdfs", lambda question, k: searched.append(k) or PDF_HITS)
    mcp_server.search_documents("warranty?")
    assert searched == [4]


@pytest.mark.parametrize("problem, message", [
    (RuntimeError(pdfs.PDF_STORE_EMPTY), mcp_server.DOCUMENTS_EMPTY),          # ingest_pdfs never ran
    (VectorStoreUnavailable(store.QDRANT_DOWN), store.QDRANT_DOWN),             # Qdrant is down
    (None, mcp_server.DOCUMENTS_EMPTY),                                          # the collection holds nothing
])
def test_search_documents_problems_are_friendly_errors(client, monkeypatch, problem, message):
    def fake_search(question, k):
        if problem:
            raise problem
        return []
    monkeypatch.setattr(mcp_server, "search_pdfs", fake_search)
    result = call_tool(client, "search_documents", {"question": "warranty on gear pumps"})
    assert result["isError"] and result["content"][0]["text"].endswith(message)


def test_search_documents_needs_a_question(client):
    result = call_tool(client, "search_documents", {"question": "  "})
    assert result["isError"] and "Give the user's question." in result["content"][0]["text"]
