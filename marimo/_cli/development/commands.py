# Copyright 2024 Marimo. All rights reserved.
from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click

from marimo._cli.print import orange
from marimo._server.session.serialize import (
    serialize_notebook,
    serialize_session_view,
)
from marimo._utils.code import hash_code

if TYPE_CHECKING:
    import psutil


def _generate_server_api_schema() -> dict[str, Any]:
    from starlette.schemas import SchemaGenerator

    import marimo._data.models as data
    import marimo._messaging.errors as errors
    import marimo._messaging.ops as ops
    import marimo._runtime.requests as requests
    import marimo._secrets.models as secrets_models
    import marimo._server.models.completion as completion
    import marimo._server.models.export as export
    import marimo._server.models.files as files
    import marimo._server.models.home as home
    import marimo._server.models.models as models
    import marimo._server.models.packages as packages
    import marimo._server.models.secrets as secrets
    import marimo._snippets.snippets as snippets
    from marimo._ast.cell import CellConfig, RuntimeStateType
    from marimo._config.config import MarimoConfig
    from marimo._messaging.cell_output import CellChannel, CellOutput
    from marimo._messaging.mimetypes import KnownMimeType
    from marimo._output.mime import MIME
    from marimo._plugins.core.web_component import JSONType
    from marimo._runtime.packages.package_manager import PackageDescription
    from marimo._server.api.router import build_routes
    from marimo._utils.dataclass_to_openapi import (
        PythonTypeToOpenAPI,
    )
    from marimo._version import __version__

    # dataclass components used in websocket messages
    # these are always snake_case
    MESSAGES = [
        # Base
        MIME,
        RuntimeStateType,
        KnownMimeType,
        CellChannel,
        data.NonNestedLiteral,
        data.DataType,
        CellConfig,
        MarimoConfig,
        # Errors
        errors.SetupRootError,
        errors.MultipleDefinitionError,
        errors.CycleError,
        errors.MultipleDefinitionError,
        errors.ImportStarError,
        errors.DeleteNonlocalError,
        errors.MarimoInterruptionError,
        errors.MarimoInternalError,
        errors.MarimoAncestorStoppedError,
        errors.MarimoAncestorPreventedError,
        errors.MarimoStrictExecutionError,
        errors.MarimoExceptionRaisedError,
        errors.MarimoSyntaxError,
        errors.UnknownError,
        errors.Error,
        # Outputs
        CellOutput,
        # Data
        data.DataTableColumn,
        data.DataTable,
        data.ColumnStats,
        data.DataSourceConnection,
        data.Schema,
        data.Database,
        # Secrets
        secrets_models.SecretKeysWithProvider,
        secrets.CreateSecretRequest,
        # Operations
        ops.CellOp,
        ops.HumanReadableStatus,
        ops.FunctionCallResult,
        ops.SendUIElementMessage,
        ops.RemoveUIElements,
        ops.Interrupted,
        ops.CompletedRun,
        ops.KernelReady,
        ops.CompletionResult,
        ops.Alert,
        ops.MissingPackageAlert,
        ops.InstallingPackageAlert,
        ops.Reconnected,
        ops.Banner,
        ops.Reload,
        ops.VariableDeclaration,
        ops.VariableValue,
        ops.Variables,
        ops.VariableValues,
        ops.Datasets,
        ops.DataColumnPreview,
        ops.SQLTablePreview,
        ops.SQLTableListPreview,
        ops.DataSourceConnections,
        ops.SecretKeysResult,
        ops.QueryParamsSet,
        ops.QueryParamsAppend,
        ops.QueryParamsDelete,
        ops.QueryParamsClear,
        ops.UpdateCellCodes,
        ops.UpdateCellIdsRequest,
        ops.FocusCell,
        ops.MessageOperation,
    ]

    # dataclass components used in requests/responses
    REQUEST_RESPONSES = [
        # Sub components
        home.MarimoFile,
        files.FileInfo,
        requests.ExecutionRequest,
        snippets.SnippetSection,
        snippets.Snippet,
        snippets.Snippets,
        requests.SetUIElementValueRequest,
        # Requests/responses
        completion.VariableContext,
        completion.SchemaColumn,
        completion.SchemaTable,
        completion.AiCompletionContext,
        completion.AiCompletionRequest,
        completion.AiInlineCompletionRequest,
        completion.ChatRequest,
        export.ExportAsHTMLRequest,
        export.ExportAsMarkdownRequest,
        export.ExportAsScriptRequest,
        export.ExportAsIPYNBRequest,
        files.FileCreateRequest,
        files.FileCreateResponse,
        files.FileDeleteRequest,
        files.FileDeleteResponse,
        files.FileDetailsRequest,
        files.FileDetailsResponse,
        files.FileListRequest,
        files.FileListResponse,
        files.FileMoveRequest,
        files.FileMoveResponse,
        files.FileOpenRequest,
        files.FileUpdateRequest,
        files.FileUpdateResponse,
        secrets.ListSecretKeysResponse,
        secrets.DeleteSecretRequest,
        packages.AddPackageRequest,
        PackageDescription,
        packages.ListPackagesResponse,
        packages.PackageOperationResponse,
        packages.RemovePackageRequest,
        packages.DependencyTreeNode,
        packages.DependencyTreeResponse,
        home.OpenTutorialRequest,
        home.RecentFilesResponse,
        home.RunningNotebooksResponse,
        home.ShutdownSessionRequest,
        home.WorkspaceFilesRequest,
        home.WorkspaceFilesResponse,
        models.BaseResponse,
        models.FormatRequest,
        models.FormatResponse,
        models.InstantiateRequest,
        models.ReadCodeResponse,
        models.RenameFileRequest,
        models.RunRequest,
        models.SaveAppConfigurationRequest,
        models.SaveNotebookRequest,
        models.CopyNotebookRequest,
        models.SaveUserConfigurationRequest,
        models.StdinRequest,
        models.SuccessResponse,
        models.SuccessResponse,
        models.UpdateComponentValuesRequest,
        models.InvokeAiToolRequest,
        models.InvokeAiToolResponse,
        requests.CodeCompletionRequest,
        requests.DeleteCellRequest,
        requests.ExecuteMultipleRequest,
        requests.ExecuteScratchpadRequest,
        requests.ExecuteStaleRequest,
        requests.ExecutionRequest,
        requests.FunctionCallRequest,
        requests.InstallMissingPackagesRequest,
        requests.ListSecretKeysRequest,
        requests.PdbRequest,
        requests.PreviewDatasetColumnRequest,
        requests.PreviewSQLTableListRequest,
        requests.PreviewDataSourceConnectionRequest,
        requests.PreviewSQLTableRequest,
        requests.RenameRequest,
        requests.SetCellConfigRequest,
        requests.SetModelMessageRequest,
        requests.SetUserConfigRequest,
        requests.StopRequest,
    ]

    processed_classes: dict[Any, str] = {
        JSONType: "JSONType",
    }
    component_schemas: dict[str, Any] = {
        # Hand-written schema to avoid circular dependencies
        "JSONType": {
            "oneOf": [
                {"type": "string"},
                {"type": "number"},
                {"type": "object"},
                {"type": "array"},
                {"type": "boolean"},
                {"type": "null"},
            ]
        },
        "HTTPRequest": {"type": "null"},
    }
    # We must override the names of some Union Types,
    # otherwise, their __name__ is "Union"
    name_overrides: dict[Any, str] = {
        JSONType: "JSONType",
        errors.Error: "Error",
        KnownMimeType: "MimeType",
        data.DataType: "DataType",
        data.NonNestedLiteral: "NonNestedLiteral",
        RuntimeStateType: "RuntimeState",
        CellChannel: "CellChannel",
        ops.MessageOperation: "MessageOperation",
    }

    converter = PythonTypeToOpenAPI(
        camel_case=False, name_overrides=name_overrides
    )
    for cls in MESSAGES:
        # Remove self from the list
        # since it may not have been processed yet
        if cls in processed_classes:
            del processed_classes[cls]
        name = name_overrides.get(cls, cls.__name__)  # type: ignore[attr-defined]
        component_schemas[name] = converter.convert(cls, processed_classes)
        processed_classes[cls] = name

    converter = PythonTypeToOpenAPI(
        camel_case=True, name_overrides=name_overrides
    )
    for cls in REQUEST_RESPONSES:
        # Remove self from the list
        # since it may not have been processed yet
        if cls in processed_classes:
            del processed_classes[cls]
        name = name_overrides.get(cls, cls.__name__)  # type: ignore[attr-defined]
        component_schemas[name] = converter.convert(cls, processed_classes)
        processed_classes[cls] = name

    schemas = SchemaGenerator(
        {
            "openapi": "3.1.0",
            "info": {"title": "marimo API", "version": __version__},
            "components": {
                "schemas": {
                    **component_schemas,
                }
            },
        }
    )

    return schemas.get_schema(routes=build_routes())


