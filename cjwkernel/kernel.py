import io
import logging
import os
import os.path
import selectors
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import pyspawner
import thrift.protocol.TBinaryProtocol
import thrift.transport.TTransport
from cjwkernel.chroot import READONLY_CHROOT_DIR, ChrootContext
from cjwkernel.errors import ModuleExitedError, ModuleTimeoutError
from cjwkernel.thrift import ttypes
from cjwkernel.types import (
    ArrowTable,
    CompiledModule,
    FetchResult,
    Params,
    RawParams,
    RenderResult,
    Tab,
    arrow_arrow_table_to_thrift,
    arrow_fetch_result_to_thrift,
    arrow_params_to_thrift,
    arrow_raw_params_to_thrift,
    arrow_tab_to_thrift,
    thrift_fetch_result_to_arrow,
    thrift_raw_params_to_arrow,
    thrift_render_result_to_arrow,
)
from cjwkernel.validate import ValidateError

logger = logging.getLogger(__name__)


TIMEOUT = 600  # seconds
DEAD_PROCESS_N_WAITS = 50  # number of waitpid() calls after process exits
DEAD_PROCESS_WAIT_POLL_INTERVAL = 0.02  # seconds between waitpid() calls
LOG_BUFFER_MAX_BYTES = 100 * 1024  # waaaay too much log output
OUTPUT_BUFFER_MAX_BYTES = (
    2 * 1024 * 1024
)  # a huge migrate_params() return value, perhaps?

# Import all encodings. Some modules (e.g., loadurl) encounter weird stuff
ENCODING_IMPORTS = [
    "encodings." + p.stem
    for p in Path("/usr/local/lib/python3.8/encodings").glob("*.py")
    if p.stem not in {"cp65001", "mbcs", "oem"}  # un-importable
]


@dataclass
class ChildReader:
    fileno: int
    """File descriptor to read from.

    ChildReader won't call `os.close(fileno)` when closing; be sure
    you close `fileno` elsewhere.
    """

    limit_bytes: int
    bytesio: io.BytesIO = field(default_factory=io.BytesIO)
    overflowed: bool = False
    eof: bool = False

    def __post_init__(self):
        os.set_blocking(self.fileno, False)

    def ingest(self):
        if self.eof:
            return
        allowed = self.limit_bytes - len(self.buffer)
        while allowed > 0:
            try:
                b = os.read(self.fileno, allowed)
            except BlockingIOError:
                return  # that's all for now
            if not b:
                self.eof = True
                return  # EOF
            self.bytesio.write(b)
            allowed -= len(b)
        # Detect overflow by reading one more byte
        if not self.overflowed:
            try:
                b = os.read(self.fileno, 1)
            except BlockingIOError:
                return
            if b:
                self.overflowed = True
            else:
                self.eof = True
        # Read all overflowed data (and ignore it), so the program does not
        # stall because a buffer is full
        if self.overflowed:
            while True:
                try:
                    b = os.read(self.fileno, 50 * 1024)
                except BlockingIOError:
                    return  # that's all for now
                if not b:
                    self.eof = True
                    return  # EOF

    @property
    def buffer(self):
        return self.bytesio.getbuffer()

    def to_str(self) -> str:
        return str(self.buffer, encoding="utf-8", errors="replace")


