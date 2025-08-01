# Copyright 2024 Marimo. All rights reserved.
from __future__ import annotations

import os
import random
import string
import sys
from typing import (
    TYPE_CHECKING,
    Callable,
    Optional,
    TypeVar,
)

if sys.version_info < (3, 10):
    from typing_extensions import ParamSpec, TypeAlias
else:
    from typing import ParamSpec, TypeAlias

from marimo import _loggers
from marimo._ast.cell import Cell, CellConfig
from marimo._ast.compiler import (
    cell_factory,
    context_cell_factory,
    ir_cell_factory,
    toplevel_cell_factory,
)
from marimo._ast.models import CellData
from marimo._ast.names import DEFAULT_CELL_NAME, SETUP_CELL_NAME
from marimo._ast.pytest import process_for_pytest
from marimo._schemas.serialization import (
    CellDef,
    SetupCell,
)
from marimo._types.ids import CellId_t

if TYPE_CHECKING:
    from collections.abc import Iterable
    from types import FrameType

    from marimo._ast.app import InternalApp

P = ParamSpec("P")
R = TypeVar("R")
Fn: TypeAlias = Callable[P, R]
Cls: TypeAlias = type
Obj: TypeAlias = "Cls | Fn[P, R]"

LOGGER = _loggers.marimo_logger()


class CellIdGenerator:
    def __init__(self, prefix: str = "") -> None:
        self.prefix = prefix
        self.random_seed = random.Random(42)
        self.seen_ids: set[CellId_t] = set()

    def create_cell_id(self) -> CellId_t:
        """Create a new unique cell ID.

        Returns:
            CellId_t: A new cell ID consisting of the manager's prefix followed by 4 random letters.
        """
        attempts = 0
        while attempts < 100:
            # 4 random letters
            _id = self.prefix + "".join(
                self.random_seed.choices(string.ascii_letters, k=4)
            )
            if _id not in self.seen_ids:
                self.seen_ids.add(CellId_t(_id))
                return CellId_t(_id)
            attempts += 1

        raise ValueError(
            f"Failed to create a unique cell ID after {attempts} attempts"
        )


