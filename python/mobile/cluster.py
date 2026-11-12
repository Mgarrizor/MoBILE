"""A calibration run on a cluster with Slurm, from the GUI on this computer, over ssh: made here, then

  send      its folder copied there, with the driving files and observations it uses, its paths made relative to it
  submit    a batch job there that runs `mobile calibrate` on it (calibration_cli.py), after the last one if it is queued
  refresh   the small files copied back (status, a snapshot of the study, the series of each trial, the job logs), and
            what Slurm says of its jobs; never the model output
  stop      the job asked to stop as at its deadline (SIGTERM): the trials going on are lost, the calibration resumable

While it runs there, the folder there is the master, and the one here mirrors it (CLUSTER in it says where): it is not
run here. Every command runs `ssh -o BatchMode=yes <host>`: a missing login (e.g. a certificate of the day) fails at
once (LOGIN), instead of waiting for a password. Files go through tar over the same ssh connection."""

import datetime
import io
import json
import os
import shlex
import shutil
import subprocess
import tarfile
import tempfile
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .calibration_cli import RESUMABLE
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
STOPPED = "STOPPED (RESUMABLE)"  # A job's state, here, when Slurm says FAILED but the calibration stopped as at its deadline


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
    # Quiet: the module messages would fill the end of the log that Refresh shows
    setup: str = ("source ~/mobile_env.sh > /dev/null 2>&1\nmodule load python/3.11.7 > /dev/null 2>&1\nunset PYTHONPATH\n"
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
    # No paths of this computer there: the runs go in the trials' folders anyway, and the shapes only draw maps here
    there["setup"]["runs_dir"] = target
    there["setup"].pop("shapes", None)
    extra ={"calibration.json": (json.dumps(there, indent=2) + "\n").encode()}
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
    # The signal is a safety net only: Slurm may send it up to 60 s early, so it comes 60-120 s before the end, after
    # the trials have ended (deadline: calibration_cli.DEADLINE_MARGIN = 120 s). At 300 s it cut trials still running
    # (LEONARDO, job 64190103: 20 cancelled).
    lines += [f"#SBATCH --time={settings.time.strip()}",
              "#SBATCH --signal=B:TERM@60  # Before the end: stop cleanly, if the deadline has not stopped it already",
              f"#SBATCH --output={target}/{LOGS}/%j.out", ""]
    lines += [line for line in settings.setup.splitlines()]
    options = f" --parallel {parallel}" + (f" --trial-minutes {settings.trial_minutes:g}" if settings.trial_minutes else "")
    lines += ["", "# exec: the signal of Slurm goes to the batch shell; so mobile gets it", f'exec mobile calibrate "$1"{options}', ""]
    return "\n".join(lines)


def submit(folder, settings):
    """Submit a job that runs the calibration there, after the last of its jobs that Slurm lists now (asked in the same
    call, not taken from the last refresh). Returns its id; the job it waits for, if any, is its "after" in CLUSTER."""
    folder = Path(folder)
    cluster = _cluster(folder)
    target = cluster["folder"]
    script = job_script(settings, read_calibration(folder), target)
    ids = [job["id"] for job in cluster["jobs"]]
    # The jobs of it that squeue lists, on a line of their own; the last of them, in the order submitted, is waited for
    ask = (f"listed=\" $(squeue -h -j {','.join(ids)} -o %A 2>/dev/null | awk '{{printf \"%s \", $1}}')\"; "
           f"after=; for job in {' '.join(ids)}; do case \"$listed\" in *\" $job \"*) after=$job;; esac; done; "
           if ids else "listed=' '; after=; ")
    answer = ssh(cluster["host"], f"{ask}echo \"listed:$listed\"; mkdir -p {remote(target + '/' + LOGS)} && "
                                  f"cat > {remote(target + '/' + JOB_SCRIPT)} && cd {remote(target)} && "
                                  f"sbatch --parsable ${{after:+--dependency=afterany:$after}} {JOB_SCRIPT} {remote(target)}",
                 "submitting the job", data=script.encode())
    lines = answer.strip().splitlines()
    listed = next((line[len("listed:"):].split() for line in lines if line.startswith("listed:")), [])
    job = lines[-1].split(";")[0] if lines else ""
    if not job.isdigit():
        raise ClusterError(f"sbatch did not give a job id: {answer.strip()[:200]}")
    for old in cluster["jobs"]:
        old["listed"] = old["id"] in listed
    after = next((old for old in reversed(ids) if old in listed), None)
    cluster["jobs"].append({"id": job, "submitted": _now(), "state": "PENDING", "listed": True, "after": after})
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
    for job in cluster["jobs"]:
        if job["state"] in ("FAILED", "ENDED") and _stopped_resumable(folder / LOGS / f"{job['id']}.out"):
            job["state"] = STOPPED
    cluster["refreshed"] = _now()
    _write_cluster(folder, cluster)
    return cluster


def _stopped_resumable(log):
    """Whether a job's log ends as `mobile calibrate` does when it stops before the end, resumable (its exit code 3, which
    Slurm records as FAILED)."""
    try:
        lines = [line for line in log.read_text(errors="replace").splitlines()[-30:] if line.startswith("exit ")]
    except OSError:
        return False
    return bool(lines) and lines[-1].startswith(f"exit {RESUMABLE}:")


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


# ---------------------------------------------------------------- cluster information

INFO_SECONDS = 25  # Each command of the cluster information at most, but saldo
SALDO_SECONDS = 120  # saldo and the project's usage (sacct -a), slow: 18 s and 24 s on LEONARDO, 12 Nov 2026
INFO_SCRIPT = r"""export PATH="$PATH:/cineca/bin"
t() { if command -v timeout > /dev/null; then timeout "$1" "${@:2}"; else "${@:2}"; fi 2> /dev/null; }
echo @@assoc; assoc=$(t {seconds} sacctmgr -n -P show assoc user="$USER" format=account,partition,qos); echo "$assoc"
# saldo by project (asked per user, it lists none for a new account), each alongside the rest: it is often slow
saldo_dir=$(mktemp -d)
for a in $( (echo {account}; echo "$assoc" | cut -d'|' -f1) | grep . | sort -u); do
  (t {saldo_seconds} saldo -b -a "$a" {saldo_flags}; echo "saldo-exit: $?") > "$saldo_dir/$a" &
done
echo @@qos; [ -n {qos} ] && t {seconds} sacctmgr -n -P show qos {qos} format=name,maxwall,maxtrespu,maxjobspu,maxsubmitpu
echo @@calibration; [ -n {ids} ] && t {seconds} sacct -n -X -P -j {ids} -o JobID,State,CPUTimeRAW
echo @@mine; t {seconds} squeue --me -h -o '%A|%j|%T|%M|%l|%R'
echo @@load; [ -n {partition} ] && t {seconds} sinfo -p {partition} -h -o '%T %D'
wait; echo @@saldo; s=$(cat "$saldo_dir"/* 2> /dev/null); rm -rf "$saldo_dir"; echo "$s"
echo @@usage; start=$(echo "$s" | awk -v a={account} '$1 == a && $2 ~ /^[0-9]{8}$/ {print $2}')
if [ -n "$start" ]; then
  echo "$start"; u=$(t {saldo_seconds} sacct -n -X -P -a -A {account} -S "${start:0:4}-${start:4:2}-${start:6:2}" -E now -o CPUTimeRAW)
  echo "sacct-exit: $?"; echo "$u" | awk '{n += $1} END {print n + 0}'
fi
echo @@end
"""


def cluster_info(settings, folder=None):
    """What the cluster says, in one ssh call of read-only commands: {section: its lines} (sections of INFO_SCRIPT)."""
    cluster = read_cluster(folder) if folder else None
    ids = ",".join(job["id"] for job in (cluster or {}).get("jobs", []))
    values = {"seconds": str(INFO_SECONDS), "saldo_seconds": str(SALDO_SECONDS),
              "saldo_flags": "--dcgp" if settings.partition.strip().startswith("dcgp") else "", "qos": settings.qos.strip(), "account": settings.account.strip(),
              "partition": settings.partition.strip(), "ids": ids}
    script = INFO_SCRIPT
    for key, value in values.items():
        script = script.replace("{" + key + "}", value if key.startswith("saldo_") or key == "seconds" else shlex.quote(value))
    answer = ssh(settings.host, "bash -s", "asking the cluster", data=script.encode(), timeout=4 * INFO_SECONDS + 2 * SALDO_SECONDS + 30)
    sections, name = {}, None
    for line in answer.splitlines():
        if line.startswith("@@"):
            name = line[2:].strip()
            sections[name] = []
        elif name and line.strip():
            sections[name].append(line.rstrip())
    if "end" not in sections:
        raise ClusterError("asking the cluster: the answer stopped early")
    return sections


def _hours(seconds):
    """Core-hours, as said: 1 decimal below 100."""
    return f"{seconds / 3600:,.1f}" if seconds < 360000 else f"{seconds / 3600:,.0f}"


def wall_seconds(text):
    """Seconds of a Slurm time ([d-]h:mm:ss, mm:ss or minutes), or None (e.g. UNLIMITED, empty)."""
    text = (text or "").strip()
    days, _, rest = text.rpartition("-") if "-" in text else ("0", "", text)
    parts = rest.split(":")
    if not days.isdigit() or not all(part.isdigit() for part in parts) or not 1 <= len(parts) <= 3:
        return None
    numbers = [int(part) for part in parts]
    if len(numbers) == 1:
        seconds = numbers[0] * 60  # Minutes, as for --time
    elif len(numbers) == 2:
        seconds = numbers[0] * 60 + numbers[1]
    else:
        seconds = numbers[0] * 3600 + numbers[1] * 60 + numbers[2]
    return int(days) * 86400 + seconds


def _memory(value):
    """'965 GB of memory' of Slurm's 988000M (its units: K, M, G, T, each 1024 of the one before; M without a unit)."""
    number, unit = (value[:-1], value[-1].upper()) if value[-1:].isalpha() else (value, "M")
    try:
        gb = float(number) * 1024 ** "KMGT".index(unit) / 1024 ** 2
    except ValueError:
        return f"{value} of memory"
    return f"{gb:,.0f} GB of memory"


def _date(stamp):
    """'25 Nov 2026' of 20261125."""
    return datetime.datetime.strptime(stamp, "%Y%m%d").strftime("%-d %b %Y")


def info_rows(sections, settings, record=None, today=None):
    """[(what, value, from, warning)] of the cluster information (cluster_info), for the settings and, if given, the record of
    the calibration chosen (its jobs asked about). warning: the value needs attention."""
    today = today or datetime.date.today()
    rows = []
    # The budget of each project, as CINECA last counted it
    budgets = []
    for line in sections.get("saldo", []):
        parts = line.split()
        if len(parts) >= 7 and len(parts[1]) == 8 and parts[1].isdigit() and parts[3].replace(".", "").isdigit():
            account, start, end, total, used, share = parts[0], parts[1], parts[2], float(parts[3]), float(parts[5]), parts[6]
            if any(account == known for known, *_ in budgets):
                continue
            left = (datetime.datetime.strptime(end, "%Y%m%d").date() - today).days
            budgets.append((account, start, total))
            rows.append((f"Budget of {account}", f"{used:,.0f} of {total:,.0f} core-hours used ({share} %); "
                         f"from {_date(start)} to {_date(end)}" + (f", {left} days left" if left >= 0 else ", ended"),
                         f"saldo -b -a {account} (as of CINECA's last update: it lags)", left < 14 or used > 0.9 * total))
    exits = {line.split(":")[1].strip() for line in sections.get("saldo", []) if line.startswith("saldo-exit:")}
    if "124" in exits:
        rows.append(("Budget", f"saldo did not answer within {SALDO_SECONDS} s for "
                     + ("a project" if budgets else "your projects") + " (it is often slow): Check again later", "saldo -b -a", True))
    elif not budgets:
        said = "saldo is not there (not CINECA?)" if "127" in exits else "saldo listed no project"
        rows.append(("Budget", said, "saldo -b -a", True))
    # Up to date: what Slurm counted since the project started, all its users
    usage = sections.get("usage", [])
    if settings.account and len(usage) >= 3 and usage[1] == "sacct-exit: 0" and usage[2].replace(".", "").isdigit():
        total = next((total for account, _, total in budgets if account == settings.account), None)
        used = float(usage[2]) / 3600
        rows.append((f"Used now by {settings.account}", f"{used:,.0f} core-hours since {_date(usage[0])}"
                     + (f": {total - used:,.0f} left" if total else ""), "sacct, all jobs of the project (up to date)",
                     bool(total) and used > 0.9 * total))
    elif settings.account and len(usage) >= 2:
        rows.append((f"Used now by {settings.account}", f"sacct did not answer within {SALDO_SECONDS} s (it is slow over a whole "
                     "project): Check again later" if usage[1] == "sacct-exit: 124" else f"sacct failed ({usage[1]})", "sacct", True))
    elif settings.account and budgets:
        rows.append((f"Used now by {settings.account}", "not in what saldo listed: is the Account right?", "sacct", True))
    elif settings.account:
        rows.append((f"Used now by {settings.account}", "needs the start of the project, from saldo", "sacct", False))
    # The projects and QOS this user may use
    allowed = {}
    for line in sections.get("assoc", []):
        parts = line.split("|")
        if len(parts) >= 3 and parts[0]:
            allowed.setdefault(parts[0], set()).update(qos for qos in parts[2].split(",") if qos)
    if allowed:
        rows.append(("Your projects and QOS", "; ".join(f"{account}: {', '.join(sorted(qos))}" for account, qos in sorted(allowed.items())),
                     "sacctmgr show assoc", bool(settings.account) and settings.account not in allowed))
    # The limits of the QOS chosen, and the time limit against them
    for line in sections.get("qos", [])[:1]:
        name, maxwall, tres, jobs, submit, *_ = line.split("|") + [""] * 5
        names = {"cpu": "CPUs", "node": "nodes", "mem": "memory", "gres/gpu": "GPUs"}
        each = [_memory(value) if key == "mem" else f"{value} {names.get(key, key)}"
                for key, _, value in (part.partition("=") for part in tres.split(",") if part)]
        limits = [f"a job runs at most {maxwall}" if maxwall else "no time limit"]
        limits += [f"you may use at most {', '.join(each)} at a time" if each else "",
                   f"run at most {jobs} job{'s' if jobs != '1' else ''} at a time" if jobs else "",
                   f"queue at most {submit}" if submit else ""]
        too_long = wall_seconds(maxwall) is not None and (wall_seconds(settings.time) or 0) > wall_seconds(maxwall)
        rows.append((f"QOS {name}", ", ".join(limit for limit in limits if limit) +
                     (f". The time limit set, {settings.time}, is longer: sbatch would refuse the job" if too_long else ""),
                     "sacctmgr show qos", too_long))
    # This calibration's jobs: their cost so far, and per completed trial
    jobs = [line.split("|") for line in sections.get("calibration", []) if line.split("|")[0].isdigit()]
    if record is not None and jobs:
        seconds = sum(float(job[2]) for job in jobs if len(job) >= 3 and job[2].replace(".", "").isdigit())
        completed = record.get("completed") or 0
        per = f"; {seconds / completed / 3600:.2f} per completed trial ({completed} completed, as of the last refresh)" if completed else ""
        rows.append(("This calibration", f"{len(jobs)} job{'s' if len(jobs) > 1 else ''}, {_hours(seconds)} core-hours{per}",
                     "sacct over its jobs", False))
    # All jobs of this user
    mine = [line.split("|") for line in sections.get("mine", [])]
    rows.append(("Your jobs", "; ".join(f"{job[0]} {job[1]} {job[2].lower()} {job[3]} of {job[4]}"
                                        + (f" {job[5]}" if job[2] == "PENDING" and len(job) > 5 else "") for job in mine if len(job) >= 5)
                 or "none queued or running", "squeue --me", False))
    # How busy the partition is
    nodes = {}
    for line in sections.get("load", []):
        parts = line.split()
        if len(parts) == 2 and parts[1].isdigit():
            state = parts[0].rstrip("*~#!%$@^-+")
            nodes[state] = nodes.get(state, 0) + int(parts[1])
    if nodes:
        order = ["idle", "mixed", "allocated"]
        said = [f"{nodes[state]} {state}" for state in order if state in nodes]
        others = sum(count for state, count in nodes.items() if state not in order)
        rows.append((f"Nodes of {settings.partition}", ", ".join(said) + (f", {others} other (down, drained, reserved…)" if others else ""),
                     "sinfo", False))
    return rows


def certificate(now=None):
    """(seconds left, said) of the ssh certificate in the agent here that lasts longest (e.g. that of `step ssh login`), or
    (None, said) if there is none: logging in with a key alone needs none."""
    now = now or datetime.datetime.now()
    try:
        keys = subprocess.run(["ssh-add", "-L"], capture_output=True, text=True, timeout=10).stdout.splitlines()
    except (OSError, subprocess.TimeoutExpired):
        return None, "ssh-add not available"
    best = None
    for key in keys:
        if "-cert-" not in key.split(" ")[0]:
            continue
        try:
            shown = subprocess.run(["ssh-keygen", "-L", "-f", "-"], input=key + "\n", capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.TimeoutExpired):
            continue
        for line in shown.splitlines():
            if line.strip().startswith("Valid:") and " to " in line:
                try:
                    until = datetime.datetime.fromisoformat(line.rsplit(" to ", 1)[1].strip())
                except ValueError:
                    continue
                best = until if best is None or until > best else best
    if best is None:
        return None, "no certificate in the ssh agent: log in first (not needed if you log in with a key alone)"
    left = (best - now).total_seconds()
    if left <= 0:
        return left, f"expired at {best:%H:%M}: log in again"
    return left, f"valid until {best:%H:%M} ({int(left // 3600)} h {int(left % 3600 // 60)} min left)"


def job_cost(settings):
    """Core-hours a job of these settings costs at most: its CPUs for its whole time limit (or None if the time is unclear)."""
    seconds = wall_seconds(settings.time)
    return None if seconds is None else settings.cpus * seconds / 3600


__all__ = ["ClusterError", "ClusterSettings", "CalibrationError", "certificate", "check_login", "cluster_info", "info_rows",
           "job_cost", "job_script", "last_log", "load_settings", "observation_files", "refresh", "remote_folder", "runs_at_once",
           "save_settings", "send", "stop", "submit", "wall_seconds"]
