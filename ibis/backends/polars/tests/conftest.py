from __future__ import annotations

from typing import Any

import numpy as np
import polars as pl
import pytest

import ibis
from ibis.backends.conftest import TEST_TABLES
from ibis.backends.tests.base import BackendTest
from ibis.backends.tests.data import array_types, struct_types, topk, win


class TestConf(BackendTest):
    supports_structs = True
    supports_json = False
    reduction_tolerance = 1e-3
    stateful = False
    deps = ("polars",)

    def _load_data(self, **_: Any) -> None:
        con = self.connection
        for table_name in TEST_TABLES:
            path = self.data_dir / "parquet" / f"{table_name}.parquet"
            with pytest.warns(FutureWarning, match="v9.1"):
                con.register(path, table_name=table_name)
        # TODO: remove warnings and replace register when implementing 8858
        with pytest.warns(FutureWarning, match="v9.1"):
            con.register(array_types, table_name="array_types")
            con.register(struct_types, table_name="struct")
            con.register(win, table_name="win")

        # TODO: remove when pyarrow inputs are supported
        con._add_table("topk", pl.from_arrow(topk).lazy())

    @staticmethod
    def connect(*, tmpdir, worker_id, **kw):
        return ibis.polars.connect(**kw)

    @classmethod
    def assert_series_equal(cls, left, right, *args, **kwargs) -> None:
        check_dtype = kwargs.pop("check_dtype", True) and not (
            issubclass(left.dtype.type, np.timedelta64)
            and issubclass(right.dtype.type, np.timedelta64)
        )
        return super().assert_series_equal(
            left, right, *args, **kwargs, check_dtype=check_dtype
        )


@pytest.fixture(scope="session")
def con(data_dir, tmp_path_factory, worker_id):
    return TestConf.load_data(data_dir, tmp_path_factory, worker_id).connection


@pytest.fixture(scope="session")
def alltypes(con):
    return con.table("functional_alltypes")
