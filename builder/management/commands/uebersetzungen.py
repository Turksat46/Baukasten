"""Übersetzungen der Oberfläche pflegen, ohne GNU gettext:

    python manage.py uebersetzungen pruefen      # fehlende Übersetzungen auflisten (Exit-Code 1, wenn welche fehlen)
    python manage.py uebersetzungen ergaenzen    # neue Texte mit leerer Übersetzung in die .po-Dateien schreiben
    python manage.py uebersetzungen kompilieren  # .mo-Dateien aus den .po-Dateien erzeugen

Gesucht wird wie bei makemessages: gettext & Co. in Python, {% translate %} und
{% blocktranslate %} in Templates (über Djangos templatize), gettext() in JavaScript.
Mit GNU gettext gehen weiterhin makemessages/compilemessages; beide Wege erzeugen
dieselben Dateien. Sprache: --sprache en (Standard).
"""
import ast
import re
import struct
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils.translation.template import templatize

BUILDER = Path(__file__).resolve().parents[2]
SKIP_DIRS = {"migrations", "locale", "__pycache__", "swagger"}
FUNCS = {"gettext": "s", "_": "s", "gettext_lazy": "s", "gettext_noop": "s", "ngettext": "n", "ngettext_lazy": "n",
         "pgettext": "p", "pgettext_lazy": "p", "npgettext": "np", "npgettext_lazy": "np"}
CALL_RE = re.compile(r"\b(n?p?gettext)\s*\(")
STRING_RE = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"")


# ---------- Texte im Code finden ----------

def _from_call(node, where, found):
    func = node.func
    name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
    kind = FUNCS.get(name)
    args = [a.value if isinstance(a, ast.Constant) and isinstance(a.value, str) else None for a in node.args]
    need = {"s": 1, "n": 2, "p": 2, "np": 3}.get(kind, 0)
    if not kind or len(args) < need or None in args[:need]:
        return
    if kind == "s":
        ctx, msgid, plural = None, args[0], None
    elif kind == "n":
        ctx, msgid, plural = None, args[0], args[1]
    elif kind == "p":
        ctx, msgid, plural = args[0], args[1], None
    else:
        ctx, msgid, plural = args[0], args[1], args[2]
    found.setdefault((ctx, msgid), {"plural": plural, "where": set()})["where"].add(where)


def _scan_loose(text, where, found):
    """gettext( … ) in templatize-Ausgabe und JavaScript: Klammer suchen und als Python auswerten."""
    for m in CALL_RE.finditer(text):
        depth, i, quote = 0, m.end() - 1, None
        while i < len(text):
            ch = text[i]
            if quote:
                if ch == "\\":
                    i += 1
                elif ch == quote:
                    quote = None
            elif ch in "'\"":
                quote = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        snippet = m.group(1) + text[m.end() - 1:i + 1]
        try:
            node = ast.parse(snippet, mode="eval").body
        except SyntaxError:
            # JavaScript: nur das erste Argument aus aneinandergehängten Texten ("a" + "b")
            head = re.match(r"\w+\(\s*((?:%s)(?:\s*\+\s*(?:%s))*)" % (STRING_RE.pattern, STRING_RE.pattern), snippet)
            if head and m.group(1) == "gettext":
                text_value = "".join(ast.literal_eval(s) for s in STRING_RE.findall(head.group(1)))
                found.setdefault((None, text_value), {"plural": None, "where": set()})["where"].add(where)
            continue
        if isinstance(node, ast.Call):
            _from_call(node, where, found)


def collect():
    """{"django": {(ctx, msgid): {"plural", "where"}}, "djangojs": {…}}"""
    found = {"django": {}, "djangojs": {}}
    roots = [BUILDER, BUILDER.parent / "extensions"]
    for root in roots:
        for path in sorted(root.rglob("*")):
            if SKIP_DIRS & set(path.parts) or path.name == "tests.py" or not path.is_file():
                continue
            rel = path.relative_to(BUILDER.parent).as_posix()
            if path.suffix == ".py":
                for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                    if isinstance(node, ast.Call):
                        _from_call(node, rel, found["django"])
            elif "templates" in path.parts and path.suffix in (".html", ".txt", ".js"):
                _scan_loose(templatize(path.read_text(encoding="utf-8"), origin=str(path)), rel, found["django"])
            elif path.suffix == ".js":
                _scan_loose(path.read_text(encoding="utf-8"), rel, found["djangojs"])
    return found


# ---------- .po lesen, schreiben, kompilieren ----------

def parse_po(path):
    entries, cur, last = [], None, None

    def fresh():
        return {"ctx": None, "id": None, "plural": None, "str": None, "comments": []}

    cur = fresh()
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            if cur["id"] is not None:
                entries.append(cur)
            cur, last = fresh(), None
        elif line.startswith("#"):
            cur["comments"].append(line)
        elif line.startswith('"'):
            field, idx = last
            if idx is None:
                cur[field] += ast.literal_eval(line)
            else:
                cur[field][idx] += ast.literal_eval(line)
        else:
            m = re.match(r'^(msgctxt|msgid_plural|msgid|msgstr)(?:\[(\d+)\])?\s+(".*")$', line)
            if not m:
                raise CommandError(f"{path}: unbekannte Zeile {line!r}")
            key, idx, value = m.group(1), m.group(2), ast.literal_eval(m.group(3))
            field = {"msgctxt": "ctx", "msgid": "id", "msgid_plural": "plural", "msgstr": "str"}[key]
            if idx is not None:
                cur["str"] = cur["str"] if isinstance(cur["str"], list) else []
                cur["str"].extend([""] * (int(idx) + 1 - len(cur["str"])))
                cur["str"][int(idx)] = value
                last = ("str", int(idx))
            else:
                cur[field] = value
                last = (field, None)
    if cur["id"] is not None:
        entries.append(cur)
    return entries


