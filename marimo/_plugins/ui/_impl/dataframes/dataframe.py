# Copyright 2024 Marimo. All rights reserved.
from __future__ import annotations

import inspect
import sys
from dataclasses import dataclass
from typing import (
    Any,
    Callable,
    Final,
    Literal,
    Optional,
    Union,
)

from marimo._output.rich_help import mddoc
from marimo._plugins.ui._core.ui_element import UIElement
from marimo._plugins.ui._impl.dataframes.transforms.apply import (
    TransformsContainer,
    get_handler_for_dataframe,
)
from marimo._plugins.ui._impl.dataframes.transforms.types import (
    DataFrameType,
    Transformations,
)
from marimo._plugins.ui._impl.table import (
    SearchTableArgs,
    SearchTableResponse,
    SortArgs,
    TableSearchError,
)
from marimo._plugins.ui._impl.tables.table_manager import (
    FieldTypes,
    TableManager,
)
from marimo._plugins.ui._impl.tables.utils import (
    get_table_manager,
)
from marimo._plugins.validators import (
    validate_no_integer_columns,
    validate_page_size,
)
from marimo._runtime.functions import EmptyArgs, Function
from marimo._utils.memoize import memoize_last_value
from marimo._utils.parse_dataclass import parse_raw


@dataclass
class GetDataFrameResponse:
    url: str
    total_rows: Union[int, Literal["too_many"]]
    # Columns that are actually row headers
    # This really only applies to Pandas, that has special index columns
    row_headers: FieldTypes
    field_types: FieldTypes
    python_code: Optional[str] = None
    sql_code: Optional[str] = None


@dataclass
class GetColumnValuesArgs:
    column: str


@dataclass
class GetColumnValuesResponse:
    values: list[str | int | float]
    too_many_values: bool


class ColumnNotFound(Exception):
    def __init__(self, column: str):
        self.column = column
        super().__init__(f"Column {column} does not exist")


class GetDataFrameError(Exception):
    def __init__(self, error: str):
        self.error = error
        super().__init__(error)


