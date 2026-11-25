"""Prüft, ob die Lockdatei requirements.txt zu requirements*.in passt.

Jedes Paket aus den .in-Dateien muss in requirements.txt stehen, und zwar in einer Version,
die die Grenzen aus der .in-Datei erfüllt. Schlägt fehl, wenn jemand eine .in-Datei geändert
und vergessen hat, die Lockdatei neu zu erzeugen (Befehl in CONTRIBUTING.md).

Aufruf (in CI und lokal): python tools/lockdatei_pruefen.py
"""
import re
import sys
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parent.parent
INPUTS = ["requirements.in", "requirements-automation.in"]
LOCK = "requirements.txt"
PIN = re.compile(r"^([A-Za-z0-9._-]+)==([^\s\\;]+)")


def _lines(path):
    for line in (ROOT / path).read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line and not line.startswith("-"):
            yield line


def main():
    pinned = {}
    for line in (ROOT / LOCK).read_text(encoding="utf-8").splitlines():
        match = PIN.match(line)
        if match:
            pinned[canonicalize_name(match.group(1))] = match.group(2)

    problems = []
    for path in INPUTS:
        for line in _lines(path):
            req = Requirement(line)
            version = pinned.get(canonicalize_name(req.name))
            if version is None:
                problems.append(f"{path}: {req.name} fehlt in {LOCK}")
            elif not req.specifier.contains(version, prereleases=True):
                problems.append(f"{path}: {req.name}=={version} in {LOCK} passt nicht zu „{req.specifier}“")

    if problems:
        print("Lockdatei ist nicht aktuell:", *problems, sep="\n  ")
        print("Neu erzeugen: siehe CONTRIBUTING.md, „Abhängigkeiten“.")
        return 1
    print(f"{LOCK} passt zu {', '.join(INPUTS)} ({len(pinned)} Pakete festgelegt).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
