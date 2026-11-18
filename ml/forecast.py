"""forecast.py - sales forecast for the next 12 SALES months (21st to 20th) in total, and the next 3 for the top products.

Training data: net sales (SUM of net_taxable_value: credit notes are negative already) per sales month. Only
COMPLETE sales months are used: a month that starts before the first invoice date (Apr 2024 starts on
21-Mar-2024, the data on 02-Apr-2024) or ends after the newest invoice date (Nov 2026 = 21-Oct..20-Nov-2026,
the data ends on 31-Oct-2026) is left out.

Models tried on the total (each is small and explainable); the one with the lowest backtest error wins:
  - Holt-Winters (statsmodels ExponentialSmoothing): a level, a trend and a 12-month season (multiplicative
    and additive seasons are both tried)
  - SARIMAX (1,0,0)(0,1,0,12) with a drift: this month = the same month last year + the growth
  - Same month last year x growth: the sales of the same month a year before, times the growth of the
    last 12 months against the 12 before
  - Average of the last 3 months (the fallback for a short history)
Backtest: each model is trained on every month except the last 6 complete months, then forecasts those 6;
MAPE % = the average of |actual - forecast| / actual. The winner is trained again on ALL complete months.
Low / high = an 80 % range from the backtest errors: forecast x (1 -/+ 1.28 x the root-mean-square
percentage error), 10 % wider for each month further ahead (month 12 = 2.1 x the width of month 1).

Top products: the 10 products with the highest net sales in the last 12 complete months, for the first 3
forecast months only. Each month's forecast = the product's average share of the company's sales in the last 6
months x that month's total forecast; the range uses how much that share moves from month to month. Their MAPE
comes from the same backtest.
"""
import math
import warnings

import numpy as np
import pandas as pd

from .db import MlTable, as_date, money

SCENARIO = "sales_forecast"
HORIZON = 12           # sales months forecast for the company total
# Products get fewer months: many top products have short or patchy histories, and their share of the total
# moves from month to month, so a share-based forecast far ahead would be mostly guesswork.
PRODUCT_HORIZON = 3    # sales months forecast for each top product
TEST_MONTHS = 6        # months held back in the backtest
TOP_PRODUCTS = 10
Z80 = 1.2816           # 80 % of a normal distribution lies within +/- 1.28 standard deviations
MIN_BAND = 0.03        # the range is never narrower than +/- 3 %