@mddoc
class dataframe(UIElement[dict[str, Any], DataFrameType]):
    """Run transformations on a DataFrame or series.

    Currently only Pandas or Polars DataFrames are supported.

    Examples:
        ```python
        dataframe = mo.ui.dataframe(data)
        ```

    Attributes:
        value (DataFrameType): The transformed DataFrame or series.

    Args:
        df (DataFrameType): The DataFrame or series to transform.
        page_size (Optional[int], optional): The number of rows to show in the table.
            Defaults to 5.
        limit (Optional[int], optional): The number of items to load into memory, in case
            the data is remote and lazily fetched. This is likely true for SQL-backed
            dataframes via Ibis.
        on_change (Optional[Callable[[DataFrameType], None]], optional): Optional callback
            to run when this element's value changes.
    """

    _name: Final[str] = "marimo-dataframe"

    def __init__(
        self,
        df: DataFrameType,
        on_change: Optional[Callable[[DataFrameType], None]] = None,
        page_size: Optional[int] = 5,
        limit: Optional[int] = None,
    ) -> None:
        validate_no_integer_columns(df)
        # This will raise an error if the dataframe type is not supported.
        handler = get_handler_for_dataframe(df)

        # HACK: this is a hack to get the name of the variable that was passed
        dataframe_name = "df"
        try:
            frame = inspect.currentframe()
            if frame is not None and frame.f_back is not None:
                for (
                    var_name,
                    var_value,
                ) in frame.f_back.f_locals.items():
                    if var_value is df:
                        dataframe_name = var_name
                        break
        except Exception:
            pass

        self._limit = limit
        self._dataframe_name = dataframe_name
        self._data = df
        self._handler = handler
        self._manager = self._get_cached_table_manager(df, self._limit)
        self._transform_container = TransformsContainer[DataFrameType](
            df, handler
        )
        self._error: Optional[str] = None
        self._last_transforms = Transformations([])
        self._page_size = page_size or 5  # Default to 5 rows (.head())
        validate_page_size(self._page_size)

        super().__init__(
            component_name=dataframe._name,
            initial_value={
                "transforms": [],
            },
            on_change=on_change,
            label="",
            args={
                "columns": self._get_column_types(),
                "dataframe-name": dataframe_name,
                "total": self._manager.get_num_rows(force=False),
                "page-size": page_size,
            },
            functions=(
                Function(
                    name="get_dataframe",
                    arg_cls=EmptyArgs,
                    function=self._get_dataframe,
                ),
                Function(
                    name="get_column_values",
                    arg_cls=GetColumnValuesArgs,
                    function=self._get_column_values,
                ),
                Function(
                    name="search",
                    arg_cls=SearchTableArgs,
                    function=self._search,
                ),
            ),
        )

    def _get_column_types(self) -> list[list[Union[str, int]]]:
        return [
            [name, dtype[0], dtype[1]]
            for name, dtype in self._manager.get_field_types()
        ]

    def _get_dataframe(self, _args: EmptyArgs) -> GetDataFrameResponse:
        if self._error is not None:
            raise GetDataFrameError(self._error)

        manager = self._get_cached_table_manager(self._value, self._limit)
        response = self._search(
            SearchTableArgs(page_size=self._page_size, page_number=0)
        )
        return GetDataFrameResponse(
            url=str(response.data),
            total_rows=response.total_rows,
            row_headers=manager.get_row_headers(),
            field_types=manager.get_field_types(),
            python_code=self._handler.as_python_code(
                self._dataframe_name,
                # manager.get_column_names(),
                self._manager.get_column_names(),
                self._last_transforms.transforms,
            ),
            sql_code=self._handler.as_sql_code(manager.data),
        )

    def _get_column_values(
        self, args: GetColumnValuesArgs
    ) -> GetColumnValuesResponse:
        """Get all the unique values in a column."""
        LIMIT = 500

        columns = self._manager.get_column_names()
        if args.column not in columns:
            raise ColumnNotFound(args.column)

        # We get the unique values from the original dataframe, not the
        # transformed one
        unique_values = self._manager.get_unique_column_values(args.column)
        if len(unique_values) <= LIMIT:
            return GetColumnValuesResponse(
                values=list(sorted(unique_values, key=str)),
                too_many_values=False,
            )
        else:
            return GetColumnValuesResponse(
                values=[],
                too_many_values=True,
            )

    def _convert_value(self, value: dict[str, Any]) -> DataFrameType:
        if value is None:
            self._error = None
            return self._data

        try:
            transformations = parse_raw(value, Transformations)
            result = self._transform_container.apply(transformations)
            self._error = None
            self._last_transforms = transformations
            return result
        except Exception as e:
            error = f"Error applying dataframe transform: {str(e)}\n\n"
            sys.stderr.write(error)
            self._error = error
            return self._data

    def _search(self, args: SearchTableArgs) -> SearchTableResponse:
        offset = args.page_number * args.page_size

        # Apply filters, query, and functools.sort using the cached method
        result = self._apply_filters_query_sort(args.query, args.sort)

        # Save the manager to be used for selection
        try:
            data = result.take(args.page_size, offset).to_json_str()
        except BaseException as e:
            # Catch and re-raise the error as a non-BaseException
            # to avoid crashing the kernel
            raise TableSearchError(str(e)) from e

        return SearchTableResponse(
            data=data,
            total_rows=result.get_num_rows(force=True) or 0,
        )

    def _apply_filters_query_sort(
        self,
        query: Optional[str],
        sort: Optional[SortArgs],
    ) -> TableManager[Any]:
        result = self._get_cached_table_manager(self._value, self._limit)

        if query:
            result = result.search(query)

        if sort and sort.by in result.get_column_names():
            result = result.sort_values(sort.by, sort.descending)

        return result

    @memoize_last_value
    def _get_cached_table_manager(
        self, value: Any, limit: Optional[int]
    ) -> TableManager[Any]:
        tm = get_table_manager(value)
        if limit is not None:
            tm = tm.take(limit, 0)
        return tm
