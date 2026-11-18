"""run_ml.py - the ONE command of the ML step: read ss_gold, train every scenario, write the ml_* tables.

    venv\\Scripts\\python.exe ml\\run_ml.py          (laptop, from the repo folder)
    python manage.py run_ml                          (the same through Django)
    docker compose --profile load run --rm --entrypoint python loader ml/run_ml.py   (office Docker, DEPLOY.md)

1. Reads the company data from ss_gold with the ADMIN login of .env (the same settings as loader/load_gold.py):
   invoice lines, sales order lines, customers, products, the calendar and the newest stock report. Only data
   dated up to data_to = the newest invoice date (never after today) is used: the models work 'as of the newest
   data', not as of today.
2. Each scenario (forecast, customer_risk, segments, invoice_alerts, product_pairs, stock_runout) writes its
   training data as CSV into ml_inputdata/ and trains its model.
3. Only when EVERY scenario worked, the result tables are written: DROP + CREATE + INSERT of the ml_* tables,
   only inside ss_gold (db.check_target refuses anything else), plus one line per scenario in ml_run_log.
4. Prints a short summary per scenario (rows, key number, seconds).

--dry-run trains and writes the CSV files but writes nothing into MySQL.
"""
import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

if __package__ in (None, ""):            # run as a file (python ml/run_ml.py): make "import ml" work
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ml import customer_risk, db, forecast, invoice_alerts, product_pairs, segments, stock_runout  # noqa: E402

SCENARIOS = [forecast, customer_risk, segments, invoice_alerts, product_pairs, stock_runout]


def read_inputs(engine):
    """Everything the scenarios need from ss_gold, as DataFrames (+ data_from / data_to as dates)."""
    days = db.read_frame(engine, "SELECT MIN(invoice_date) AS data_from, MAX(invoice_date) AS data_to "
                                 "FROM fact_invoice_lines WHERE invoice_date <= CURDATE()")
    if days.empty or days["data_to"].iloc[0] is None:
        raise SystemExit("ss_gold has no invoice lines dated up to today - load the data first (loader/load_gold.py).")
    data_from, data_to = db.as_date(days["data_from"].iloc[0]), db.as_date(days["data_to"].iloc[0])
    params = {"data_to": data_to}
    inputs = {
        "data_from": data_from,
        "data_to": data_to,
        "calendar": db.read_frame(engine, """
            SELECT full_date, sales_month, sales_period_start, sales_period_end
            FROM dim_calendar WHERE date_id <> -1"""),
        "lines": db.read_frame(engine, """
            SELECT invoice_line_id, document_type, invoice_number, note_number, invoice_date, customer_id,
                   product_id, so_number, so_date, quantity, unit_price, taxable_value, net_quantity,
                   net_taxable_value, original_invoice_number, issue_reason
            FROM fact_invoice_lines WHERE invoice_date <= :data_to""", params),
        "orders": db.read_frame(engine, """
            SELECT so_number, order_date, customer_id, product_id, status
            FROM fact_sales_order_lines WHERE order_date <= :data_to""", params),
        "customers": db.read_frame(engine, """
            SELECT customer_id, customer_code, customer_name FROM dim_customers"""),
        "products": db.read_frame(engine, """
            SELECT product_id, product_code, product_description, item_group FROM dim_products"""),
        "stock": db.read_frame(engine, """
            SELECT sl.report_date, sl.product_id, sl.src_product_code, sl.item_description,
                   sl.cumulative_qty AS stock_qty
            FROM fact_stock_ledger sl
            JOIN dim_stock_movement_types m ON m.movement_type_id = sl.movement_type_id
            WHERE m.movement_type = 'Closing balance'
              AND sl.report_date = (SELECT MAX(report_date) FROM fact_stock_ledger WHERE report_date <= CURDATE())"""),
    }
    return inputs


def run(dry_run=False, out=print):
    """Train every scenario and (unless dry_run) write the results. Returns the summary per scenario."""
    started = time.time()
    engine = db.gold_engine()
    try:
        inputs = read_inputs(engine)
        data_to = inputs["data_to"]
        run_at = datetime.now().replace(microsecond=0)
        out(f"Read ss_gold in {time.time() - started:.1f} s: {len(inputs['lines']):,} invoice lines, "
            f"{len(inputs['orders']):,} order lines, data {inputs['data_from']:%d-%b-%Y} .. {data_to:%d-%b-%Y} "
            f"(the models work as of {data_to:%d-%b-%Y})")
        results, log_rows, summaries = [], [], []
        for scenario in SCENARIOS:
            began = time.time()
            rows, (metric_name, metric_value), lines = scenario.run(inputs, data_to, run_at, db.save_csv)
            seconds = round(time.time() - began, 2)
            # the data the scenario was trained on / built from, in plain English (ml_run_log.trained_on)
            trained_on = scenario.trained_on(inputs, data_to, rows) if hasattr(scenario, "trained_on") else None
            results.append((scenario.TABLE, rows))
            log_rows.append({"scenario": scenario.SCENARIO, "result_table": scenario.TABLE.name,
                             "rows_written": len(rows), "metric_name": metric_name,
                             "metric_value": metric_value, "seconds": seconds, "data_to": data_to,
                             "run_at": run_at, "trained_on": trained_on})
            summaries.append((scenario.SCENARIO, scenario.TABLE.name, len(rows), metric_name, metric_value,
                              seconds, lines))
            out(f"\n[{scenario.SCENARIO}] -> {scenario.TABLE.name}: {len(rows)} rows, "
                f"{metric_name} = {metric_value}, {seconds} s")
            if trained_on:
                out(f"  trained on / built from: {trained_on}")
            for line in lines:
                out(f"  {line}")
        if dry_run:
            out("\n--dry-run: nothing written to MySQL (the CSV files are in ml_inputdata/).")
        else:
            counts, run_id = db.write_results(results, log_rows, engine)
            out(f"\nWrote run {run_id} into {db.GOLD_DB}: " + ", ".join(f"{k} {v}" for k, v in counts.items())
                + " + ml_run_log")
        out(f"Training data: {db.DATA_DIR}  |  total {time.time() - started:.1f} s")
        return summaries
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description="Train the ML scenarios on ss_gold and write the ml_* tables.")
    parser.add_argument("--dry-run", action="store_true", help="train and write the CSV files, but not MySQL")
    args = parser.parse_args()
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
