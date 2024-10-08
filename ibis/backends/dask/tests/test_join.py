from __future__ import annotations

import pandas as pd
import pytest
from pandas import date_range

import ibis

dd = pytest.importorskip("dask.dataframe")
from dask.dataframe.utils import tm  # noqa: E402

# Note - computations in this file use the single threadsed scheduler (instead
# of the default multithreaded scheduler) in order to avoid a flaky interaction
# between dask and pandas in merges. There is evidence this has been fixed in
# pandas>=1.1.2 (or in other schedulers). For more background see:
# - https://github.com/dask/dask/issues/6454
# - https://github.com/dask/dask/issues/5060


join_type = pytest.mark.parametrize(
    "how",
    [
        "inner",
        "left",
        "right",
        "outer",
    ],
)


@join_type
def test_join(how, left, right, df1, df2):
    expr = left.join(right, left.key == right.key, how=how).select(
        left, right.other_value, right.key3
    )
    result = expr.compile()
    expected = dd.merge(df1, df2, how=how, on="key")
    tm.assert_frame_equal(
        result[expected.columns].compute(scheduler="single-threaded"),
        expected.compute(scheduler="single-threaded").reset_index(drop=True),
    )


@join_type
def test_join_project_left_table(how, left, right, df1, df2):
    expr = left.join(right, left.key == right.key, how=how).select(left, right.key3)
    result = expr.compile()
    expected = dd.merge(df1, df2, how=how, on="key")[list(left.columns) + ["key3"]]
    tm.assert_frame_equal(
        result[expected.columns].compute(scheduler="single-threaded"),
        expected.compute(scheduler="single-threaded").reset_index(drop=True),
    )


@join_type
def test_join_with_invalid_predicates(how, left, right):
    predicate = (left.key == right.key) & (left.key2 <= right.key3)
    expr = left.join(right, predicate, how=how)
    with pytest.raises(TypeError):
        expr.compile()

    predicate = left.key >= right.key
    expr = left.join(right, predicate, how=how)
    with pytest.raises(TypeError):
        expr.compile()


@join_type
@pytest.mark.xfail(reason="Hard to detect this case")
def test_join_with_duplicate_non_key_columns(how, left, right, df1, df2):
    left = left.mutate(x=left.value * 2)
    right = right.mutate(x=right.other_value * 3)
    expr = left.join(right, left.key == right.key, how=how)

    # This is undefined behavior because `x` is duplicated. This is difficult
    # to detect
    with pytest.raises(ValueError):
        expr.compile()


@join_type
def test_join_with_post_expression_selection(how, left, right, df1, df2):
    join = left.join(right, left.key == right.key, how=how)
    expr = join.select(left.key, left.value, right.other_value)
    result = expr.compile()
    expected = dd.merge(df1, df2, on="key", how=how)[["key", "value", "other_value"]]
    tm.assert_frame_equal(
        result[expected.columns].compute(scheduler="single-threaded"),
        expected.compute(scheduler="single-threaded").reset_index(drop=True),
    )


@join_type
def test_join_with_post_expression_filter(how, left):
    lhs = left[["key", "key2"]]
    rhs = left[["key2", "value"]]

    joined = lhs.join(rhs, "key2", how=how)
    projected = joined.select(lhs, rhs.value)
    expr = projected.filter(projected.value == 4)
    result = expr.compile()

    df1 = lhs.compile()
    df2 = rhs.compile()
    expected = dd.merge(df1, df2, on="key2", how=how)
    expected = expected.loc[expected.value == 4].reset_index(drop=True)

    tm.assert_frame_equal(
        result.compute(scheduler="single-threaded"),
        expected.compute(scheduler="single-threaded"),
    )


@join_type
def test_multi_join_with_post_expression_filter(how, left, df1):
    lhs = left[["key", "key2"]]
    rhs = left[["key2", "value"]]
    rhs2 = left[["key2", "value"]].rename(value2="value")

    joined = lhs.join(rhs, "key2", how=how)
    projected = joined.select(lhs, rhs.value)
    filtered = projected.filter(projected.value == 4)

    joined2 = filtered.join(rhs2, "key2")
    projected2 = joined2.select(filtered.key, rhs2.value2)
    expr = projected2.filter(projected2.value2 == 3)

    result = expr.compile()

    df1 = lhs.compile()
    df2 = rhs.compile()
    df3 = rhs2.compile()
    expected = dd.merge(df1, df2, on="key2", how=how)
    expected = expected.loc[expected.value == 4].reset_index(drop=True)
    expected = dd.merge(expected, df3, on="key2")[["key", "value2"]]
    expected = expected.loc[expected.value2 == 3].reset_index(drop=True)

    tm.assert_frame_equal(
        result.compute(scheduler="single-threaded"),
        expected.compute(scheduler="single-threaded"),
    )


