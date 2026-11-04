"""Launch run_MOBILE.sh in a run folder, report its progress and judge the outcome."""

import fcntl
import hashlib
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass

from .results import RunResult, write_manifest
from .rundir import OUTPUT_NAME, create_run_dir

FINISHED_LINE = "Program finished successfully"
COMPILE_RE = re.compile(r"Compile module (\S+)")
SPINUP_RE = re.compile(r"Spin-up convergence\s+([\d.]+)\s*<=\?\s*([\d.]+)")
INTEGRATE_RE = re.compile(r"Integrating\s*(\d+)\s*/\s*(\d+)\s*-\s*([\d.]+)\s*%")


def macos_sdk():
    """The path of the newest macOS SDK installed, from xcrun; None if there is none or this is not a Mac."""
    if sys.platform != "darwin":
        return None
    try:
        found = subprocess.run(["xcrun", "--show-sdk-path"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    path = found.stdout.strip()
    return path if found.returncode == 0 and os.path.isdir(path) else None


def run_environment(mobile, environ=None):
    """The environment of a run. On a Mac, gfortran looks for the SDK named after the macOS version, which the
    Command Line Tools may not have yet (linking then fails with "library 'System' not found"), so the SDK
    that is installed is given, unless SDKROOT is set."""
    env = {**(os.environ if environ is None else environ), "MOBILE": str(mobile), "GFORTRAN_UNBUFFERED_PRECONNECTED": "1"}
    if "SDKROOT" not in env and (sdk := macos_sdk()):
        env["SDKROOT"] = sdk
    return env


BUILT_LINE = "Running MoBILE"  # Written by mobile.sh once the model is built, just before it starts
LOCK_POLL_SECONDS = 0.2


class RunnerBusy(RuntimeError):
    """Another run is building the model from this MoBILE repository: mobile.sh modifies the shared src/ while
    it builds, so builds take turns. Once built, runs go on side by side."""


class RunCancelled(RuntimeError):
    """The run was cancelled while it waited for its turn to build, so it never started."""


@dataclass(frozen=True)
class Progress:
    stage: str               # compiling, initialising, spin-up, integrating
    message: str
    fraction: float | None   # Of the stage; None when it cannot be known in advance


class ProgressParser:
    """Turn the log lines of the scripts and the model into Progress events."""

    def __init__(self):
        self.spinup_year = 0

    def parse(self, line):
        if match := COMPILE_RE.search(line):
            return Progress("compiling", f"Compiling {match.group(1)}", None)
        if "Running MoBILE" in line:
            return Progress("initialising", "Initialising agents", None)
        if match := SPINUP_RE.search(line):
            self.spinup_year += 1
            return Progress(
                "spin-up",
                f"Spin-up year {self.spinup_year}: convergence {match.group(1)} (target {match.group(2)})",
                None,
            )
        if match := INTEGRATE_RE.search(line):
            current, total, percent = match.groups()
            return Progress("integrating", f"Day {current} of {total}", float(percent) / 100)
        return None


def _lines(stream):
    """Yield log lines from a binary stream; the model's progress line ends in a carriage return."""
    buffer = b""
    while chunk := os.read(stream.fileno(), 65536):
        buffer += chunk
        *complete, buffer = re.split(rb"[\r\n]", buffer)
        for line in complete:
            yield line
    if buffer:
        yield buffer


class Runner:
    def __init__(self, config):
        self.config = config
        self._process = None
        self._cancelled = threading.Event()

    def _lock_path(self):
        key = hashlib.sha256(str(self.config.mobile).encode()).hexdigest()[:16]
        return os.path.join(tempfile.gettempdir(), f"mobile_{key}.lock")

    def run(self, name=None, on_progress=None, wait=False):
        """Run the model to the end and return a RunResult; a failed run is a status, not an exception.

        The repository is locked while the model is built. If another run is building, raise RunnerBusy, or
        with wait wait for it, unless the run is cancelled meanwhile (RunCancelled)."""
        with open(self._lock_path(), "w") as lock:
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if not wait:
                        raise RunnerBusy(f"Another run is building the model from {self.config.mobile}") from None
                if self._cancelled.wait(LOCK_POLL_SECONDS):
                    raise RunCancelled("Cancelled before the model was built")
            locked = [True]

            def release():
                if locked[0]:
                    fcntl.flock(lock, fcntl.LOCK_UN)
                    locked[0] = False

            try:
                return self._run_locked(name, on_progress, release)
            finally:
                release()

    def _run_locked(self, name, on_progress, release_lock):
        run_dir = create_run_dir(self.config, name)
        env = run_environment(self.config.mobile)
        parser = ProgressParser()
        finished = False
        started = time.time()
        with open(run_dir / "run.log", "wb") as log:
            self._process = subprocess.Popen(
                ["bash", "run_MOBILE.sh"],
                cwd=run_dir,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,  # Its own process group, so that cancel reaches make and mobile.out
            )
            if self._cancelled.is_set():  # Cancelled while the run folder was made
                os.killpg(self._process.pid, signal.SIGTERM)
            for raw in _lines(self._process.stdout):
                log.write(raw + b"\n")
                log.flush()
                line = raw.decode("utf-8", errors="replace")
                if BUILT_LINE in line:
                    release_lock()  # Built: the next run can build while this one runs
                finished = finished or FINISHED_LINE in line
                event = parser.parse(line)
                if event and on_progress:
                    on_progress(event)
            returncode = self._process.wait()
            self._process.stdout.close()
        wall_seconds = time.time() - started

        # Exit codes do not tell: a bare STOP exits 0 and the scripts do not pass the model's status on
        output_path = run_dir / OUTPUT_NAME / f"{OUTPUT_NAME}.nc"
        if self._cancelled.is_set():
            status = "cancelled"
        elif finished and output_path.is_file():
            status = "finished"
        else:
            status = "failed"
        result = RunResult(
            status=status,
            run_dir=run_dir,
            output_path=output_path,
            returncode=returncode,
            wall_seconds=wall_seconds,
            spinup_years=parser.spinup_year,
        )
        write_manifest(self.config, result)
        return result

    def cancel(self):
        """Stop the running scripts, compiler and model. Safe to call from another thread."""
        process = self._process
        if process is None:
            self._cancelled.set()  # Still waiting for its turn to build: it will not start
            return
        if process.poll() is not None:
            return
        self._cancelled.set()
        os.killpg(process.pid, signal.SIGTERM)
        threading.Timer(5, self._kill, args=[process]).start()

    @staticmethod
    def _kill(process):
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
