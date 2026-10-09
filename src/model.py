"""Training, evaluation and explanation helpers for the Layer 3 model."""

import warnings

import lightgbm as lgb
import numpy as np
import pandas as pd
import shap
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

SEED = 42

LGBM_PARAMS = dict(
    n_estimators=2000,
    learning_rate=0.03,
    num_leaves=31,
    min_child_samples=50,
    subsample=0.8,
    subsample_freq=1,
    colsample_bytree=0.8,
    reg_lambda=1.0,
    random_state=SEED,
    deterministic=True,
    force_col_wise=True,
    verbose=-1,
)


def split(X: pd.DataFrame, y: pd.Series, test_size: float = 0.2):
    """Stratified train/test split (keeps the positive rate equal in both sets)."""
    return train_test_split(X, y, test_size=test_size, stratify=y, random_state=SEED)


def train_lgbm(X_train: pd.DataFrame, y_train: pd.Series) -> lgb.LGBMClassifier:
    """Fit LightGBM, using an inner stratified validation split for early stopping.

    The test set is never touched here, so the reported test metrics stay unbiased.
    """
    X_tr, X_val, y_tr, y_val = train_test_split(
        X_train, y_train, test_size=0.2, stratify=y_train, random_state=SEED
    )
    model = lgb.LGBMClassifier(**LGBM_PARAMS)
    model.fit(
        X_tr, y_tr,
        eval_set=[(X_val, y_val)],
        eval_metric="average_precision",
        callbacks=[lgb.early_stopping(100, verbose=False)],
    )
    return model


def train_logistic(X_train: pd.DataFrame, y_train: pd.Series):
    """Simple baseline: one-hot categoricals + scaled numerics into logistic regression."""
    cat_cols = X_train.select_dtypes("category").columns.tolist()
    num_cols = [c for c in X_train.columns if c not in cat_cols]
    pre = ColumnTransformer([
        ("num", make_pipeline(SimpleImputer(strategy="median"), StandardScaler()), num_cols),
        ("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=50), cat_cols),
    ])
    model = make_pipeline(pre, LogisticRegression(max_iter=2000))
    model.fit(X_train, y_train)
    return model


def evaluate(y_true, scores) -> dict:
    """ROC-AUC and PR-AUC, with the no-skill baselines for context.

    A random classifier scores ROC-AUC 0.5 and PR-AUC equal to the positive rate,
    so pr_auc_lift = PR-AUC / positive rate is the fair "better than chance" ratio.
    """
    prevalence = float(np.mean(y_true))
    pr_auc = average_precision_score(y_true, scores)
    return {
        "positive_rate": prevalence,
        "roc_auc": roc_auc_score(y_true, scores),
        "pr_auc": pr_auc,
        "pr_auc_lift": pr_auc / prevalence,
    }


def capture_at_top(y_true, scores, top_frac: float = 0.10) -> dict:
    """Share of all positives found in the top `top_frac` highest-scored rows."""
    y_true = np.asarray(y_true)
    n_top = int(np.ceil(len(scores) * top_frac))
    top_idx = np.argsort(-np.asarray(scores))[:n_top]
    return {
        "top_frac": top_frac,
        "precision_at_top": y_true[top_idx].mean(),
        "recall_at_top": y_true[top_idx].sum() / y_true.sum(),
    }


def shap_importance(model: lgb.LGBMClassifier, X: pd.DataFrame, max_rows: int = 5000):
    """SHAP values on a sample of X; returns (shap_values, X_sample, mean |SHAP| table)."""
    X_sample = X.sample(min(max_rows, len(X)), random_state=SEED)
    with warnings.catch_warnings():  # SHAP warns about its own output-format change
        warnings.simplefilter("ignore", UserWarning)
        values = shap.TreeExplainer(model).shap_values(X_sample)
    if isinstance(values, list):  # older SHAP returns [class0, class1]
        values = values[1]
    importance = (
        pd.DataFrame({"feature": X_sample.columns, "mean_abs_shap": np.abs(values).mean(axis=0)})
        .sort_values("mean_abs_shap", ascending=False)
        .reset_index(drop=True)
    )
    return values, X_sample, importance