TABLE = MlTable("ml_sales_forecast", (
    "Sales forecast (ML): net sales forecast for the next 12 SALES months (21st to 20th) after the newest "
    "complete sales month, as one TOTAL row per month, plus the next 3 months for the top 10 products "
    "(level 'PRODUCT', one row per product and month). INR, before GST, like SUM(net_taxable_value). low_inr / high_inr = an 80 % range. "
    "Made by ml/run_ml.py; the run is in ml_run_log."), [
    ("forecast_id", "INT NOT NULL", "Row key: TOTAL rows first (in month order), then the PRODUCT rows (month by month)."),
    ("level", "VARCHAR(10) NOT NULL", "'TOTAL' = the whole company's net sales; 'PRODUCT' = one product (one of the top 10 by net sales of the last 12 complete sales months)."),
    ("product_id", "INT", "-> dim_products.product_id on PRODUCT rows; NULL on TOTAL rows."),
    ("product_code", "VARCHAR(30)", "SAP item code on PRODUCT rows, e.g. 'FG00123'; NULL on TOTAL rows."),
    ("product_description", "VARCHAR(255)", "Product description on PRODUCT rows; NULL on TOTAL rows."),
    ("sales_month", "VARCHAR(8) NOT NULL", "The forecast sales month, named like dim_calendar.sales_month, e.g. 'Nov 2026' (21-Oct-2026 .. 20-Nov-2026)."),
    ("period_start", "DATE NOT NULL", "First day of that sales month (the 21st of the previous month)."),
    ("period_end", "DATE NOT NULL", "Last day of that sales month (the 20th)."),
    ("horizon_months", "TINYINT", "How far ahead: 1 = the first sales month after the newest complete one, 2 = the next, ... 12 = the twelfth (TOTAL rows 1-12, PRODUCT rows 1-3)."),
    ("forecast_inr", "DECIMAL(18,2)", "Forecast net sales in INR, before GST and freight (the model's best guess)."),
    ("low_inr", "DECIMAL(18,2)", "Low end of the 80 % range in INR: the actual is expected to be above this 9 times in 10."),
    ("high_inr", "DECIMAL(18,2)", "High end of the 80 % range in INR: the actual is expected to be below this 9 times in 10."),
    ("model_name", "VARCHAR(80)", "Model that made the forecast, e.g. 'Holt-Winters (trend + multiplicative 12-month season)'; for products 'Share of the total forecast'."),
    ("mape_pct", "DECIMAL(9,2)", "Backtest accuracy: average error in % (MAPE) when the model forecast the last 6 complete sales months from the months before. Lower is better; 5 = 5 % average error."),
    ("train_from_month", "VARCHAR(8)", "First sales month the model was trained on (the oldest COMPLETE sales month of the data), e.g. 'May 2024'. The same on every row."),
    ("train_to_month", "VARCHAR(8)", "Last sales month the model was trained on (the newest COMPLETE sales month), e.g. 'Oct 2026'. The forecast starts with the month after it. The same on every row."),
    ("train_months", "SMALLINT", "How many complete sales months the model was trained on (train_from_month .. train_to_month), e.g. 30. The same on every row."),
    ("data_to", "DATE", "Newest invoice date the model saw. The forecast is 'as of' this date (the last complete sales month ends on or before it)."),
    ("run_at", "DATETIME", "When ml/run_ml.py made this forecast."),
], primary_key=["forecast_id"], indexes=["sales_month"])


# ------------------------------------------------------------------ training data
def sales_month_of(dates, calendar):
    """The sales month columns (sales_month, period_start, period_end) for each date, from dim_calendar."""
    cal = calendar[["full_date", "sales_month", "sales_period_start", "sales_period_end"]].copy()
    cal["full_date"] = pd.to_datetime(cal["full_date"])
    frame = pd.DataFrame({"full_date": pd.to_datetime(dates)})
    return frame.merge(cal, on="full_date", how="left")


def monthly_sales(lines, calendar, data_from, data_to):
    """Net sales per sales month: sales_month, period_start, period_end, net_sales_inr, complete.
    complete = the whole month lies inside the data (first invoice date .. data_to)."""
    months = sales_month_of(lines["invoice_date"], calendar)
    frame = pd.DataFrame({"sales_month": months["sales_month"].values,
                          "period_start": pd.to_datetime(months["sales_period_start"]).values,
                          "period_end": pd.to_datetime(months["sales_period_end"]).values,
                          "net_sales_inr": lines["net_taxable_value"].astype(float).values})
    frame = frame.dropna(subset=["sales_month"])
    out = (frame.groupby(["sales_month", "period_start", "period_end"], as_index=False)["net_sales_inr"].sum()
           .sort_values("period_start").reset_index(drop=True))
    out["complete"] = ((out["period_start"] >= pd.Timestamp(data_from))
                       & (out["period_end"] <= pd.Timestamp(data_to)))
    return out


def training_period(complete):
    """The complete sales months the model is trained on, as the ml_sales_forecast columns:
    {"train_from_month": 'May 2024', "train_to_month": 'Oct 2026', "train_months": 30}."""
    return {"train_from_month": complete["sales_month"].iloc[0], "train_to_month": complete["sales_month"].iloc[-1],
            "train_months": len(complete)}


def trained_on(inputs, data_to, rows):
    """The ml_run_log.trained_on text of this scenario, from its rows, e.g.
    '30 complete sales months May 2024 - Oct 2026 (net sales per sales month)'."""
    if not rows:
        return None
    first = rows[0]
    return (f"{first['train_months']} complete sales months {first['train_from_month']} - "
            f"{first['train_to_month']} (net sales per sales month)")


