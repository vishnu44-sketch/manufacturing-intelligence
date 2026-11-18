"""ml - the machine-learning step of the SS Manufacturing Intelligence Platform.

It reads the company data in ss_gold, trains six small, explainable models and writes their results
back into ss_gold as ml_* tables (the AI and the Insights page read them as the read-only user):

  forecast.py        sales forecast for the next 12 sales months (+ 3 months of the top 10 products)  -> ml_sales_forecast
  customer_risk.py   customers who buy less or stopped, with a 0-100 risk score          -> ml_customer_risk
  segments.py        customer groups (KMeans on recency / frequency / money)              -> ml_customer_segments
  invoice_alerts.py  unusual prices, quantities and very large credit notes               -> ml_invoice_alerts
  product_pairs.py   products bought together on the same sales order                      -> ml_product_pairs
  stock_runout.py    days of stock left at the current sales speed                         -> ml_stock_runout

Run it with:  venv\\Scripts\\python.exe ml\\run_ml.py   (or: python manage.py run_ml)
db.py holds the table definitions' class, the MySQL connection and the safety checks of every write.
"""