def _quote(s):
    s = s.replace("\\", "\\\\").replace('"', '\\"').replace("\t", "\\t")
    if "\n" in s[:-1]:
        parts = s.split("\n")
        lines = [p + "\\n" for p in parts[:-1]] + ([parts[-1]] if parts[-1] else [])
        return '""\n' + "\n".join(f'"{p}"' for p in lines)
    return '"' + s.replace("\n", "\\n") + '"'


def format_entry(e):
    out = list(e["comments"])
    if e["ctx"] is not None:
        out.append("msgctxt " + _quote(e["ctx"]))
    out.append("msgid " + _quote(e["id"]))
    if e["plural"] is not None:
        out.append("msgid_plural " + _quote(e["plural"]))
        out += [f"msgstr[{i}] " + _quote(s) for i, s in enumerate(e["str"] if isinstance(e["str"], list) else ["", ""])]
    else:
        out.append("msgstr " + _quote(e["str"] if isinstance(e["str"], str) else ""))
    return "\n".join(out)


def is_fuzzy(e):
    return any(c.startswith("#,") and "fuzzy" in c for c in e["comments"])


def is_translated(e):
    s = e["str"]
    return (all(s) if isinstance(s, list) else bool(s)) and not is_fuzzy(e)


def compile_mo(po, mo):
    catalog = {}
    for e in parse_po(po):
        if any(c.startswith("#~") for c in e["comments"]):
            continue
        if e["id"] == "":
            catalog[b""] = (e["str"] or "").encode("utf-8")
            continue
        if not is_translated(e):
            continue
        key = e["id"] if e["plural"] is None else e["id"] + "\0" + e["plural"]
        if e["ctx"] is not None:
            key = e["ctx"] + "\x04" + key
        value = e["str"] if isinstance(e["str"], str) else "\0".join(e["str"])
        catalog[key.encode("utf-8")] = value.encode("utf-8")
    keys = sorted(catalog)
    ids = strs = b""
    offsets = []
    for k in keys:
        offsets.append((len(ids), len(k), len(strs), len(catalog[k])))
        ids += k + b"\0"
        strs += catalog[k] + b"\0"
    n = len(keys)
    key_start = 7 * 4 + 16 * n
    value_start = key_start + len(ids)
    table = []
    for o1, l1, _o2, _l2 in offsets:
        table += [l1, o1 + key_start]
    for _o1, _l1, o2, l2 in offsets:
        table += [l2, o2 + value_start]
    header = struct.pack("Iiiiiii", 0x950412DE, 0, n, 7 * 4, 7 * 4 + n * 8, 0, 0)
    Path(mo).write_bytes(header + struct.pack(f"{len(table)}i", *table) + ids + strs)
    return n


def missing(language="en"):
    """Fehlende Übersetzungen je Domäne: [(ctx, msgid, plural, where, vorhanden)]."""
    result = {}
    for domain, found in collect().items():
        po = BUILDER / "locale" / language / "LC_MESSAGES" / f"{domain}.po"
        entries = {(e["ctx"], e["id"]): e for e in parse_po(po)} if po.exists() else {}
        result[domain] = [
            (ctx, msgid, info["plural"], sorted(info["where"]), (ctx, msgid) in entries)
            for (ctx, msgid), info in sorted(found.items(), key=lambda kv: (sorted(kv[1]["where"])[0], kv[0][1]))
            if not ((ctx, msgid) in entries and is_translated(entries[(ctx, msgid)]))
        ]
    return result


class Command(BaseCommand):
    help = "Übersetzungen der Oberfläche prüfen, ergänzen und kompilieren (ohne GNU gettext)."

    def add_arguments(self, parser):
        parser.add_argument("aktion", choices=["pruefen", "ergaenzen", "kompilieren"])
        parser.add_argument("--sprache", default="en")

    def handle(self, *args, aktion, sprache, **options):
        if sprache not in dict(settings.LANGUAGES):
            raise CommandError(f"Die Sprache „{sprache}“ steht nicht in LANGUAGES.")
        folder = BUILDER / "locale" / sprache / "LC_MESSAGES"
        if aktion == "kompilieren":
            for domain in ("django", "djangojs"):
                count = compile_mo(folder / f"{domain}.po", folder / f"{domain}.mo")
                self.stdout.write(f"{domain}.mo: {count} Einträge")
            return
        todo = missing(sprache)
        if aktion == "pruefen":
            for domain, items in todo.items():
                for _ctx, msgid, _plural, where, _known in items:
                    self.stdout.write(f"{domain}: {where[0]}: {msgid}")
            total = sum(len(items) for items in todo.values())
            if total:
                raise CommandError(f"{total} Texte ohne Übersetzung. Mit „ergaenzen“ in die .po-Dateien "
                                   f"übernehmen, übersetzen, dann „kompilieren“.")
            self.stdout.write(self.style.SUCCESS("Alle Texte sind übersetzt."))
            return
        for domain, items in todo.items():
            po = folder / f"{domain}.po"
            entries = parse_po(po)
            new = [{"ctx": ctx, "id": msgid, "plural": plural, "str": ["", ""] if plural else "",
                    "comments": ["#: " + " ".join(where[:3])]}
                   for ctx, msgid, plural, where, known in items if not known]
            if new:
                text = "\n\n".join(format_entry(e) for e in entries + new) + "\n"
                po.write_text(text, encoding="utf-8", newline="\n")
            self.stdout.write(f"{domain}.po: {len(new)} neue Texte ergänzt, "
                              f"{len(items) - len(new)} vorhandene noch ohne Übersetzung")