@join_type
def test_join_with_non_trivial_key(how, left, right, df1, df2):
    # also test that the order of operands in the predicate doesn't matter
    join = left.join(right, right.key.length() == left.key.length(), how=how)
    expr = join.select(left.key, left.value, right.other_value)
    result = expr.compile()

    expected = (
        dd.merge(
            df1.assign(key_len=df1.key.str.len()),
            df2.assign(key_len=df2.key.str.len()),
            on="key_len",
            how=how,
        )
        .drop(["key_len", "key_y", "key2", "key3"], axis=1)
        .rename(columns={"key_x": "key"})
    )
    tm.assert_frame_equal(
        result[expected.columns].compute(scheduler="single-threaded"),
        expected.compute(scheduler="single-threaded"),
    )


@join_type
def test_join_with_non_trivial_key_project_table(how, left, right, df1, df2):
    # also test that the order of operands in the predicate doesn't matter
    join = left.join(right, right.key.length() == left.key.length(), how=how)
    expr = join.select(left, right.other_value)
    expr = expr.filter(expr.key.length() == 1)
    result = expr.compile()

    expected = (
        dd.merge(
            df1.assign(key_len=df1.key.str.len()),
            df2.assign(key_len=df2.key.str.len()),
            on="key_len",
            how=how,
        )
        .drop(["key_len", "key_y", "key2", "key3"], axis=1)
        .rename(columns={"key_x": "key"})
    )
    expected = expected.loc[expected.key.str.len() == 1]
    tm.assert_frame_equal(
        result[expected.columns].compute(scheduler="single-threaded"),
        expected.compute(scheduler="single-threaded"),
    )


@join_type
def test_join_with_project_right_duplicate_column(client, how, left, df1, df3):
    # also test that the order of operands in the predicate doesn't matter
    right = client.table("df3")
    join = left.join(right, ["key"], how=how)
    expr = join.select(left.key, right.key2, right.other_value)
    result = expr.compile()

    expected = (
        dd.merge(df1, df3, on="key", how=how)
        .drop(["key2_x", "key3", "value"], axis=1)
        .rename(columns={"key2_y": "key2"})
    )
    tm.assert_frame_equal(
        result[expected.columns].compute(scheduler="single-threaded"),
        expected.compute(scheduler="single-threaded").reset_index(drop=True),
    )


merge_asof_minversion = pytest.mark.skipif(
    pd.__version__ < "0.19.2",
    reason="at least pandas-0.19.2 required for merge_asof",
)


@merge_asof_minversion
def test_asof_join(time_left, time_right, time_df1, time_df2):
    expr = time_left.asof_join(time_right, "time").select(
        time_left, time_right.other_value
    )
    result = expr.compile()
    expected = dd.merge_asof(time_df1, time_df2, on="time")
    tm.assert_frame_equal(
        result[expected.columns].compute(scheduler="single-threaded"),
        expected.compute(scheduler="single-threaded").reset_index(drop=True),
    )


@merge_asof_minversion
def test_keyed_asof_join(
    time_keyed_left, time_keyed_right, time_keyed_df1, time_keyed_df2
):
    expr = time_keyed_left.asof_join(time_keyed_right, "time", predicates="key").select(
        time_keyed_left, time_keyed_right.other_value
    )
    result = expr.compile()
    expected = dd.merge_asof(time_keyed_df1, time_keyed_df2, on="time", by="key")
    tm.assert_frame_equal(
        result[expected.columns].compute(scheduler="single-threaded"),
        expected.compute(scheduler="single-threaded").reset_index(drop=True),
    )