@click.group(
    help="""Various commands for the marimo development.""", hidden=True
)
def development() -> None:
    pass


@click.command(help="""Print the marimo OpenAPI schema""")
def openapi() -> None:
    """
    Example usage:

        marimo development openapi
    """
    import yaml

    click.echo(
        yaml.dump(_generate_server_api_schema(), default_flow_style=False)
    )


@click.group(help="Various commands for the marimo processes", hidden=True)
def ps() -> None:
    pass


def get_marimo_processes() -> list[psutil.Process]:
    import psutil

    def is_marimo_process(proc: psutil.Process) -> bool:
        if proc.name() == "marimo":
            return True

        if proc.name().lower() == "python":
            try:
                cmds = proc.cmdline()
            except psutil.AccessDenied:
                return False
            except psutil.ZombieProcess:
                return False
            # any endswith marimo
            has_marimo = any(x.endswith("marimo") for x in cmds)
            # any command equals "tutorial", "edit", or "run"
            has_running_command = any(
                x in {"run", "tutorial", "edit"} for x in cmds
            )
            return has_marimo and has_running_command

        return False

    result: list[psutil.Process] = []

    for proc in psutil.process_iter():
        if is_marimo_process(proc):
            result.append(proc)

    return result


@ps.command(help="List the marimo processes", name="list")
def list_processes() -> None:
    """
    Example usage:

        marimo development ps list
    """
    # pretty print processes
    result = get_marimo_processes()
    for proc in result:
        cmds = proc.cmdline()
        cmd = " ".join(cmds[1:])
        click.echo(f"PID: {orange(str(proc.pid))} | {cmd}")


