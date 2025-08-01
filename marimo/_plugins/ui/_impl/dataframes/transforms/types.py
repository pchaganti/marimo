# Copyright 2024 Marimo. All rights reserved.
from __future__ import annotations

import abc
from dataclasses import dataclass
from enum import Enum
from typing import (
    Any,
    Generic,
    Literal,
    Optional,
    TypeVar,
    Union,
)

# Could be a DataFrame from pandas, polars, pyarrow, DataFrameProtocol, etc.
DataFrameType = TypeVar("DataFrameType")

ColumnId = Union[str, int]
ColumnIds = list[ColumnId]
NumpyDataType = str
Operator = Literal[
    "==",
    "!=",
    "<",
    ">",
    "<",
    "<=",
    ">=",
    "is_true",
    "is_false",
    "is_null",
    "is_not_null",
    "equals",
    "does_not_equal",
    "contains",
    "regex",
    "starts_with",
    "ends_with",
    "in",
]
Aggregation = Literal[
    "count",
    "sum",
    "mean",
    "median",
    "min",
    "max",
]
UniqueKeep = Literal["first", "last", "none", "any"]


class TransformType(Enum):
    AGGREGATE = "aggregate"
    COLUMN_CONVERSION = "column_conversion"
    FILTER_ROWS = "filter_rows"
    GROUP_BY = "group_by"
    RENAME_COLUMN = "rename_column"
    SELECT_COLUMNS = "select_columns"
    SORT_COLUMN = "sort_column"
    SHUFFLE_ROWS = "shuffle_rows"
    SAMPLE_ROWS = "sample_rows"
    EXPLODE_COLUMNS = "explode_columns"
    EXPAND_DICT = "expand_dict"
    UNIQUE = "unique"


@dataclass(frozen=True)
class Condition:
    column_id: ColumnId
    operator: Operator
    value: Optional[Any] = None

    def __hash__(self) -> int:
        return hash((self.column_id, self.operator, self.value))

    def __post_init__(self) -> None:
        if self.operator == "in":
            if isinstance(self.value, list):
                # Hack to convert to tuple for frozen dataclass
                # Only tuples can be hashed
                object.__setattr__(self, "value", tuple(self.value))
            elif isinstance(self.value, tuple):
                pass
            else:
                raise ValueError(
                    "value must be a list or tuple for 'in' operator"
                )


@dataclass
class ColumnConversionTransform:
    type: Literal[TransformType.COLUMN_CONVERSION]
    column_id: ColumnId
    data_type: NumpyDataType
    errors: Literal["ignore", "raise"]


@dataclass
class RenameColumnTransform:
    type: Literal[TransformType.RENAME_COLUMN]
    column_id: ColumnId
    new_column_id: ColumnId


@dataclass
class SortColumnTransform:
    type: Literal[TransformType.SORT_COLUMN]
    column_id: ColumnId
    ascending: bool
    na_position: Literal["first", "last"]


@dataclass
class FilterRowsTransform:
    type: Literal[TransformType.FILTER_ROWS]
    operation: Literal["keep_rows", "remove_rows"]
    where: list[Condition]


@dataclass
class GroupByTransform:
    type: Literal[TransformType.GROUP_BY]
    column_ids: ColumnIds
    drop_na: bool
    aggregation: Aggregation


@dataclass
class AggregateTransform:
    type: Literal[TransformType.AGGREGATE]
    column_ids: ColumnIds
    aggregations: list[Aggregation]


@dataclass
class SelectColumnsTransform:
    type: Literal[TransformType.SELECT_COLUMNS]
    column_ids: ColumnIds


@dataclass
class ShuffleRowsTransform:
    type: Literal[TransformType.SHUFFLE_ROWS]
    seed: int


@dataclass
class SampleRowsTransform:
    type: Literal[TransformType.SAMPLE_ROWS]
    n: int
    replace: bool
    seed: int


@dataclass
class ExplodeColumnsTransform:
    type: Literal[TransformType.EXPLODE_COLUMNS]
    column_ids: ColumnIds


@dataclass
class ExpandDictTransform:
    type: Literal[TransformType.EXPAND_DICT]
    column_id: ColumnId


@dataclass
class UniqueTransform:
    type: Literal[TransformType.UNIQUE]
    column_ids: ColumnIds
    keep: UniqueKeep


Transform = Union[
    AggregateTransform,
    ColumnConversionTransform,
    FilterRowsTransform,
    GroupByTransform,
    RenameColumnTransform,
    SelectColumnsTransform,
    SortColumnTransform,
    ShuffleRowsTransform,
    SampleRowsTransform,
    ExplodeColumnsTransform,
    ExpandDictTransform,
    UniqueTransform,
]


@dataclass
class Transformations:
    transforms: list[Transform]


T = TypeVar("T")


class TransformHandler(abc.ABC, Generic[T]):
    @staticmethod
    @abc.abstractmethod
    def handle_column_conversion(
        df: T, transform: ColumnConversionTransform
    ) -> T:
        raise NotImplementedError

    @staticmethod
    @abc.abstractmethod
    def handle_rename_column(df: T, transform: RenameColumnTransform) -> T:
        raise NotImplementedError

    @staticmethod
    @abc.abstractmethod
    def handle_sort_column(df: T, transform: SortColumnTransform) -> T:
        raise NotImplementedError

    @staticmethod
    @abc.abstractmethod
    def handle_filter_rows(df: T, transform: FilterRowsTransform) -> T:
        raise NotImplementedError

    @staticmethod
    @abc.abstractmethod
    def handle_group_by(df: T, transform: GroupByTransform) -> T:
        raise NotImplementedError

    @staticmethod
    @abc.abstractmethod
    def handle_aggregate(df: T, transform: AggregateTransform) -> T:
        raise NotImplementedError

    @staticmethod
    @abc.abstractmethod
    def handle_select_columns(df: T, transform: SelectColumnsTransform) -> T:
        raise NotImplementedError

    @staticmethod
    @abc.abstractmethod
    def handle_shuffle_rows(df: T, transform: ShuffleRowsTransform) -> T:
        raise NotImplementedError

    @staticmethod
    @abc.abstractmethod
    def handle_sample_rows(df: T, transform: SampleRowsTransform) -> T:
        raise NotImplementedError

    @staticmethod
    @abc.abstractmethod
    def handle_explode_columns(df: T, transform: ExplodeColumnsTransform) -> T:
        raise NotImplementedError

    @staticmethod
    @abc.abstractmethod
    def handle_expand_dict(df: T, transform: ExpandDictTransform) -> T:
        raise NotImplementedError

    @staticmethod
    @abc.abstractmethod
    def handle_unique(df: T, transform: UniqueTransform) -> T:
        raise NotImplementedError

    @staticmethod
    def as_python_code(
        df_name: str, columns: list[str], transforms: list[Transform]
    ) -> str | None:
        del df_name, transforms, columns
        return None

    @staticmethod
    def as_sql_code(transformed_df: T) -> str | None:
        del transformed_df
        return None
