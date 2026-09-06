#!/usr/bin/env python3
"""Rigenera il blocco CTF-STATS del profile README a partire dal repo writeupctf.

Uso:
    python tools/update_readme.py --writeups ./writeupctf --readme README.md

Layout atteso dei writeup (con fallback tollerante):

    writeupctf/
        mntcrl-2026/
            crypto/
                hyperelliptic-drift.md
            pwn/
                aname.md

Cioe': <competizione>/<categoria>/<challenge>.md
Ogni file puo' sovrascrivere i dati dedotti dal path con un front matter YAML
minimale:

    ---
    title: Hyperelliptic Drift
    category: crypto
    competition: mntcrl 2026
    date: 2026-08-30
    ---

Nessuna dipendenza esterna: si parsa solo il sottoinsieme di YAML che serve.
Exit code 0 se il README e' gia' aggiornato, 0 anche dopo la riscrittura;
exit 1 solo su errore vero (marker mancanti, path inesistente).
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from dataclasses import dataclass
from pathlib import Path

START = "<!-- CTF-STATS:START -->"
END = "<!-- CTF-STATS:END -->"

REPO_URL = "https://github.com/flavioabbinante/writeupctf/blob/main"

# Cartelle da ignorare durante la scansione.
SKIP_DIRS = {".git", ".github", "assets", "img", "images", "files", "templates"}
SKIP_FILES = {"readme.md", "index.md", "template.md", "contributing.md"}

# Ordine fisso in tabella: le categorie che mi interessano vengono prima,
# le altre in coda in ordine alfabetico.
CATEGORY_ORDER = ["pwn", "rev", "crypto", "forensics", "web", "misc", "osint"]

CATEGORY_ALIASES = {
    "reverse": "rev",
    "reversing": "rev",
    "reverse-engineering": "rev",
    "cryptography": "crypto",
    "forensic": "forensics",
    "binary": "pwn",
    "pwning": "pwn",
    "web-exploitation": "web",
}

RECENT_COUNT = 5


@dataclass
class Writeup:
    title: str
    category: str
    competition: str
    date: dt.date | None
    path: Path

    @property
    def link(self) -> str:
        return f"{REPO_URL}/{self.path.as_posix()}"


def parse_front_matter(text: str) -> dict[str, str]:
    """Estrae un front matter YAML piatto (chiave: valore). Niente liste, niente nesting."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    meta: dict[str, str] = {}
    for line in text[3:end].splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition(":")
        if not sep:
            continue
        meta[key.strip().lower()] = value.strip().strip("\"'")
    return meta


def first_heading(text: str) -> str | None:
    match = re.search(r"^#\s+(.+)$", text, flags=re.MULTILINE)
    return match.group(1).strip() if match else None


def humanize(slug: str) -> str:
    return re.sub(r"[-_]+", " ", slug).strip().title()


def normalize_category(raw: str) -> str:
    key = raw.strip().lower()
    return CATEGORY_ALIASES.get(key, key)


def parse_date(raw: str | None) -> dt.date | None:
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return dt.datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def collect(root: Path) -> list[Writeup]:
    writeups: list[Writeup] = []

    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if rel.name.lower() in SKIP_FILES:
            continue

        text = path.read_text(encoding="utf-8", errors="replace")
        meta = parse_front_matter(text)
        parts = rel.parts

        # Dal path: <competizione>/<categoria>/<file>.md
        path_competition = parts[0] if len(parts) >= 3 else ""
        path_category = parts[1] if len(parts) >= 3 else (parts[0] if len(parts) == 2 else "")

        category = normalize_category(meta.get("category") or path_category or "misc")
        competition = meta.get("competition") or humanize(path_competition)
        title = meta.get("title") or first_heading(text) or humanize(rel.stem)

        writeups.append(
            Writeup(
                title=title,
                category=category,
                competition=competition,
                date=parse_date(meta.get("date")),
                path=rel,
            )
        )

    return writeups


def render(writeups: list[Writeup]) -> str:
    if not writeups:
        return "_Nessun writeup ancora pubblicato._"

    counts: dict[str, int] = {}
    for w in writeups:
        counts[w.category] = counts.get(w.category, 0) + 1

    def sort_key(category: str) -> tuple[int, str]:
        if category in CATEGORY_ORDER:
            return (CATEGORY_ORDER.index(category), "")
        return (len(CATEGORY_ORDER), category)

    lines: list[str] = []
    lines.append("**Writeup pubblicati per categoria**")
    lines.append("")
    lines.append("| Categoria | Writeup |")
    lines.append("| --- | ---: |")
    for category in sorted(counts, key=sort_key):
        lines.append(f"| {category} | {counts[category]} |")
    lines.append(f"| **totale** | **{len(writeups)}** |")
    lines.append("")

    # I piu' recenti: prima quelli con data, poi gli altri in ordine alfabetico.
    dated = sorted((w for w in writeups if w.date), key=lambda w: w.date, reverse=True)
    undated = sorted((w for w in writeups if not w.date), key=lambda w: w.title.lower())
    recent = (dated + undated)[:RECENT_COUNT]

    lines.append("**Ultimi writeup**")
    lines.append("")
    for w in recent:
        suffix = f" · {w.competition}" if w.competition else ""
        lines.append(f"- [{w.title}]({w.link}) — `{w.category}`{suffix}")

    return "\n".join(lines)


def splice(readme: str, block: str) -> str:
    if START not in readme or END not in readme:
        raise SystemExit(f"Marker mancanti nel README: servono {START} e {END}")
    pattern = re.compile(
        re.escape(START) + r".*?" + re.escape(END),
        flags=re.DOTALL,
    )
    note = "<!-- Blocco generato da tools/update_readme.py — non modificare a mano. -->"
    replacement = f"{START}\n{note}\n\n{block}\n{END}"
    return pattern.sub(lambda _: replacement, readme, count=1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--writeups", default="writeupctf", type=Path)
    parser.add_argument("--readme", default="README.md", type=Path)
    parser.add_argument(
        "--check",
        action="store_true",
        help="non scrive nulla, esce con 1 se il README andrebbe aggiornato",
    )
    args = parser.parse_args()

    if not args.writeups.is_dir():
        raise SystemExit(f"Cartella writeup non trovata: {args.writeups}")
    if not args.readme.is_file():
        raise SystemExit(f"README non trovato: {args.readme}")

    writeups = collect(args.writeups)
    readme = args.readme.read_text(encoding="utf-8")
    updated = splice(readme, render(writeups))

    if updated == readme:
        print(f"README gia' aggiornato ({len(writeups)} writeup).")
        return 0

    if args.check:
        print("Il README andrebbe rigenerato.")
        return 1

    args.readme.write_text(updated, encoding="utf-8")
    print(f"README aggiornato ({len(writeups)} writeup).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