@merge_asof_minversion
def test_asof_join_overlapping_non_predicate(
    time_keyed_left, time_keyed_right, time_keyed_df1, time_keyed_df2
):
    # Add a junk column with a colliding name
    time_keyed_left = time_keyed_left.mutate(
        collide=time_keyed_left.key + time_keyed_left.value
    )
    time_keyed_right = time_keyed_right.mutate(
        collide=time_keyed_right.key + time_keyed_right.other_value
    )
    time_keyed_df1.assign(collide=time_keyed_df1["key"] + time_keyed_df1["value"])
    time_keyed_df2.assign(collide=time_keyed_df2["key"] + time_keyed_df2["other_value"])

    expr = time_keyed_left.asof_join(
        time_keyed_right, on="time", predicates=[("key", "key")]
    )
    result = expr.compile()
    expected = dd.merge_asof(
        time_keyed_df1, time_keyed_df2, on="time", by="key", suffixes=("", "_right")
    )
    tm.assert_frame_equal(
        result[expected.columns].compute(scheduler="single-threaded"),
        expected.compute(scheduler="single-threaded").reset_index(drop=True),
    )


@pytest.mark.parametrize(
    "how",
    [
        "left",
        "right",
        "inner",
        "outer",
    ],
)
@pytest.mark.parametrize(
    "func",
    [
        pytest.param(lambda join: join["a0", "a1"], id="tuple"),
        pytest.param(lambda join: join[["a0", "a1"]], id="list"),
        pytest.param(lambda join: join.select(["a0", "a1"]), id="select"),
    ],
)
def test_select_on_unambiguous_join(con, how, func):
    df_t = pd.DataFrame({"a0": [1, 2, 3], "b1": list("aab")})
    df_s = pd.DataFrame({"a1": [2, 3, 4], "b2": list("abc")})

    t = ibis.memtable(df_t)
    s = ibis.memtable(df_s)
    method = getattr(t, f"{how}_join")
    join = method(s, t.b1 == s.b2)
    expr = func(join)
    result = con.compile(expr).compute(scheduler="single-threaded")

    expected = pd.merge(df_t, df_s, left_on=["b1"], right_on=["b2"], how=how)[
        ["a0", "a1"]
    ]
    assert not expected.empty

    tm.assert_frame_equal(result, expected)


@pytest.mark.parametrize(
    "func",
    [
        pytest.param(lambda join: join["a0", "a1"], id="tuple"),
        pytest.param(lambda join: join[["a0", "a1"]], id="list"),
        pytest.param(lambda join: join.select(["a0", "a1"]), id="select"),
    ],
)
@merge_asof_minversion
def test_select_on_unambiguous_asof_join(func, npartitions):
    df_t = dd.from_pandas(
        pd.DataFrame({"a0": [1, 2, 3], "b1": date_range("20180101", periods=3)}),
        npartitions=npartitions,
    )
    df_s = dd.from_pandas(
        pd.DataFrame({"a1": [2, 3, 4], "b2": date_range("20171230", periods=3)}),
        npartitions=npartitions,
    )
    con = ibis.dask.connect({"t": df_t, "s": df_s})
    t = con.table("t")
    s = con.table("s")
    join = t.asof_join(s, t.b1 == s.b2)
    expected = dd.merge_asof(df_t, df_s, left_on=["b1"], right_on=["b2"])[["a0", "a1"]]
    assert not expected.compute(scheduler="single-threaded").empty
    expr = func(join)
    result = expr.compile()
    tm.assert_frame_equal(
        result.compute(scheduler="single-threaded"),
        expected.compute(scheduler="single-threaded").reset_index(drop=True),
    )


def test_outer_join(npartitions):
    df = dd.from_pandas(
        pd.DataFrame({"test": [1, 2, 3], "name": ["a", "b", "c"]}),
        npartitions=npartitions,
    )
    df_2 = dd.from_pandas(
        pd.DataFrame({"test_2": [1, 5, 6], "name_2": ["d", "e", "f"]}),
        npartitions=npartitions,
    )

    conn = ibis.dask.connect({"df": df, "df_2": df_2})

    ibis_table_1 = conn.table("df")
    ibis_table_2 = conn.table("df_2")

    joined = ibis_table_1.outer_join(
        ibis_table_2,
        predicates=ibis_table_1["test"] == ibis_table_2["test_2"],
    )
    result = joined.compile()
    expected = dd.merge(
        df,
        df_2,
        left_on="test",
        right_on="test_2",
        how="outer",
    )
    tm.assert_frame_equal(
        result.compute(scheduler="single-threaded"),
        expected.compute(scheduler="single-threaded").reset_index(drop=True),
    )
