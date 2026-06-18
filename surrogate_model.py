"""
Surrogate modeling helpers for DEFORM optimization datasets.

The first supported models are tabular regressors. Tree models are robust for
small, mixed-quality simulation datasets. Gaussian processes are useful for
Bayesian optimization because they provide uncertainty estimates.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd


def _require_sklearn():
    """Import sklearn lazily so dataset tools can run without ML packages."""
    try:
        from sklearn.compose import ColumnTransformer
        from sklearn.ensemble import ExtraTreesRegressor, RandomForestRegressor
        from sklearn.gaussian_process import GaussianProcessRegressor
        from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel
        from sklearn.impute import SimpleImputer
        from sklearn.metrics import mean_absolute_error, r2_score
        from sklearn.model_selection import train_test_split
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import OneHotEncoder, StandardScaler
    except ImportError as exc:
        raise ImportError(
            "Surrogate modeling requires scikit-learn. Install it in the DEFORM "
            "Python environment before training models."
        ) from exc

    return {
        "ColumnTransformer": ColumnTransformer,
        "ExtraTreesRegressor": ExtraTreesRegressor,
        "RandomForestRegressor": RandomForestRegressor,
        "GaussianProcessRegressor": GaussianProcessRegressor,
        "ConstantKernel": ConstantKernel,
        "Matern": Matern,
        "WhiteKernel": WhiteKernel,
        "SimpleImputer": SimpleImputer,
        "mean_absolute_error": mean_absolute_error,
        "r2_score": r2_score,
        "train_test_split": train_test_split,
        "Pipeline": Pipeline,
        "OneHotEncoder": OneHotEncoder,
        "StandardScaler": StandardScaler,
    }


def infer_feature_columns(df, target_column, exclude_columns=None):
    """Infer usable feature columns from a dataset."""
    if exclude_columns is None:
        exclude_columns = []
    excluded = set(exclude_columns) | {target_column}
    return [column for column in df.columns if column not in excluded and not column.endswith("_json")]


def build_preprocessor(df, feature_columns):
    """Create preprocessing for numeric and categorical columns."""
    sk = _require_sklearn()
    numeric_features = [
        col for col in feature_columns if pd.api.types.is_numeric_dtype(df[col])
    ]
    categorical_features = [col for col in feature_columns if col not in numeric_features]

    numeric_pipeline = sk["Pipeline"]([
        ("imputer", sk["SimpleImputer"](strategy="median")),
        ("scaler", sk["StandardScaler"]()),
    ])
    categorical_pipeline = sk["Pipeline"]([
        ("imputer", sk["SimpleImputer"](strategy="most_frequent")),
        ("onehot", sk["OneHotEncoder"](handle_unknown="ignore")),
    ])

    return sk["ColumnTransformer"]([
        ("numeric", numeric_pipeline, numeric_features),
        ("categorical", categorical_pipeline, categorical_features),
    ])


def make_regressor(model_type="random_forest", random_state=1):
    """Create a supported regression model."""
    sk = _require_sklearn()
    if model_type == "random_forest":
        return sk["RandomForestRegressor"](n_estimators=300, random_state=random_state)
    if model_type == "extra_trees":
        return sk["ExtraTreesRegressor"](n_estimators=300, random_state=random_state)
    if model_type == "gaussian_process":
        kernel = (
            sk["ConstantKernel"](1.0)
            * sk["Matern"](length_scale=1.0, nu=2.5)
            + sk["WhiteKernel"](noise_level=1e-5)
        )
        return sk["GaussianProcessRegressor"](
            kernel=kernel,
            normalize_y=True,
            random_state=random_state,
        )
    raise ValueError("model_type must be random_forest, extra_trees, or gaussian_process.")


def train_surrogate(
    dataset_csv_path,
    target_column="objective",
    feature_columns=None,
    exclude_columns=None,
    model_type="random_forest",
    random_state=1,
    test_size=0.25,
):
    """Train and evaluate a surrogate model from a dataset CSV."""
    sk = _require_sklearn()
    df = pd.read_csv(dataset_csv_path)
    df = df.dropna(subset=[target_column])

    if feature_columns is None:
        feature_columns = infer_feature_columns(df, target_column, exclude_columns=exclude_columns)

    x = df[feature_columns]
    y = pd.to_numeric(df[target_column], errors="coerce")
    valid = y.notna()
    x = x.loc[valid]
    y = y.loc[valid]

    if len(df) < 3:
        raise ValueError("Need at least three completed rows to train a surrogate.")

    x_train, x_test, y_train, y_test = sk["train_test_split"](
        x,
        y,
        test_size=test_size,
        random_state=random_state,
    )

    model = sk["Pipeline"]([
        ("preprocess", build_preprocessor(df, feature_columns)),
        ("regressor", make_regressor(model_type=model_type, random_state=random_state)),
    ])
    model.fit(x_train, y_train)
    predictions = model.predict(x_test)

    report = {
        "model_type": model_type,
        "target_column": target_column,
        "feature_columns": feature_columns,
        "n_train": int(len(x_train)),
        "n_test": int(len(x_test)),
        "mae": float(sk["mean_absolute_error"](y_test, predictions)),
        "r2": float(sk["r2_score"](y_test, predictions)) if len(x_test) > 1 else np.nan,
    }
    return model, report


def save_training_report(report, output_json_path):
    """Save a surrogate training report to JSON."""
    output_json_path = Path(output_json_path)
    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_json_path, "w") as file:
        json.dump(report, file, indent=2)
    return output_json_path