def next_months(calendar, last_period_end, count=HORIZON):
    """The `count` sales months after the one that ends on last_period_end: [(name, start, end), ...]."""
    cal = calendar[["sales_month", "sales_period_start", "sales_period_end"]].drop_duplicates().copy()
    cal["sales_period_start"] = pd.to_datetime(cal["sales_period_start"])
    cal["sales_period_end"] = pd.to_datetime(cal["sales_period_end"])
    later = cal[cal["sales_period_start"] > pd.Timestamp(last_period_end)].sort_values("sales_period_start")
    found = [(r.sales_month, r.sales_period_start, r.sales_period_end) for r in later.head(count).itertuples()]
    start = pd.Timestamp(found[-1][2]) if found else pd.Timestamp(last_period_end)
    while len(found) < count:                # past the calendar's end: make the next months ourselves
        begin = start + pd.Timedelta(days=1)                       # the 21st
        end = (begin + pd.DateOffset(months=1)).replace(day=20)    # the 20th of the next month
        found.append((end.strftime("%b %Y"), begin, end))
        start = end
    return found


# ------------------------------------------------------------------ the models
def _holt_winters(seasonal):
    def fit_forecast(history, steps):
        from statsmodels.tsa.holtwinters import ExponentialSmoothing
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = ExponentialSmoothing(np.asarray(history, dtype=float), trend="add", seasonal=seasonal,
                                         seasonal_periods=12, initialization_method="estimated").fit()
            return np.asarray(model.forecast(steps), dtype=float)
    return fit_forecast


def _sarimax(history, steps):
    from statsmodels.tsa.statespace.sarimax import SARIMAX
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = SARIMAX(np.asarray(history, dtype=float), order=(1, 0, 0), seasonal_order=(0, 1, 0, 12),
                        trend="c").fit(disp=False)
        return np.asarray(model.forecast(steps), dtype=float)


def _same_month_last_year(history, steps):
    history = np.asarray(history, dtype=float)
    growth = history[-12:].sum() / history[-24:-12].sum()
    return np.array([history[len(history) - 12 + h] * growth for h in range(steps)])


def _last_3_average(history, steps):
    return np.repeat(np.asarray(history, dtype=float)[-3:].mean(), steps)


# name, function, the fewest months of history it needs
MODELS = [
    ("Holt-Winters (trend + multiplicative 12-month season)", _holt_winters("mul"), 24),
    ("Holt-Winters (trend + additive 12-month season)", _holt_winters("add"), 24),
    ("SARIMAX (1,0,0)(0,1,0,12) with drift", _sarimax, 24),
    ("Same month last year x growth", _same_month_last_year, 24),
    ("Average of the last 3 months", _last_3_average, 3),
]


def mape(actual, predicted):
    """Mean absolute percentage error in % (months with actual 0 are skipped)."""
    actual, predicted = np.asarray(actual, dtype=float), np.asarray(predicted, dtype=float)
    keep = actual != 0
    if not keep.any():
        return float("nan")
    return float(np.mean(np.abs((actual[keep] - predicted[keep]) / actual[keep])) * 100)


