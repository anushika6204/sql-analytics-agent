import pandas as pd

from app.charts import build_figure, suggest_chart, to_dataframe


def test_line_chart_for_time_series():
    df = pd.DataFrame({"month": ["2025-01", "2025-02", "2025-03"], "total_sales": [10, 20, 15]})
    spec = suggest_chart(df)
    assert spec == {"type": "line", "x": "month", "y": "total_sales"}
    assert build_figure(df, spec).data


def test_pie_for_few_categories_and_bar_for_many():
    few = pd.DataFrame({"region": list("NSEW"), "total": [1, 2, 3, 4]})
    assert suggest_chart(few)["type"] == "pie"
    many = pd.DataFrame({"name": [f"c{i}" for i in range(10)], "total": range(10)})
    assert suggest_chart(many)["type"] == "bar"


def test_no_chart_for_non_numeric_single_row_or_id_only_data():
    assert suggest_chart(pd.DataFrame({"name": ["a", "b"], "city": ["x", "y"]})) is None
    assert suggest_chart(pd.DataFrame({"total": [5]})) is None
    assert suggest_chart(pd.DataFrame({"id": [1, 2, 3], "name": list("abc")})) is None


def test_raw_orders_table_charts_amount_over_date():
    df = to_dataframe({"columns": ["id", "order_date", "amount"],
                       "rows": [[1, "2025-01-01", 5.0], [2, "2025-01-02", 7.0]]})
    spec = suggest_chart(df)
    assert spec["x"] == "order_date" and spec["y"] == "amount" and spec["type"] == "line"
