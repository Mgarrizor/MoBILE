"""A calibration run on a cluster with Slurm, from the GUI on this computer, over ssh: made here, then

  send      its folder copied there, with the driving files and observations it uses, its paths made relative to it
  submit    a batch job there that runs `mobile calibrate` on it (calibration_cli.py), after the last one if it is queued
  refresh   the small files copied back (status, a snapshot of the study, the series of each trial, the job logs), and
            what Slurm says of its jobs; never the model output
  stop      the job asked to stop as at its deadline (SIGTERM): the trials going on are lost, the calibration resumable

While it runs there, the folder there is the master, and the one here mirrors it (CLUSTER in it says where): it is not
run here. Every command runs `ssh -o BatchMode=yes <host>`: a missing login (e.g. a certificate of the day) fails at
once (LOGIN), instead of waiting for a password. Files go through tar over the same ssh connection."""

import io
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .calibration_engine import (CLUSTER, DATABASE, SERIES, SNAPSHOT, STATUS, TRIALS, CalibrationError, _now, _write_atomic,
                                 forget_storage, is_running, read_calibration, read_cluster, resolved, setup_config,
                                 write_calibration)
from .config import MAX_PATH_LENGTH, MAX_THREADS
from .worldpop import cache_folder, summary_name

SETTINGS_FILE = "cluster.json"  # In the settings folder: the cluster settings last used
LOGS = "logs"
JOB_SCRIPT = "job.sh"
LOGIN = "log in to the cluster first (e.g. `step ssh login <your e-mail> --provisioner cineca-hpc` for CINECA), then try again"
REMOTE_FIELDS = ("status", "completed", "failed", "failure", "binary_md5")  # Taken from the record there on refresh
SSH_SECONDS = 60  # A command that is not a copy


class ClusterError(RuntimeError):
    """Something that could not be done on the cluster, said for the user."""


@dataclass
class ClusterSettings:
    """Where and how a calibration runs on the cluster. The defaults are those of the CINECA LEONARDO DCGP partition."""
    host: str = "leonardo"
    folder: str = "/leonardo_work/try26_garrido/calibration"
    mobile: str = ""  # The MoBILE clone there; empty: $MOBILE of the setup lines
    account: str = "try26_garrido"
    partition: str = "dcgp_usr_prod"
    qos: str = "normal"
    time: str = "06:00:00"
    cpus: int = 112
    exclusive: bool = True
    parallel: int = 0  # Runs at the same time; 0: the CPUs divided by the threads per run of the calibration
    trial_minutes: float = 0.0  # A guess of how long a trial takes, used until 10 have completed; 0: none
    setup: str = ("source ~/mobile_env.sh\nmodule load python/3.11.7\nunset PYTHONPATH\n"
                  "source ~/venvs/mobile-gui/bin/activate")

    @classmethod
    def from_dict(cls, values):
        known = {field.name: field.type for field in fields(cls)}
        return cls(**{key: value for key, value in (values or {}).items() if key in known})


def load_settings():
    from .setup import settings_folder  # Not at the top: as worldpop does

    try:
        return ClusterSettings.from_dict(json.loads((settings_folder() / SETTINGS_FILE).read_text()))
    except (OSError, ValueError, TypeError):
        return ClusterSettings()


def save_settings(settings):
    """Remember the settings for the next session. Not being able to is not an error."""
    from .setup import settings_folder

    try:
        folder = settings_folder()
        folder.mkdir(parents=True, exist_ok=True)
        (folder / SETTINGS_FILE).write_text(json.dumps(asdict(settings), indent=2) + "\n")
    except OSError:
        pass


def remote(path):
    """A path for the shell there: ~ and $VARIABLES expanded there, anything else as it is."""
    path = str(path)
    if path == "~" or path.startswith("~/"):
        path = "$HOME" + path[1:]
    return '"' + "".join("\\" + c if c in '"`\\' else c for c in path) + '"'


def _complaint(stderr):
    """The last line of what ssh or the command said, without the warnings ssh prints on every connection."""
    lines = [line for line in (stderr or "").strip().splitlines()
             if line.strip() and "post-quantum" not in line and not line.startswith("**")
             and "gres/tmpfs" not in line]
    return lines[-1] if lines else ""


def ssh(host, command, what, data=None, timeout=SSH_SECONDS):
    """Run a shell command there; its standard output. data: bytes, or an open file, for its standard input."""
    given = {"input": data} if data is None or isinstance(data, bytes) else {"stdin": data}
    try:
        result = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", host, command], **given,
                                capture_output=True, timeout=timeout)
    except FileNotFoundError:
        raise ClusterError("ssh is not installed on this computer") from None
    except subprocess.TimeoutExpired:
        raise ClusterError(f"{what}: {host} did not answer within {timeout} s") from None
    stderr = result.stderr.decode(errors="replace")
    if result.returncode == 255:
        raise ClusterError(f"cannot connect to {host}: {LOGIN}. ({_complaint(stderr) or 'no answer'})")
    if result.returncode != 0:
        raise ClusterError(f"{what} failed on {host}: {_complaint(stderr) or f'exit {result.returncode}'}")
    return result.stdout.decode(errors="replace")