class Kernel:
    """Compiles and runs user-supplied module code.

    Here's the thing about user code: it can only be run in a sandbox.
    `compile()` is safe, but `exec()` is dangerous -- after running user code,
    the entire process must be killed: otherwise, the module may leak one
    workflow's data into another workflow (intentionally or not).

    The solution: "pyspawner". One "pyspawner" process loads 100MB of Python
    deps and then idles. The "compile" method compiles a user's module, then
    forks and evaluates it in a child process to ensure sanity. The
    "migrate_params", "render" and "fetch" methods fork, evaluate the user's
    module, then invoke that user's `migrate_params()`, `render()` or `fetch`.

    Child processes cannot be trusted to return sane values. So we communicate
    via Thrift (which errors on unexpected data) rather than Python pickle
    (which executes code on unexpected data).
    """

    def __init__(
        self,
        validate_timeout: float = TIMEOUT,
        migrate_params_timeout: float = TIMEOUT,
        fetch_timeout: float = TIMEOUT,
        render_timeout: float = TIMEOUT,
    ):
        self.validate_timeout = validate_timeout
        self.migrate_params_timeout = migrate_params_timeout
        self.fetch_timeout = fetch_timeout
        self.render_timeout = render_timeout
        self._pyspawner = pyspawner.Client(
            child_main="cjwkernel.pandas.main.main",
            executable="/opt/venv/cjwkernel/bin/python",
            environment={
                # SECURITY: children inherit these values
                "LANG": "C.UTF-8",
                "HOME": "/",
                "VIRTUAL_ENV": "/opt/venv/cjwkernel",
                # [adamhooper, 2019-10-19] rrrgh, OpenBLAS....
                #
                # If we preload numpy, we're in trouble. Numpy loads OpenBLAS,
                # and OpenBLAS starts a whole threading subsystem ... which
                # breaks fork() in our modules. (We use fork() to open Parquet
                # files....) OPENBLAS_NUM_THREADS=1 disables the thread pool.
                #
                # I'm frustrated.
                "OPENBLAS_NUM_THREADS": "1",
            },
            preload_imports=[
                "_strptime",
                "abc",
                "asyncio",
                "base64",
                "collections",
                "concurrent",
                "concurrent.futures",
                "concurrent.futures.thread",
                "dataclasses",
                "datetime",
                "enum",
                "functools",
                "inspect",
                "itertools",
                "json",
                "math",
                "multiprocessing",
                "multiprocessing.connection",
                "multiprocessing.popen_fork",
                "os.path",
                "re",
                "sqlite3",
                "ssl",
                "string",
                "tarfile",
                "typing",
                "urllib.parse",
                "warnings",
                "bs4",
                "formulas",
                "formulas.functions.operators",
                "formulas.parser",
                "html5lib",
                "html5lib.constants",
                "html5lib.filters",
                "html5lib.filters.whitespace",
                "html5lib.treewalkers.etree",
                "idna.uts46data",
                "lxml",
                "lxml.etree",
                "lxml.html",
                "lxml.html.html5parser",
                "lz4",
                "lz4.frame",
                "numpy",
                "nltk",
                "nltk.corpus",
                "nltk.sentiment.vader",
                "oauthlib",
                "oauthlib.oauth1",
                "oauthlib.oauth2",
                "pandas",
                "pandas.core",
                "pandas.core.apply",
                "pandas.core.computation.expressions",
                "pandas.core.groupby.categorical",
                "pyarrow",
                "pyarrow.pandas_compat",
                "pyarrow.parquet",
                "pytz",
                "re2",
                "schedula.dispatcher",
                "schedula.utils.blue",
                "schedula.utils.sol",
                "thrift.protocol.TBinaryProtocol",
                "thrift.transport.TTransport",
                *ENCODING_IMPORTS,
                "cjwkernel.pandas.main",
                "cjwkernel.pandas.module",
                "cjwmodule",
                "cjwmodule.i18n",
                "cjwmodule.http.client",
                "cjwmodule.http.httpfile",
                "cjwmodule.util",
                "cjwparquet",
                "cjwparse.api",
            ],
        )

    def __del__(self):
        self._pyspawner.close()

    def validate(self, compiled_module: CompiledModule) -> None:
        """Detect common errors in the user's code.

        Raise ModuleExitedError or ModuleTimeoutError on error.
        """
        self._run_in_child(
            chroot_dir=READONLY_CHROOT_DIR,
            network_config=None,
            compiled_module=compiled_module,
            timeout=self.validate_timeout,
            result=ttypes.ValidateModuleResult(),
            function="validate_thrift",
            args=[],
        )

    def migrate_params(
        self, compiled_module: CompiledModule, params: Dict[str, Any]
    ) -> None:
        """Call a module's migrate_params()."""
        request = arrow_raw_params_to_thrift(RawParams(params))
        response = self._run_in_child(
            chroot_dir=READONLY_CHROOT_DIR,
            network_config=None,
            compiled_module=compiled_module,
            timeout=self.migrate_params_timeout,
            result=ttypes.RawParams(),
            function="migrate_params_thrift",
            args=[request],
        )
        return thrift_raw_params_to_arrow(response).params

    def render(
        self,
        compiled_module: CompiledModule,
        chroot_context: ChrootContext,
        basedir: Path,
        input_table: ArrowTable,
        params: Params,
        tab: Tab,
        fetch_result: Optional[FetchResult],
        output_filename: str,
    ) -> RenderResult:
        """Run the module's `render_thrift()` function and return its result.

        Raise ModuleError if the module has a bug.
        """
        chroot_dir = chroot_context.chroot.root
        basedir_seen_by_module = Path("/") / basedir.relative_to(chroot_dir)
        request = ttypes.RenderRequest(
            str(basedir_seen_by_module),
            arrow_arrow_table_to_thrift(input_table),
            arrow_params_to_thrift(params),
            arrow_tab_to_thrift(tab),
            (
                None
                if fetch_result is None
                else arrow_fetch_result_to_thrift(fetch_result)
            ),
            output_filename,
        )
        try:
            with chroot_context.writable_file(basedir / output_filename):
                result = self._run_in_child(
                    chroot_dir=chroot_dir,
                    network_config=pyspawner.NetworkConfig(),  # TODO disallow networking
                    compiled_module=compiled_module,
                    timeout=self.render_timeout,
                    result=ttypes.RenderResult(),
                    function="render_thrift",
                    args=[request],
                )
        finally:
            chroot_context.clear_unowned_edits()

        if result.table.filename and result.table.filename != output_filename:
            raise ModuleExitedError(
                compiled_module.module_slug, 0, "Module wrote to wrong output file"
            )

        try:
            # thrift_render_result_to_arrow() verifies all filenames passed by
            # the module are in the directory the module has access to. It
            # assumes the Arrow file (if there is one) is untrusted, so it can
            # raise ValidateError
            render_result = thrift_render_result_to_arrow(result, basedir)
        except ValidateError as err:
            raise ModuleExitedError(
                compiled_module.module_slug,
                0,
                "Module produced invalid data: %s" % str(err),
            )
        return render_result

    def fetch(
        self,
        compiled_module: CompiledModule,
        chroot_context: ChrootContext,
        basedir: Path,
        params: Params,
        secrets: Dict[str, Any],
        last_fetch_result: Optional[FetchResult],
        input_parquet_filename: Optional[str],
        output_filename: str,
    ) -> FetchResult:
        """Run the module's `fetch_thrift()` function and return its result.

        Raise ModuleError if the module has a bug.
        """
        chroot_dir = chroot_context.chroot.root
        basedir_seen_by_module = Path("/") / basedir.relative_to(chroot_dir)
        request = ttypes.FetchRequest(
            str(basedir_seen_by_module),
            arrow_params_to_thrift(params),
            arrow_raw_params_to_thrift(RawParams(secrets)),
            (
                None
                if last_fetch_result is None
                else arrow_fetch_result_to_thrift(last_fetch_result)
            ),
            input_parquet_filename,
            output_filename,
        )
        try:
            with chroot_context.writable_file(basedir / output_filename):
                result = self._run_in_child(
                    chroot_dir=chroot_dir,
                    network_config=pyspawner.NetworkConfig(),
                    compiled_module=compiled_module,
                    timeout=self.fetch_timeout,
                    result=ttypes.FetchResult(),
                    function="fetch_thrift",
                    args=[request],
                )
        finally:
            chroot_context.clear_unowned_edits()

        if result.filename and result.filename != output_filename:
            raise ModuleExitedError(
                compiled_module.module_slug, 0, "Module wrote to wrong output file"
            )

        # TODO validate result isn't too large. If result is dataframe it makes
        # sense to truncate; but fetch results aren't necessarily data frames.
        # It's up to the module to enforce this logic ... but we need to set a
        # maximum file size.
        return thrift_fetch_result_to_arrow(result, basedir)

    def _run_in_child(
        self,
        *,
        chroot_dir: Path,
        network_config: Optional[pyspawner.NetworkConfig],
        compiled_module: CompiledModule,
        timeout: float,
        result: Any,
        function: str,
        args: List[Any],
    ) -> None:
        """Fork a child process to run `function` with `args`.

        `args` must be Thrift data types. `result` must also be a Thrift type --
        its `.read()` function will be called, which may produce an error if
        the child process has a bug. (EOFError is very likely.)

        Raise ModuleExitedError if the child process did not behave as expected.

        Raise ModuleTimeoutError if it did not exit after a delay -- or if it
        closed its file descriptors long before it exited.
        """
        limit_time = time.time() + timeout

        module_process = self._pyspawner.spawn_child(
            args=[compiled_module, function, args],
            process_name=compiled_module.module_slug,
            sandbox_config=pyspawner.SandboxConfig(
                chroot_dir=chroot_dir, network=network_config
            ),
        )

        # stdout is Thrift package; stderr is logs
        output_reader = ChildReader(
            module_process.stdout.fileno(), OUTPUT_BUFFER_MAX_BYTES
        )
        log_reader = ChildReader(module_process.stderr.fileno(), LOG_BUFFER_MAX_BYTES)
        # Read until the child closes its stdout and stderr
        with selectors.DefaultSelector() as selector:
            selector.register(output_reader.fileno, selectors.EVENT_READ)
            selector.register(log_reader.fileno, selectors.EVENT_READ)

            timed_out = False
            while selector.get_map():
                remaining = limit_time - time.time()
                if remaining <= 0:
                    if not timed_out:
                        timed_out = True
                        module_process.kill()  # untrusted code could ignore SIGTERM
                    remaining = None  # wait as long as it takes for everything to die
                    # Fall through. After SIGKILL the child will close each fd,
                    # sending EOF to us. That means the selector _must_ return.

                events = selector.select(timeout=remaining)
                ready = frozenset(key.fd for key, _ in events)
                for reader in (output_reader, log_reader):
                    if reader.fileno in ready:
                        reader.ingest()
                        if reader.eof:
                            selector.unregister(reader.fileno)

        # The child closed its fds, so it should die soon. If it doesn't, that's
        # a bug -- so kill -9 it!
        #
        # os.wait() has no timeout option, and asyncio messes with signals so
        # we won't use those. Spin until the process dies, and force-kill if we
        # spin too long.
        for _ in range(DEAD_PROCESS_N_WAITS):
            pid, exit_status = module_process.wait(os.WNOHANG)
            if pid != 0:  # pid==0 means process is still running
                break
            time.sleep(DEAD_PROCESS_WAIT_POLL_INTERVAL)
        else:
            # we waited and waited. No luck. Dead module. Kill it.
            timed_out = True
            module_process.kill()
            _, exit_status = module_process.wait(0)
        if os.WIFEXITED(exit_status):
            exit_code = os.WEXITSTATUS(exit_status)
        elif os.WIFSIGNALED(exit_status):
            exit_code = -os.WTERMSIG(exit_status)
        else:
            raise RuntimeError("Unhandled wait() status: %r" % exit_status)

        if timed_out:
            raise ModuleTimeoutError(compiled_module.module_slug, timeout)

        if exit_code != 0:
            raise ModuleExitedError(
                compiled_module.module_slug, exit_code, log_reader.to_str()
            )

        transport = thrift.transport.TTransport.TMemoryBuffer(output_reader.buffer)
        protocol = thrift.protocol.TBinaryProtocol.TBinaryProtocol(transport)
        try:
            result.read(protocol)
        except EOFError:  # TODO handle other errors Thrift may throw
            raise ModuleExitedError(
                compiled_module.module_slug, exit_code, log_reader.to_str()
            ) from None

        # We should be at the end of the output now. If we aren't, that means
        # the child wrote too much.
        if transport.read(1) != b"":
            raise ModuleExitedError(
                compiled_module.module_slug, exit_code, log_reader.to_str()
            )

        if log_reader.buffer:
            logger.info("Output from module process: %s", log_reader.to_str())

        return result