class CellManager:
    """A manager for cells in a marimo notebook.

    The CellManager is responsible for:
    1. Creating and managing unique cell IDs
    2. Registering and storing cell data (code, configuration, etc.)
    3. Providing access to cell information through various queries
    4. Managing both valid (parsable) and unparsable cells
    5. Handling cell decorators for the notebook interface

    Attributes:
        prefix (str): A prefix added to all cell IDs managed by this instance
        unparsable (bool): Flag indicating if any unparsable cells were encountered
    """

    def __init__(self, prefix: str = "") -> None:
        """Initialize a new CellManager.

        Args:
            prefix (str, optional): Prefix to add to all cell IDs. Defaults to "".
        """
        self._cell_data: dict[CellId_t, CellData] = {}
        self.prefix = prefix
        self.unparsable = False
        self._cell_id_generator = CellIdGenerator(prefix)

    def create_cell_id(self) -> CellId_t:
        """Create a new unique cell ID.

        Returns:
            CellId_t: A new cell ID consisting of the manager's prefix followed by 4 random letters.
        """
        return self._cell_id_generator.create_cell_id()

    def cell_decorator(
        self,
        obj: Obj[P, R] | None,
        column: Optional[int],
        disabled: bool,
        hide_code: bool,
        app: InternalApp | None = None,
        *,
        top_level: bool = False,
    ) -> Cell | Obj[P, R] | Callable[[Obj[P, R]], Cell | Obj[P, R]]:
        """Create a cell decorator for marimo notebook cells."""
        # NB. marimo also statically loads notebooks via the marimo/_ast/load
        # path. This code is only called when run as a script or imported as a
        # module.
        cell_config = CellConfig(
            column=column, disabled=disabled, hide_code=hide_code
        )

        def _register(obj: Obj[P, R]) -> Cell | Obj[P, R]:
            # Use PYTEST_VERSION here, opposed to PYTEST_CURRENT_TEST, in
            # order to allow execution during test collection.
            is_top_level_pytest = (
                "PYTEST_VERSION" in os.environ
                and "PYTEST_CURRENT_TEST" not in os.environ
            ) or "MARIMO_PYTEST_WASM" in os.environ
            factory: Callable[..., Cell] = (
                toplevel_cell_factory if top_level else cell_factory
            )
            try:
                cell = factory(
                    obj,
                    cell_id=self.create_cell_id(),
                    anonymous_file=app._app._anonymous_file if app else False,
                    test_rewrite=is_top_level_pytest
                    or (app is not None and app._app._pytest_rewrite),
                )
            except TypeError as e:
                LOGGER.debug(
                    f"Failed to register cell: {e}. Expected class or function,"
                    f"got {type(obj)}."
                )
                # Top level definitions can wrap non-functions or classes.
                # Since static parsing makes it possible to load and create a
                # notebook like this, importing the notebooks shouldn't fail
                # either.
                if top_level:
                    return obj
                # If it is not a top-level definition, something is very wrong
                raise ValueError(
                    "Unexpected failure. Please report this error to "
                    "github.com/marimo-team/marimo/issues."
                ) from e

            cell._cell.configure(cell_config)
            self._register_cell(cell, app=app)

            # Top level functions are exposed as the function itself.
            if top_level:
                return obj

            # Manually set the signature for pytest.
            if is_top_level_pytest:
                # NB. in place metadata update.
                process_for_pytest(obj, cell)
            return cell

        if obj is None:
            # If the decorator was used with parentheses, func will be None,
            # and we return a decorator that takes the decorated function as an
            # argument
            def decorator(obj: Obj[P, R]) -> Cell | Obj[P, R]:
                return _register(obj)

            return decorator
        else:
            return _register(obj)

    def cell_context(
        self,
        frame: FrameType,
        app: InternalApp | None = None,
        config: Optional[CellConfig] = None,
    ) -> Cell:
        """Registers cells when called through a context block."""
        cell = context_cell_factory(
            cell_id=CellId_t(SETUP_CELL_NAME),
            # NB. carry along the frame from the initial call.
            frame=frame,
        )
        cell._cell.configure(config or CellConfig())
        self._register_cell(cell, app=app)
        return cell

    def _register_cell(
        self, cell: Cell, app: InternalApp | None = None
    ) -> None:
        if app is None:
            raise ValueError("app must not be None")
        if app is not None:
            cell._register_app(app)
        cell_impl = cell._cell
        self.register_cell(
            cell_id=cell_impl.cell_id,
            code=cell_impl.code,
            name=cell.name,
            config=cell_impl.config,
            cell=cell,
        )

    def register_cell(
        self,
        cell_id: Optional[CellId_t],
        code: str,
        config: Optional[CellConfig],
        name: str = DEFAULT_CELL_NAME,
        cell: Optional[Cell] = None,
    ) -> None:
        """Register a new cell with the manager.

        Args:
            cell_id: Unique identifier for the cell. If None, one will be generated
            code: The cell's source code
            config: Cell configuration (column, disabled state, etc.)
            name: Name of the cell, defaults to DEFAULT_CELL_NAME
            cell: Optional Cell object for valid cells
        """
        if cell_id is None:
            cell_id = self.create_cell_id()

        self._cell_data[cell_id] = CellData(
            cell_id=cell_id,
            code=code,
            name=name,
            config=config or CellConfig(),
            cell=cell,
        )

    def register_ir_cell(
        self, cell_def: CellDef, app: InternalApp | None = None
    ) -> None:
        if isinstance(cell_def, SetupCell):
            cell_id = CellId_t(SETUP_CELL_NAME)
        else:
            cell_id = self.create_cell_id()
        cell = ir_cell_factory(cell_def, cell_id=cell_id)
        cell_config = CellConfig.from_dict(
            cell_def.options,
        )
        cell._cell.configure(cell_config)
        self._register_cell(cell, app=app)

    def register_unparsable_cell(
        self,
        code: str,
        name: Optional[str],
        cell_config: CellConfig,
    ) -> None:
        """Register a cell that couldn't be parsed.

        Handles code formatting and registration of cells that couldn't be parsed
        into valid Python code.

        Args:
            code: The unparsable code string
            name: Optional name for the cell
            cell_config: Configuration for the cell
        """
        # If this is the first cell, and its name is setup, assume that it's
        # the setup cell.
        if len(self._cell_data) == 0 and name == SETUP_CELL_NAME:
            cell_id = CellId_t(SETUP_CELL_NAME)
        else:
            cell_id = self.create_cell_id()

        # - code.split("\n")[1:-1] disregards first and last lines, which are
        #   empty
        # - line[4:] removes leading indent in multiline string
        # - replace(...) unescapes double quotes
        # - rstrip() removes an extra newline
        code = "\n".join(
            [line[4:].replace('\\"', '"') for line in code.split("\n")[1:-1]]
        )

        self.register_cell(
            cell_id=cell_id,
            code=code,
            config=cell_config,
            name=name or DEFAULT_CELL_NAME,
            cell=None,
        )

    def ensure_one_cell(self) -> None:
        """Ensure at least one cell exists in the manager.

        If no cells exist, creates an empty cell with default configuration.
        """
        if not self._cell_data:
            cell_id = self.create_cell_id()
            self.register_cell(
                cell_id=cell_id,
                code="",
                config=CellConfig(),
            )

    def cell_name(self, cell_id: CellId_t) -> str:
        """Get the name of a cell by its ID.

        Args:
            cell_id: The ID of the cell

        Returns:
            str: The name of the cell

        Raises:
            KeyError: If the cell_id doesn't exist
        """
        return self._cell_data[cell_id].name

    def names(self) -> Iterable[str]:
        """Get an iterator over all cell names.

        Returns:
            Iterable[str]: Iterator yielding each cell's name
        """
        for cell_data in self._cell_data.values():
            yield cell_data.name

    def codes(self) -> Iterable[str]:
        """Get an iterator over all cell codes.

        Returns:
            Iterable[str]: Iterator yielding each cell's source code
        """
        for cell_data in self._cell_data.values():
            yield cell_data.code

    def configs(self) -> Iterable[CellConfig]:
        """Get an iterator over all cell configurations.

        Returns:
            Iterable[CellConfig]: Iterator yielding each cell's configuration
        """
        for cell_data in self._cell_data.values():
            yield cell_data.config

    def valid_cells(
        self,
    ) -> Iterable[tuple[CellId_t, Cell]]:
        """Get an iterator over all valid (parsable) cells.

        Returns:
            Iterable[tuple[CellId_t, Cell]]: Iterator yielding tuples of (cell_id, cell)
            for each valid cell
        """
        for cell_data in self._cell_data.values():
            if cell_data.cell is not None:
                yield (cell_data.cell_id, cell_data.cell)

    def valid_cell_ids(self) -> Iterable[CellId_t]:
        """Get an iterator over IDs of all valid cells.

        Returns:
            Iterable[CellId_t]: Iterator yielding cell IDs of valid cells
        """
        for cell_data in self._cell_data.values():
            if cell_data.cell is not None:
                yield cell_data.cell_id

    def cell_ids(self) -> Iterable[CellId_t]:
        """Get an iterator over all cell IDs in registration order.

        Returns:
            Iterable[CellId_t]: Iterator yielding all cell IDs
        """
        return self._cell_data.keys()

    def has_cell(self, cell_id: CellId_t) -> bool:
        """Check if a cell with the given ID exists.

        Args:
            cell_id: The ID to check

        Returns:
            bool: True if the cell exists, False otherwise
        """
        return cell_id in self._cell_data

    def cells(
        self,
    ) -> Iterable[Optional[Cell]]:
        """Get an iterator over all Cell objects.

        Returns:
            Iterable[Optional[Cell]]: Iterator yielding Cell objects (or None for invalid cells)
        """
        for cell_data in self._cell_data.values():
            yield cell_data.cell

    def config_map(self) -> dict[CellId_t, CellConfig]:
        """Get a mapping of cell IDs to their configurations.

        Returns:
            dict[CellId_t, CellConfig]: Dictionary mapping cell IDs to their configurations
        """
        return {cid: cd.config for cid, cd in self._cell_data.items()}

    def cell_data(self) -> Iterable[CellData]:
        """Get an iterator over all cell data.

        Returns:
            Iterable[CellData]: Iterator yielding CellData objects for all cells
        """
        return self._cell_data.values()

    def cell_data_at(self, cell_id: CellId_t) -> CellData:
        """Get the cell data for a specific cell ID.

        Args:
            cell_id: The ID of the cell to get data for

        Returns:
            CellData: The cell's data

        Raises:
            KeyError: If the cell_id doesn't exist
        """
        return self._cell_data[cell_id]

    def get_cell_code(self, cell_id: CellId_t) -> Optional[str]:
        """Get the code for a cell by its ID.

        Args:
            cell_id: The ID of the cell

        Returns:
            Optional[str]: The cell's code, or None if the cell doesn't exist
        """
        if cell_id not in self._cell_data:
            return None
        return self._cell_data[cell_id].code

    def get_cell_data(self, cell_id: CellId_t) -> Optional[CellData]:
        """Get the cell data for a specific cell ID.

        Args:
            cell_id: The ID of the cell to get data for

        Returns:
            Optional[CellData]: The cell's data, or None if the cell doesn't exist
        """
        if cell_id not in self._cell_data:
            LOGGER.debug(f"Cell with ID '{cell_id}' not found in cell manager")
            return None
        return self._cell_data[cell_id]

    def get_cell_data_by_name(self, name: str) -> Optional[CellData]:
        """Find a cell ID by its name.

        Args:
            name: The name to search for

        Returns:
            Optional[CellData]: The data of the first cell with matching name,
            or None if no match is found
        """
        for cell_data in self._cell_data.values():
            if cell_data.name.strip("*") == name:
                return cell_data
        return None

    def get_cell_id_by_code(self, code: str) -> Optional[CellId_t]:
        """Find a cell ID by its code content.

        Args:
            code: The code to search for

        Returns:
            Optional[CellId_t]: The ID of the first cell with matching code,
            or None if no match is found
        """
        for cell_id, cell_data in self._cell_data.items():
            if cell_data.code == code:
                return cell_id
        return None

    def sort_cell_ids_by_similarity(
        self, prev_cell_manager: CellManager
    ) -> None:
        """Sort cell IDs by similarity to the current cell manager.

        This mutates the current cell manager.
        """
        prev_ids = list(prev_cell_manager.cell_ids())
        prev_codes = [data.code for data in prev_cell_manager.cell_data()]
        current_ids = list(self._cell_data.keys())
        current_codes = [data.code for data in self.cell_data()]
        sorted_ids = _match_cell_ids_by_similarity(
            prev_ids, prev_codes, current_ids, current_codes
        )
        assert len(sorted_ids) == len(list(self.cell_ids()))

        # Create mapping from new to old ids
        id_mapping = dict(zip(sorted_ids, current_ids))

        # Update the cell data in place
        new_cell_data: dict[CellId_t, CellData] = {}
        for new_id, old_id in id_mapping.items():
            prev_cell_data = self._cell_data[old_id]
            prev_cell_data.cell_id = new_id
            new_cell_data[new_id] = prev_cell_data

        self._cell_data = new_cell_data

        # Add the new ids to the set, so we don't reuse them in the future
        for _id in sorted_ids:
            self._cell_id_generator.seen_ids.add(_id)

    @property
    def seen_ids(self) -> set[CellId_t]:
        return self._cell_id_generator.seen_ids