def check_login(host):
    """Raises ClusterError, saying to log in, if ssh cannot get in without a password."""
    ssh(host, "true", "the login")


# ---------------------------------------------------------------- send

def observation_files(folder):
    """[(path, bytes)] of the observations a calibration is compared with: they are copied with it when it is sent."""
    record = resolved(folder, read_calibration(folder))
    paths = sorted({objective[key] for objective in record["objectives"] for key in ("data", "data_raw") if objective.get(key)})
    return [(path, Path(path).stat().st_size if Path(path).is_file() else None) for path in paths]


def remote_folder(settings, folder):
    """The folder of the calibration there: that of the settings, and the name of the folder here."""
    return f"{settings.folder.rstrip('/')}/{Path(folder).name}"


def _plan(folder, record):
    """(record to write there, {name in the folder there: file here}) of a calibration: its paths relative to its folder;
    the driving files not in it put in inputs/, the observations in data/."""
    folder = Path(folder).resolve()
    files, inputs = {}, {}
    for key, path in record["run_inputs"].items():
        if not isinstance(path, str) or path.strip() in ("", "NONE") or not Path(path).is_file():
            inputs[key] = path
            continue
        here = Path(path).resolve()
        name = str(here.relative_to(folder)) if here.is_relative_to(folder) else f"inputs/external/{key}_{here.name}"
        files[name], inputs[key] = here, name
    objectives = []
    for index, objective in enumerate(resolved(folder, record)["objectives"]):
        objective = dict(objective)
        for key in ("data", "data_raw"):
            if objective.get(key):
                name = f"data/objective_{index}_{key}_{Path(objective[key]).name}"
                files[name], objective[key] = Path(objective[key]), name
        objectives.append(objective)
    if (folder / DATABASE).is_file():
        files[DATABASE] = folder / DATABASE
    there = {**record, "run_inputs": inputs, "objectives": objectives, "setup": {**record["setup"], "inputs": dict(inputs)}}
    return there, files


def _tar(files, extra):
    """A tar archive of files {name: path} and extra {name: bytes}, in a temporary file, at its start."""
    archive = tempfile.TemporaryFile()
    with tarfile.open(fileobj=archive, mode="w") as tar:
        for name, data in extra.items():
            info = tarfile.TarInfo(name)
            info.size, info.mtime = len(data), int(time.time())
            tar.addfile(info, io.BytesIO(data))
        for name, path in files.items():
            tar.add(path, arcname=name, recursive=False)
    archive.seek(0)
    return archive


def send(folder, settings, cleared=False):
    """Copy a calibration made here to the cluster, and note where in its folder here (CLUSTER). cleared: the user has
    agreed that its observations (observation_files) may be copied there. Returns the folder there."""
    folder = Path(folder)
    record = read_calibration(folder)
    if read_cluster(folder) is not None:
        raise ClusterError(f"it was sent already, to {read_cluster(folder)['host']}")
    if is_running(folder):
        raise ClusterError("it is running here: cancel it first")
    missing = [path for path, size in observation_files(folder) if size is None]
    if missing:
        raise ClusterError(f"observations not found: {', '.join(missing)}")
    if not cleared:
        raise ClusterError("tick that its observations may be copied to the cluster first")
    threads = record["setup"]["run"]["threads"]
    if threads > MAX_THREADS:
        raise ClusterError(f"its runs have {threads} threads; the model allows at most {MAX_THREADS}")
    there, files = _plan(folder, record)
    if settings.mobile:
        there["setup"]["mobile"] = settings.mobile
    else:
        there["setup"]["mobile"] = "$MOBILE"
    # Where it goes, as the shell there sees it, and that nothing is there yet
    target = remote_folder(settings, folder)
    answer = ssh(settings.host, f'd={remote(target)}; printf "%s\\n" "$d"; if [ -e "$d" ]; then echo exists; fi',
                 "looking for the folder").splitlines()
    target = answer[0] if answer else target
    if "exists" in answer[1:]:
        raise ClusterError(f"{settings.host}:{target} exists already: rename it there, or give this calibration another name")
    longest = max([len(name) for name in files] + [len(f"{TRIALS}/trial_00000/seed_{max(record['seeds'])}/output/output.nc")])
    if len(target) + 1 + longest > MAX_PATH_LENGTH - 40:
        raise ClusterError(f"paths there would be up to {len(target) + 1 + longest} characters, more than the model takes "
                           f"({MAX_PATH_LENGTH - 40}): choose a shorter folder there")
    extra = {"calibration.json": (json.dumps(there, indent=2) + "\n").encode()}
    with _tar(files, extra) as archive:
        ssh(settings.host, f'mkdir -p {remote(target)} && tar xf - -C {remote(target)}', "copying the calibration",
            data=archive, timeout=3600)
    _send_age_structure(folder, record, settings.host)
    _write_cluster(folder, {"host": settings.host, "folder": target, "sent": _now(), "jobs": [], "refreshed": None})
    return target