def forecast_total(values, horizon=HORIZON, test_months=TEST_MONTHS):
    """Pick the model with the lowest backtest MAPE and forecast `horizon` months.

    values: net sales of the complete sales months, oldest first.
    Returns {"model", "mape_pct", "forecast": [...], "low": [...], "high": [...],
             "backtest": {"actual": [...], "predicted": [...]}, "tried": {model: mape}}."""
    values = np.asarray(values, dtype=float)
    if len(values) < 4:
        raise ValueError("The sales forecast needs at least 4 complete sales months.")
    test = min(test_months, max(1, len(values) // 4))
    train, actual = values[:-test], values[-test:]
    tried, best = {}, None
    for name, fit_forecast, needs in MODELS:
        if len(train) < needs:
            continue
        try:
            predicted = fit_forecast(train, test)
        except Exception:        # a model that cannot fit this history is simply not used
            continue
        if not np.all(np.isfinite(predicted)):
            continue
        error = mape(actual, predicted)
        tried[name] = round(error, 2)
        if best is None or error < best[1]:
            best = (name, error, predicted, fit_forecast)
    if best is None:
        raise ValueError("No forecast model could be trained on this history.")
    name, error, predicted, fit_forecast = best
    future = fit_forecast(values, horizon)
    pct_errors = (actual - predicted) / np.where(actual == 0, np.nan, actual)
    rms = float(np.sqrt(np.nanmean(pct_errors ** 2))) if np.isfinite(pct_errors).any() else MIN_BAND
    band = max(rms, MIN_BAND)
    low, high = [], []
    for h, value in enumerate(future, start=1):
        width = Z80 * band * (1 + 0.1 * (h - 1))
        low.append(max(0.0, value * (1 - width)))
        high.append(value * (1 + width))
    # the winner's backtest error of each test month = how far ahead it was (1 month, 2 months, ...), for the log
    by_horizon = [round(abs(float(e)) * 100, 2) for e in pct_errors]
    return {"model": name, "mape_pct": round(error, 2), "forecast": list(future), "low": low, "high": high,
            "backtest": {"actual": list(actual), "predicted": list(predicted), "error_pct_by_horizon": by_horizon},
            "tried": tried}


def forecast_products(product_months, total_actual, total_forecast, backtest_predicted, test_months):
    """Next-month forecast per product from its share of the total.

    product_months   : DataFrame, one row per product, one column per complete sales month (oldest first), INR
    total_actual     : the total net sales of the same months
    total_forecast   : (forecast, low, high) of the company total for the next month
    backtest_predicted: the total model's backtest forecasts of the last `test_months` months
    Returns a list of dicts: product_id, forecast, low, high, mape_pct."""
    total_actual = np.asarray(total_actual, dtype=float)
    shares = product_months.to_numpy(dtype=float) / np.where(total_actual == 0, np.nan, total_actual)
    forecast, low_total, high_total = total_forecast
    out = []
    for i, product_id in enumerate(product_months.index):
        recent = shares[i, -6:]
        share, spread = float(np.nanmean(recent)), float(np.nanstd(recent))
        # backtest: the share of the 6 months before each test month x the total model's backtest forecast
        actual = product_months.iloc[i].to_numpy(dtype=float)[-test_months:]
        predicted = []
        for k in range(test_months):
            end = len(total_actual) - test_months + k
            predicted.append(float(np.nanmean(shares[i, max(0, end - 6):end])) * backtest_predicted[k])
        out.append({"product_id": product_id, "forecast": share * forecast,
                    "low": max(0.0, (share - Z80 * spread) * low_total),
                    "high": (share + Z80 * spread) * high_total,
                    "mape_pct": round(mape(actual, predicted), 2)})
    return out


# ------------------------------------------------------------------ the scenario
def run(inputs, data_to, run_at, save_csv):
    """Build the training data, train, and return (rows for ml_sales_forecast, metric, summary text)."""
    lines, calendar, products = inputs["lines"], inputs["calendar"], inputs["products"]
    months = monthly_sales(lines, calendar, inputs["data_from"], data_to)
    complete = months[months["complete"]].reset_index(drop=True)
    total = forecast_total(complete["net_sales_inr"].to_numpy())
    future = next_months(calendar, complete["period_end"].iloc[-1])
    test = len(total["backtest"]["actual"])

    months_csv = months.copy()
    months_csv["used_for_training"] = months_csv["complete"]
    save_csv(months_csv, "forecast_monthly_sales.csv")

    rows = []
    for h, (name, start, end) in enumerate(future, start=1):
        rows.append({"level": "TOTAL", "sales_month": name, "period_start": as_date(start),
                     "period_end": as_date(end), "horizon_months": h,
                     "forecast_inr": money(total["forecast"][h - 1]), "low_inr": money(total["low"][h - 1]),
                     "high_inr": money(total["high"][h - 1]), "model_name": total["model"],
                     "mape_pct": total["mape_pct"]})

    # the top products of the last 12 complete months, month by month
    product_lines = lines[lines["product_id"] != -1]
    by_month = sales_month_of(product_lines["invoice_date"], calendar)
    frame = pd.DataFrame({"product_id": product_lines["product_id"].values,
                          "sales_month": by_month["sales_month"].values,
                          "net_sales_inr": product_lines["net_taxable_value"].astype(float).values})
    frame = frame[frame["sales_month"].isin(complete["sales_month"])]
    table = frame.pivot_table(index="product_id", columns="sales_month", values="net_sales_inr",
                              aggfunc="sum", fill_value=0.0)
    table = table.reindex(columns=list(complete["sales_month"]), fill_value=0.0)
    last_12 = list(complete["sales_month"].iloc[-12:])
    top_ids = table[last_12].sum(axis=1).sort_values(ascending=False).head(TOP_PRODUCTS).index
    top = table.loc[top_ids]
    names = products.set_index("product_id")
    top_csv = top.reset_index().melt(id_vars="product_id", var_name="sales_month", value_name="net_sales_inr")
    top_csv["product_code"] = top_csv["product_id"].map(names["product_code"])
    save_csv(top_csv[["product_id", "product_code", "sales_month", "net_sales_inr"]],
             "forecast_top_products_monthly_sales.csv")

    # the top products: the first PRODUCT_HORIZON forecast months, month by month (all products of a month together)
    for h, (name, start, end) in enumerate(future[:PRODUCT_HORIZON], start=1):
        product_rows = forecast_products(top, complete["net_sales_inr"].to_numpy(),
                                         (total["forecast"][h - 1], total["low"][h - 1], total["high"][h - 1]),
                                         total["backtest"]["predicted"], test)
        for item in product_rows:
            pid = item["product_id"]
            rows.append({"level": "PRODUCT", "product_id": int(pid),
                         "product_code": names["product_code"].get(pid), "product_description":
                         names["product_description"].get(pid), "sales_month": name,
                         "period_start": as_date(start), "period_end": as_date(end), "horizon_months": h,
                         "forecast_inr": money(item["forecast"]), "low_inr": money(item["low"]),
                         "high_inr": money(item["high"]), "model_name": "Share of the total forecast",
                         "mape_pct": None if math.isnan(item["mape_pct"]) else item["mape_pct"]})
    # the training period (the complete sales months the model learned from) goes on every row, so the app can
    # say it as data ("trained on 30 complete sales months, May 2024 - Oct 2026")
    trained = training_period(complete)
    for i, row in enumerate(rows, start=1):
        row.update({"forecast_id": i, **trained, "data_to": data_to, "run_at": run_at})

    lines_out = [f"trained on {trained['train_months']} complete sales months "
                 f"({trained['train_from_month']} .. {trained['train_to_month']}); "
                 f"models tried (backtest MAPE %): {total['tried']}",
                 f"winner: {total['model']}, backtest MAPE {total['mape_pct']} % on the last {test} months",
                 "backtest error % by months ahead: " + ", ".join(
                     f"{h}: {e}" for h, e in enumerate(total["backtest"]["error_pct_by_horizon"], start=1)),
                 f"products: the top {TOP_PRODUCTS} for the first {PRODUCT_HORIZON} forecast months"]
    for row in rows[:HORIZON]:
        lines_out.append(f"{row['sales_month']} ({row['period_start']:%d-%b-%Y} .. {row['period_end']:%d-%b-%Y}): "
                         f"{row['forecast_inr']:,.0f}  (80 %: {row['low_inr']:,.0f} .. {row['high_inr']:,.0f})")
    return rows, ("backtest MAPE % (last 6 months)", total["mape_pct"]), lines_out
