# ml_inputdata - the input files of the ML models

`ml/run_ml.py` writes these CSV files on every run (they are not in git: `ml_inputdata/*.csv` in .gitignore).
They hold exactly what each model was trained on: only the parts of the company data each model needs, read from
ss_gold (the cleaned inputdata/ files) up to the newest invoice date (data_to). The results are not here - they go
into the ml_* tables in ss_gold.

- `forecast_monthly_sales.csv` - net sales per sales month (21st to 20th): sales_month, period_start,
  period_end, net_sales_inr, complete / used_for_training (only complete months train the forecast).
- `forecast_top_products_monthly_sales.csv` - net sales per complete sales month of the top 10 products.
- `customer_features.csv` - one row per customer: invoices, last / first invoice, sales of the last 3 months,
  the 3 before, the 12 before, the same 3 months a year ago, orders, typical gap (the risk score's inputs).
- `customer_rfm.csv` - one row per customer: recency_days, invoices, sales_inr, tenure_days (the KMeans groups).
- `invoice_lines_for_alerts.csv` - every invoice / credit / debit note line with price, quantity and value
  (the unusual-invoice checks).
- `order_baskets.csv` - one row per sales order (SO number / financial year) and product, cancelled orders
  left out (the bought-together pairs).
- `stock_speed.csv` - every item of the newest stock report: stock quantity, quantity sold in the last 90 days
  and the average per day (the stock run-out).