def _match_cell_ids_by_similarity(
    prev_ids: list[CellId_t],
    prev_codes: list[str],
    next_ids: list[CellId_t],
    next_codes: list[str],
) -> list[CellId_t]:
    """Match cell IDs based on code similarity.

    Args:
        prev_ids: List of previous cell IDs, used as the set of possible IDs
        prev_codes: List of previous cell codes
        next_ids: List of next cell IDs, used only when more cells than prev_ids
        next_codes: List of next cell codes

    Returns:
        List of cell IDs matching next_codes, using prev_ids where possible
    """
    assert len(prev_codes) == len(prev_ids)
    assert len(next_codes) == len(next_ids)

    # Initialize result and tracking sets
    result: list[Optional[CellId_t]] = [None] * len(next_codes)
    used_positions: set[int] = set()
    used_prev_ids: set[CellId_t] = set()

    # Track which next_ids are new (not in prev_ids)
    new_next_ids = [p_id for p_id in next_ids if p_id not in prev_ids]
    new_id_idx = 0

    # First pass: exact matches using hash map
    next_code_to_idx: dict[str, list[int]] = {}
    for idx, code in enumerate(next_codes):
        next_code_to_idx.setdefault(code, []).append(idx)

    for prev_idx, prev_code in enumerate(prev_codes):
        if prev_ids[prev_idx] in used_prev_ids:
            continue
        if prev_code in next_code_to_idx:
            # Use first available matching position
            for next_idx in next_code_to_idx[prev_code]:
                if next_idx not in used_positions:
                    result[next_idx] = prev_ids[prev_idx]
                    used_positions.add(next_idx)
                    used_prev_ids.add(prev_ids[prev_idx])
                    break

    # If all positions filled, we're done
    if len(used_positions) == len(next_codes):
        return [_id for _id in result if _id is not None]  # type: ignore

    def similarity_score(s1: str, s2: str) -> int:
        """Fast similarity score based on common prefix and suffix.
        Returns lower score for more similar strings."""
        # Find common prefix length
        prefix_len = 0
        for c1, c2 in zip(s1, s2):
            if c1 != c2:
                break
            prefix_len += 1

        # Find common suffix length if strings differ in middle
        if prefix_len < min(len(s1), len(s2)):
            s1_rev = s1[::-1]
            s2_rev = s2[::-1]
            suffix_len = 0
            for c1, c2 in zip(s1_rev, s2_rev):
                if c1 != c2:
                    break
                suffix_len += 1
        else:
            suffix_len = 0

        # Return inverse similarity - shorter common affix means higher score
        return len(s1) + len(s2) - 2 * (prefix_len + suffix_len)

    # Filter out used positions and ids for similarity matrix
    remaining_prev_indices = [
        i for i, pid in enumerate(prev_ids) if pid not in used_prev_ids
    ]
    remaining_next_indices = [
        i for i in range(len(next_codes)) if i not in used_positions
    ]

    # Create similarity matrix only for remaining cells
    similarity_matrix: list[list[int]] = []
    for prev_idx in remaining_prev_indices:
        row: list[int] = []
        for next_idx in remaining_next_indices:
            score = similarity_score(
                prev_codes[prev_idx], next_codes[next_idx]
            )
            row.append(score)
        similarity_matrix.append(row)

    # Second pass: best matches for remaining positions
    for matrix_prev_idx, prev_idx in enumerate(remaining_prev_indices):
        # Find best match among unused positions
        min_score = float("inf")  # type: ignore
        best_next_matrix_idx = None
        for matrix_next_idx, score in enumerate(
            similarity_matrix[matrix_prev_idx]
        ):
            if score < min_score:
                min_score = score
                best_next_matrix_idx = matrix_next_idx

        if best_next_matrix_idx is not None:
            next_idx = remaining_next_indices[best_next_matrix_idx]
            result[next_idx] = prev_ids[prev_idx]
            used_positions.add(next_idx)
            used_prev_ids.add(prev_ids[prev_idx])

    # Fill remaining positions with new next_ids
    for i in range(len(next_codes)):
        if result[i] is None:
            if new_id_idx < len(new_next_ids):
                result[i] = new_next_ids[new_id_idx]
                new_id_idx += 1

    return [_id for _id in result if _id is not None]  # type: ignore