def _send_age_structure(folder, record, host):
    """The age structure the runs use, there where the package keeps it (it cannot be downloaded from a compute node),
    unless it comes with the package."""
    choice = setup_config(folder, record).age_choice()
    name = summary_name(**choice)
    path = cache_folder() / name
    if path.is_file():
        there = f"~/.config/mobile/worldpop/{name}"
        ssh(host, f"mkdir -p {remote(str(Path(there).parent))} && cat > {remote(there)}", "copying the age structure",
            data=path.read_bytes())


def _write_cluster(folder, cluster):
    _write_atomic(Path(folder) / CLUSTER, json.dumps(cluster, indent=1) + "\n")


def _cluster(folder):
    cluster = read_cluster(folder)
    if cluster is None:
        raise ClusterError("it has not been sent to a cluster")
    return cluster


# ---------------------------------------------------------------- submit

def runs_at_once(settings, threads):
    """Runs at the same time in a job: as set, or as many as fit in its CPUs with the threads per run."""
    return settings.parallel or max(1, settings.cpus // threads)


def job_script(settings, record, target):
    """The batch script that runs the calibration in a folder there (its first argument)."""
    threads = record["setup"]["run"]["threads"]
    parallel = runs_at_once(settings, threads)
    if parallel * threads > settings.cpus:
        raise ClusterError(f"{parallel} runs × {threads} threads need {parallel * threads} CPUs; the job asks for {settings.cpus}")
    name = "cal_" + Path(target).name[:24]
    lines = ["#!/bin/bash", f"#SBATCH --job-name={name}"]
    for option, value in (("account", settings.account), ("partition", settings.partition), ("qos", settings.qos)):
        if value.strip():
            lines.append(f"#SBATCH --{option}={value.strip()}")
    lines += ["#SBATCH --nodes=1", "#SBATCH --ntasks=1", f"#SBATCH --cpus-per-task={settings.cpus}"]
    if settings.exclusive:
        lines.append("#SBATCH --exclusive")
    lines += [f"#SBATCH --time={settings.time.strip()}",
              "#SBATCH --signal=B:TERM@300  # Before the end: stop cleanly, if the deadline has not stopped it already",
              f"#SBATCH --output={target}/{LOGS}/%j.out", ""]
    lines += [line for line in settings.setup.splitlines()]
    options = f" --parallel {parallel}" + (f" --trial-minutes {settings.trial_minutes:g}" if settings.trial_minutes else "")
    lines += ["", "# exec: the signal of Slurm goes to the batch shell; so mobile gets it", f'exec mobile calibrate "$1"{options}', ""]
    return "\n".join(lines)


def submit(folder, settings):
    """Submit a job that runs the calibration there, after the last one if Slurm still lists it. Returns its id."""
    folder = Path(folder)
    cluster = _cluster(folder)
    target = cluster["folder"]
    script = job_script(settings, read_calibration(folder), target)
    listed = [job for job in cluster["jobs"] if job.get("listed")]
    after = f" --dependency=afterany:{listed[-1]['id']}" if listed else ""
    answer = ssh(cluster["host"], f"mkdir -p {remote(target + '/' + LOGS)} && cat > {remote(target + '/' + JOB_SCRIPT)} && "
                                  f"cd {remote(target)} && sbatch --parsable{after} {JOB_SCRIPT} {remote(target)}",
                 "submitting the job", data=script.encode())
    job = answer.strip().splitlines()[-1].split(";")[0] if answer.strip() else ""
    if not job.isdigit():
        raise ClusterError(f"sbatch did not give a job id: {answer.strip()[:200]}")
    cluster["jobs"].append({"id": job, "submitted": _now(), "state": "PENDING", "listed": True})
    _write_cluster(folder, cluster)
    return job


# ---------------------------------------------------------------- refresh

def _job_states(answer):
    """{job: (state, listed)} from what squeue, then sacct (after a line ---), said."""
    states = {}
    queued, _, accounted = answer.partition("---")
    for line in accounted.splitlines():
        parts = line.strip().split("|")
        if len(parts) >= 2 and parts[0].isdigit():
            states[parts[0]] = (parts[1].split()[0], False)
    for line in queued.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].isdigit():
            states[parts[0]] = (parts[1], True)
    return states


