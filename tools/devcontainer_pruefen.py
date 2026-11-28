"""Prüft, ob jede Datei, die .devcontainer/devcontainer.json mit „-r <datei>“ einliest, existiert.

Sonst bricht pip beim Anlegen des Codespaces ab, und der Schnellstart aus dem README
funktioniert nicht.

Aufruf (in CI und lokal): python tools/devcontainer_pruefen.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ".devcontainer/devcontainer.json"
REQUIREMENT_FILE = re.compile(r"(?:-r|--requirement)[\s=]+([^\s\"',;&|]+)")


def main():
    text = (ROOT / CONFIG).read_text(encoding="utf-8")
    files = REQUIREMENT_FILE.findall(text)
    missing = [name for name in files if not (ROOT / name).is_file()]
    if missing:
        print(f"{CONFIG} liest Dateien ein, die es nicht gibt:", *missing, sep="\n  ")
        return 1
    print(f"{CONFIG}: alle eingelesenen Dateien vorhanden ({', '.join(files) or 'keine'}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