@ps.command(help="Kill the marimo processes")
def killall() -> None:
    """
    Example usage:

        marimo development ps killall
    """

    for proc in get_marimo_processes():
        # Ignore self
        if proc.pid == os.getpid():
            continue
        proc.kill()
        click.echo(f"Killed process {proc.pid}")

    click.echo("Killed all marimo processes")


@click.command(
    help="Inline packages according to PEP 723", name="inline-packages"
)
@click.argument(
    "name",
    required=True,
    type=click.Path(
        path_type=Path, exists=True, file_okay=True, dir_okay=False
    ),
)
def inline_packages(name: Path) -> None:
    """
    Example usage:

        marimo development inline-packages

    This uses some heuristics to guess the package names from the imports in
    the file.

    Requires uv.
    Installation: https://docs.astral.sh/uv/getting-started/installation/
    """
    from marimo._dependencies.dependencies import DependencyManager
    from marimo._runtime.packages.module_name_to_pypi_name import (
        module_name_to_pypi_name,
    )

    # Validate uv is installed
    if not DependencyManager.which("uv"):
        raise click.UsageError(
            "uv is not installed. See https://docs.astral.sh/uv/getting-started/installation/"
        )

    # Validate the file exists
    if not name.exists():
        raise click.FileError(str(name))

    # Validate >=3.10 for sys.stdlib_module_names
    if sys.version_info < (3, 10):
        # TOD: add support for < 3.10
        # We can use https://github.com/omnilib/stdlibs
        # to get the stdlib module names
        raise click.UsageError("Requires Python >=3.10")

    package_names = module_name_to_pypi_name()

    def get_pypi_package_names() -> list[str]:
        tree = ast.parse(name.read_text(encoding="utf-8"), filename=name)

        imported_modules = set[str]()

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported_modules.add(node.module.split(".")[0])

        pypi_names = [
            package_names.get(mod, mod.replace("_", "-"))
            for mod in imported_modules
        ]

        return pypi_names

    def is_stdlib_module(module_name: str) -> bool:
        return module_name in sys.stdlib_module_names

    pypi_names = get_pypi_package_names()

    # Filter out python distribution packages
    pypi_names = [name for name in pypi_names if not is_stdlib_module(name)]

    click.echo(f"Inlining packages: {pypi_names}")
    click.echo(f"into script: {name}")
    subprocess.run(
        [
            "uv",
            "add",
            "--script",
            str(name),
        ]
        + pypi_names
    )


@click.command(help="Print all routes")
def print_routes() -> None:
    from starlette.applications import Starlette
    from starlette.routing import Mount, Route, Router

    from marimo._server.main import create_starlette_app

    app = create_starlette_app(base_url="")

    def print_all_routes(app: Any, base_path: str = "") -> None:
        if not isinstance(app, (Starlette, Router)):
            return
        for route in app.routes:
            if isinstance(route, Route) and route.methods is not None:
                full_path = base_path + route.path
                for method in route.methods:
                    if method == "HEAD":
                        continue
                    click.echo(f"{method} {full_path}")
            elif isinstance(route, Mount) and route.app is not None:
                # Recursively append base path for mounted apps
                new_base_path = base_path + route.path
                print_all_routes(route.app, new_base_path)

    print_all_routes(app)
    return