def refresh(folder):
    """Copy back what the GUI shows of a calibration running there, and what Slurm says of its jobs."""
    folder = Path(folder)
    cluster = _cluster(folder)
    host, target = cluster["host"], cluster["folder"]
    ids = ",".join(job["id"] for job in cluster["jobs"])
    if ids:
        answer = ssh(host, f"squeue -h -j {ids} -o '%A %T' 2>/dev/null; echo ---; sacct -n -X -P -j {ids} -o JobID,State 2>/dev/null; true",
                     "asking Slurm")
        states = _job_states(answer)
        for job in cluster["jobs"]:
            state, listed = states.get(job["id"], ("ENDED", False))  # Neither listed nor accounted for: it has ended
            job["state"], job["listed"] = state, listed
    # The small files only: what there is of them
    wanted = f"{STATUS} {SNAPSHOT} calibration.json {LOGS} {TRIALS}/*/{SERIES}"
    command = f"cd {remote(target)} && ls -d {wanted} 2>/dev/null | tar cf - -T - 2>/dev/null; true"
    try:
        result = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", host, command], capture_output=True,
                                timeout=600)
    except subprocess.TimeoutExpired:
        raise ClusterError(f"copying back: {host} did not answer within 600 s") from None
    if result.returncode == 255:
        raise ClusterError(f"cannot connect to {host}: {LOGIN}. ({_complaint(result.stderr.decode(errors='replace'))})")
    with tempfile.TemporaryDirectory(dir=folder) as staging:
        staging = Path(staging)
        if result.stdout:
            _extract(result.stdout, staging)
        _take(folder, staging)
    cluster["refreshed"] = _now()
    _write_cluster(folder, cluster)
    return cluster


def _extract(data, target):
    """Unpack a tar archive from the cluster: files and folders only, all within the target."""
    with tarfile.open(fileobj=io.BytesIO(data), mode="r") as tar:
        members = tar.getmembers()
        for member in members:
            name = Path(member.name)
            if name.is_absolute() or ".." in name.parts or not (member.isfile() or member.isdir()):
                raise ClusterError(f"unexpected file in what came back: {member.name}")
        tar.extractall(target, members=members)


def _take(folder, staging):
    """Put what was copied back in the folder here: the study from its snapshot, the record's progress, the rest as it is."""
    if (staging / SNAPSHOT).is_file():
        os.replace(staging / SNAPSHOT, folder / DATABASE)
        forget_storage(folder)  # Read again from the new file
    if (staging / "calibration.json").is_file():
        there = json.loads((staging / "calibration.json").read_text())
        write_calibration(folder, {**read_calibration(folder), **{key: there[key] for key in REMOTE_FIELDS if key in there}})
    if (staging / STATUS).is_file():
        os.replace(staging / STATUS, folder / STATUS)
    if (staging / LOGS).is_dir():
        shutil.copytree(staging / LOGS, folder / LOGS, dirs_exist_ok=True)
    for kept in (staging / TRIALS).glob(f"*/{SERIES}"):
        shutil.copytree(kept, folder / TRIALS / kept.parent.name / SERIES, dirs_exist_ok=True)


def last_log(folder, lines=15):
    """(job, the last lines of its log) of the last job whose log was copied back, or None."""
    cluster = read_cluster(folder) or {}
    for job in reversed(cluster.get("jobs", [])):
        path = Path(folder) / LOGS / f"{job['id']}.out"
        if path.is_file():
            return job["id"], "\n".join(path.read_text(errors="replace").splitlines()[-lines:])
    return None


# ---------------------------------------------------------------- stop

def stop(folder):
    """Ask the last job listed to stop: a running one cleanly (SIGTERM, as at its deadline: resumable), a queued one
    cancelled. Returns its id, or None if none is listed."""
    folder = Path(folder)
    cluster = _cluster(folder)
    listed = [job for job in cluster["jobs"] if job.get("listed")]
    if not listed:
        return None
    job = listed[-1]
    command = (f"scancel --batch --signal=TERM {job['id']}" if job.get("state") in ("RUNNING", "COMPLETING")
               else f"scancel {job['id']}")
    ssh(cluster["host"], command, "stopping the job")
    return job["id"]


__all__ = ["ClusterError", "ClusterSettings", "CalibrationError", "check_login", "job_script", "last_log", "load_settings",
           "observation_files", "refresh", "remote_folder", "runs_at_once", "save_settings", "send", "stop", "submit"]
