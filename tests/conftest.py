from __future__ import annotations

import pandas as pd
import pytest

from anomalyguard.demo import generate_orders, generate_sensor, generate_tabular


@pytest.fixture(scope="session")
def orders() -> tuple[pd.DataFrame, pd.DataFrame]:
    return generate_orders(n_rows=800, seed=7)


@pytest.fixture(scope="session")
def tabular() -> tuple[pd.DataFrame, pd.DataFrame]:
    return generate_tabular(n_rows=1200, seed=7)


@pytest.fixture(scope="session")
def sensor() -> tuple[pd.DataFrame, pd.DataFrame]:
    return generate_sensor(n_points=24 * 40, seed=7)


@pytest.fixture()
def orders_csv(tmp_path, orders) -> str:
    path = tmp_path / "orders.csv"
    orders[0].to_csv(path, index=False)
    return str(path)