@click.command(help="Preview a marimo file as static HTML")
@click.argument(
    "file_path",
    required=True,
    type=click.Path(
        path_type=Path, exists=True, file_okay=True, dir_okay=False
    ),
)
@click.option(
    "--port",
    default=8080,
    help="Port to serve the preview on",
    type=int,
)
@click.option(
    "--host",
    default="localhost",
    help="Host to serve the preview on",
    type=str,
)
@click.option(
    "--headless",
    is_flag=True,
    default=False,
    help="Don't automatically open the browser",
)
def preview(file_path: Path, port: int, host: str, headless: bool) -> None:
    """
    Preview a marimo file as static HTML.

    Creates a static HTML export of the marimo file and serves it
    on a simple HTTP server for preview purposes.

    Example usage:
        marimo development preview my_notebook.py
        marimo development preview my_notebook.py --port 8000
    """
    import threading
    import webbrowser

    import uvicorn
    from starlette.applications import Starlette
    from starlette.responses import HTMLResponse
    from starlette.routing import Route
    from starlette.staticfiles import StaticFiles

    from marimo._ast.app_config import _AppConfig
    from marimo._config.config import DEFAULT_CONFIG
    from marimo._server.templates.templates import static_notebook_template
    from marimo._server.tokens import SkewProtectionToken
    from marimo._utils.paths import marimo_package_path

    if TYPE_CHECKING:
        from starlette.requests import Request

    try:
        # Run the notebook to get actual outputs
        click.echo(f"Running notebook {file_path.name}...")
        from marimo._server.export import run_app_until_completion
        from marimo._server.file_router import AppFileRouter
        from marimo._server.utils import asyncio_run
        from marimo._utils.marimo_path import MarimoPath

        # Create file manager for the notebook
        file_router = AppFileRouter.from_filename(MarimoPath(file_path))
        file_key = file_router.get_unique_file_key()
        assert file_key is not None
        file_manager = file_router.get_file_manager(file_key)

        # Run the notebook to completion and get session view
        session_view, did_error = asyncio_run(
            run_app_until_completion(
                file_manager,
                cli_args={},
                argv=None,
            )
        )
        if did_error:
            click.echo(
                "Warning: Some cells had errors during execution", err=True
            )

        # Create session snapshot from the executed session
        session_snapshot = serialize_session_view(
            session_view,
            cell_ids=list(file_manager.app.cell_manager.cell_ids()),
        )

        # Get notebook snapshot from file manager
        notebook_snapshot = serialize_notebook(
            session_view, file_manager.app.cell_manager
        )

        # Get the static assets directory
        static_root = marimo_package_path() / "_static"

        # Get base HTML template
        template_path = static_root / "index.html"

        html_template = template_path.read_text(encoding="utf-8")

        # Use local assets instead of CDN
        asset_url = f"http://{host}:{port}"
        code = file_path.read_text(encoding="utf-8")

        # Generate static HTML
        html_content = static_notebook_template(
            html=html_template,
            user_config=DEFAULT_CONFIG,
            config_overrides={},
            server_token=SkewProtectionToken("preview"),
            app_config=_AppConfig(),
            filepath=str(file_path),
            code=code,
            session_snapshot=session_snapshot,
            code_hash=hash_code(code),
            notebook_snapshot=notebook_snapshot,
            files={},
            asset_url=asset_url,
        )

        click.echo(f"Creating preview for {file_path.name}")

        async def serve_html(request: Request) -> HTMLResponse:
            del request
            return HTMLResponse(html_content)

        # Create Starlette app
        app = Starlette(
            routes=[
                Route("/", serve_html),
                Route("/index.html", serve_html),
            ]
        )

        # Mount static files for assets
        app.mount(
            "/assets",
            StaticFiles(directory=static_root / "assets"),
            name="assets",
        )

        # Mount other static files (favicon, icons, manifest, etc.)
        app.mount(
            "/",
            StaticFiles(directory=static_root, html=False),
            name="static",
        )

        url = f"http://{host}:{port}"
        click.echo(f"Serving preview at {url}")
        click.echo("Press Ctrl+C to stop the server")

        # Open browser if requested
        if not headless:

            def open_browser() -> None:
                webbrowser.open(url)

            timer = threading.Timer(1.0, open_browser)
            timer.start()

        # Run the server
        uvicorn.run(app, host=host, port=port, log_level="error")

    except Exception as e:
        click.echo(f"Error creating preview: {e}", err=True)
        raise click.Abort() from e


development.add_command(inline_packages)
development.add_command(openapi)
development.add_command(ps)
development.add_command(print_routes)
development.add_command(preview)
