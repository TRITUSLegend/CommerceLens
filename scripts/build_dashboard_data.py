"""Build the small pre-aggregated parquet files that the Streamlit dashboard reads.

Usage (from the repo root):
    python scripts/build_dashboard_data.py

Runs the same sql/ queries and src/ model code as the notebooks, so every number
on the dashboard traces back to them. Output: dashboard/data/*.parquet
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.metrics import precision_recall_curve, roc_curve  # noqa: E402

from src import db, features as F, model as M  # noqa: E402

OUT_DIR = ROOT / "dashboard" / "data"
TEMPORAL_CUTOFF = pd.Timestamp("2018-05-01")

# parquet name -> sql file (single-SELECT queries exported as-is)
SQL_EXPORTS = {
    "kpis": "10_kpis.sql",
    "order_status": "01_order_status.sql",
    "funnel": "02_order_funnel.sql",
    "pareto_category": "03_pareto_category.sql",
    "pareto_seller": "04_pareto_seller.sql",
    "revenue_by_state": "05_revenue_by_state.sql",
    "monthly_trend": "06_monthly_trend.sql",
    "order_frequency": "07_order_frequency.sql",
    "delay_vs_review": "11_delay_vs_review.sql",
    "late_vs_ontime": "12_late_vs_ontime.sql",
    "category_ops": "13_category_ops.sql",
    "state_ops": "14_state_ops.sql",
    "freight_vs_review": "15_freight_ratio_vs_review.sql",
    "first_order_vs_repeat": "16_first_order_vs_repeat.sql",
    "seller_tiers": "17_seller_tier_ops.sql",
    "monthly_ops": "20_monthly_ops.sql",
}


def save(df: pd.DataFrame, name: str) -> None:
    """Write one parquet file and log its size."""
    path = OUT_DIR / f"{name}.parquet"
    df.to_parquet(path, index=False)
    print(f"  {path.name:<32} {len(df):>6} rows  {path.stat().st_size / 1024:7.1f} KB")


def export_sql(con) -> None:
    """Export every Layer 1/2 query result."""
    for name, sql_file in SQL_EXPORTS.items():
        df = db.query(con, sql_file)
        if name == "pareto_seller":
            df = df.drop(columns="seller_id")  # anonymous rank is enough for the chart
        save(df, name)
    db.run_script(con, "08_rfm_customers.sql")
    save(db.query(con, "09_rfm_segments.sql"), "rfm_segments")


def export_model(con) -> None:
    """Train the Layer 3 models exactly as in 03_model.ipynb and export metrics + SHAP."""
    # Target comparison
    rows = []
    for name, loader in [("Repeat purchase (180d)", F.repeat_dataset), ("Low review (1-2 stars)", F.low_review_dataset)]:
        X, y, _ = loader(con)
        X_tr, X_te, y_tr, y_te = M.split(X, y)
        scores = M.train_lgbm(X_tr, y_tr).predict_proba(X_te)[:, 1]
        cap = M.capture_at_top(y_te, scores)
        rows.append({"target": name, "rows": len(y), **M.evaluate(y_te, scores),
                     "precision_top10": cap["precision_at_top"], "recall_top10": cap["recall_at_top"]})
    save(pd.DataFrame(rows), "model_target_comparison")

    # Final low-review model vs baselines
    X, y, ts = F.low_review_dataset(con)
    X_tr, X_te, y_tr, y_te = M.split(X, y)
    lgbm = M.train_lgbm(X_tr, y_tr)
    logit = M.train_logistic(X_tr, y_tr)
    p_lgbm = lgbm.predict_proba(X_te)[:, 1]
    past, future = ts < TEMPORAL_CUTOFF, ts >= TEMPORAL_CUTOFF
    lgbm_t = M.train_lgbm(X[past], y[past])
    metrics = pd.DataFrame([
        {"model": "No-skill baseline", "evaluation": "Stratified random split",
         "positive_rate": y_te.mean(), "roc_auc": 0.5, "pr_auc": y_te.mean()},
        {"model": "Logistic regression", "evaluation": "Stratified random split",
         **M.evaluate(y_te, logit.predict_proba(X_te)[:, 1])},
        {"model": "LightGBM", "evaluation": "Stratified random split", **M.evaluate(y_te, p_lgbm)},
        {"model": "LightGBM", "evaluation": f"Out-of-time (train < {TEMPORAL_CUTOFF:%Y-%m-%d})",
         **M.evaluate(y[future], lgbm_t.predict_proba(X[future])[:, 1])},
    ])
    metrics["pr_auc_lift"] = metrics["pr_auc"] / metrics["positive_rate"]
    save(metrics, "model_metrics")

    capture = pd.DataFrame([M.capture_at_top(y_te, p_lgbm, f) for f in (0.05, 0.10, 0.20, 0.30)])
    capture["lift_vs_random"] = capture["precision_at_top"] / y_te.mean()
    save(capture, "model_capture")

    # Fine-grained capture curve (1%..100%) for the dashboard's what-if slider
    curve = pd.DataFrame([M.capture_at_top(y_te, p_lgbm, f / 100) for f in range(1, 101)])
    curve["lift_vs_random"] = curve["precision_at_top"] / y_te.mean()
    save(curve, "model_capture_curve")

    # ROC and precision-recall curves (downsampled) for LightGBM and the logistic baseline
    curves = []
    for label, scores in [("LightGBM", p_lgbm), ("Logistic regression", logit.predict_proba(X_te)[:, 1])]:
        fpr, tpr, _ = roc_curve(y_te, scores)
        prec, rec, _ = precision_recall_curve(y_te, scores)
        roc_idx = np.linspace(0, len(fpr) - 1, 200).astype(int)
        pr_idx = np.linspace(0, len(rec) - 1, 200).astype(int)
        curves.append(pd.DataFrame({"model": label, "curve": "ROC", "x": fpr[roc_idx], "y": tpr[roc_idx]}))
        curves.append(pd.DataFrame({"model": label, "curve": "PR", "x": rec[pr_idx], "y": prec[pr_idx]}))
    save(pd.concat(curves, ignore_index=True), "model_curves")

    # SHAP: global importance + a long-format sample for a beeswarm-style chart
    shap_values, X_sample, importance = M.shap_importance(lgbm, X_te)
    save(importance, "shap_importance")

    top_numeric = [f for f in importance["feature"] if f in F.NUMERIC_FEATURES][:10]
    frames = []
    for f in top_numeric:
        v = X_sample[f].astype(float)
        lo, hi = v.quantile(0.02), v.quantile(0.98)  # robust 0-1 scaling for colour
        frames.append(pd.DataFrame({
            "feature": f,
            "shap_value": shap_values[:, X_sample.columns.get_loc(f)],
            "feature_value": v.values,
            "feature_scaled": ((v.clip(lo, hi) - lo) / (hi - lo if hi > lo else 1)).values,
        }))
    beeswarm = pd.concat(frames, ignore_index=True)
    beeswarm = beeswarm.groupby("feature").sample(n=min(1500, len(X_sample)), random_state=M.SEED)
    save(beeswarm.astype({"shap_value": "float32", "feature_value": "float32", "feature_scaled": "float32"}),
         "shap_beeswarm")

    col = X_sample.columns.get_loc("customer_state")
    state_effect = (
        pd.DataFrame({"customer_state": X_sample["customer_state"].astype(str).values, "shap": shap_values[:, col]})
        .groupby("customer_state")["shap"].agg(mean_shap="mean", orders="size").reset_index()
        .query("orders >= 50").sort_values("mean_shap", ascending=False)
    )
    save(state_effect, "shap_state_effect")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    con = db.connect()
    print(f"Writing parquet files to {OUT_DIR}")
    export_sql(con)
    print("Training models (about a minute)...")
    export_model(con)
    total = sum(p.stat().st_size for p in OUT_DIR.glob("*.parquet"))
    print(f"Done. Total size: {total / 1024:.1f} KB")


if __name__ == "__main__":
    np.random.seed(M.SEED)
    main()
