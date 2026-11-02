"""Launch run_MOBILE.sh in a run folder, report its progress and judge the outcome."""

import fcntl
import hashlib
import os
import re
import signal
import subprocess
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


class RunnerBusy(RuntimeError):
    """Another run is using this MoBILE repository: mobile.sh modifies the shared src/."""


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

    def run(self, name=None, on_progress=None):
        """Run the model to the end and return a RunResult; a failed run is a status, not an exception."""
        with open(self._lock_path(), "w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RunnerBusy(f"A run is already using {self.config.mobile}") from None
            return self._run_locked(name, on_progress)

    def _run_locked(self, name, on_progress):
        run_dir = create_run_dir(self.config, name)
        env = {
            **os.environ,
            "MOBILE": str(self.config.mobile),
            "GFORTRAN_UNBUFFERED_PRECONNECTED": "1",
        }
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
            for raw in _lines(self._process.stdout):
                log.write(raw + b"\n")
                log.flush()
                line = raw.decode("utf-8", errors="replace")
                finished = finished or FINISHED_LINE in line
                event = parser.parse(line)
                if event and on_progress:
                    on_progress(event)
            returncode = self._process.wait()
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
        if process is None or process.poll() is not None:
            return
        self._cancelled.set()
        os.killpg(process.pid, signal.SIGTERM)
        threading.Timer(5, self._kill, args=[process]).start()

    @staticmethod
    def _kill(process):
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
