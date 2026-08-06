#!/usr/bin/env python3
"""
srtkit.py — deterministic SRT plumbing for a Claude Code translation workflow.

This script does NOT translate anything and makes no network calls. It handles
the parts a language model should never be trusted with (timestamps, cue
indices, tag preservation, validation) and leaves the actual translation to
Claude Code.

Workflow:
    python srtkit.py extract ./subs --out ./work
        -> ./work/<name>/skeleton.json     timing data, never edited
        -> ./work/<name>/part01.txt ...    numbered text for translation

    (Claude Code translates part01.txt -> part01.es.txt, etc.)

    python srtkit.py merge ./work --out ./subs_es
        -> rebuilds real .srt files from skeleton + translated text

    python srtkit.py check ./subs ./subs_es
        -> verifies nothing drifted: cue counts, indices, timings, line lengths

Line format inside part files:
    [142] ¿En serio hiciste eso?
    [143] Primera línea\nSegunda línea      <- literal \n means a line break
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

MAX_LINE_CHARS = 42
CUES_PER_PART = 120          # cues per part file — a comfortable working chunk

TAG_PATTERN = re.compile(r"(<[^>]+>|\{\\[^}]+\})")
TIMECODE = re.compile(
    r"(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})(.*)"
)
LINE_ENTRY = re.compile(r"^\[(\d+)\]\s?(.*)$")


# --------------------------------------------------------------------------
# Model
# --------------------------------------------------------------------------


@dataclass
class Cue:
    index: int
    start: str
    end: str
    trailer: str = ""
    lines: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    @property
    def flat(self) -> str:
        """Single-line form using a literal \\n for internal breaks."""
        return self.text.replace("\n", "\\n")

    def translatable(self) -> bool:
        stripped = TAG_PATTERN.sub("", self.text).strip()
        return bool(re.search(r"[A-Za-z]", stripped))

    def duration(self) -> float:
        return _secs(self.end) - _secs(self.start)


def _secs(tc: str) -> float:
    tc = tc.replace(".", ",")
    hh, mm, rest = tc.split(":")
    ss, ms = rest.split(",")
    return int(hh) * 3600 + int(mm) * 60 + int(ss) + int(ms) / 1000


# --------------------------------------------------------------------------
# Parse / write
# --------------------------------------------------------------------------


def parse_srt(path: Path) -> list[Cue]:
    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")

    cues: list[Cue] = []
    for chunk in re.split(r"\n{2,}", raw.strip()):
        lines = chunk.split("\n")
        tc_pos = next((i for i, ln in enumerate(lines) if TIMECODE.search(ln)), None)
        if tc_pos is None:
            continue
        m = TIMECODE.search(lines[tc_pos])
        idx_line = lines[tc_pos - 1].strip() if tc_pos > 0 else ""
        try:
            index = int(idx_line)
        except ValueError:
            index = len(cues) + 1
        cues.append(Cue(
            index=index,
            start=m.group(1),
            end=m.group(2),
            trailer=m.group(3).rstrip(),
            lines=[ln for ln in lines[tc_pos + 1:] if ln.strip()],
        ))
    return cues


def write_srt(cues: list[Cue], path: Path) -> None:
    out = []
    for c in cues:
        out += [str(c.index), f"{c.start} --> {c.end}{c.trailer}", c.text, ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def rewrap(text: str, limit: int = MAX_LINE_CHARS) -> str:
    """Re-balance into <=2 readable lines. Dash dialogue keeps its structure."""
    lines = text.split("\n")
    if any(ln.lstrip().startswith(("-", "–", "—")) for ln in lines):
        return text
    if all(len(ln) <= limit for ln in lines):
        return text
    flat = " ".join(ln.strip() for ln in lines).strip()
    if len(flat) <= limit:
        return flat
    wrapped = textwrap.wrap(flat, width=max(limit, len(flat) // 2 + 1))
    return "\n".join(wrapped[:2]) if len(wrapped) > 2 else "\n".join(wrapped)


# --------------------------------------------------------------------------
# extract
# --------------------------------------------------------------------------


def cmd_extract(args) -> int:
    src = args.input
    files = [src] if src.is_file() else sorted(src.rglob("*.srt"))
    if not files:
        print("No .srt files found.", file=sys.stderr)
        return 1

    root = src.parent if src.is_file() else src
    args.out.mkdir(parents=True, exist_ok=True)

    for f in files:
        cues = parse_srt(f)
        targets = [c for c in cues if c.translatable()]
        stem = f.relative_to(root).with_suffix("").as_posix().replace("/", "__")
        d = args.out / stem
        d.mkdir(parents=True, exist_ok=True)

        (d / "skeleton.json").write_text(json.dumps({
            "source": str(f),
            "cues": [
                {"i": c.index, "s": c.start, "e": c.end,
                 "t": c.trailer, "x": c.text, "skip": not c.translatable()}
                for c in cues
            ],
        }, ensure_ascii=False, indent=1), encoding="utf-8")

        parts = [targets[i:i + args.chunk]
                 for i in range(0, len(targets), args.chunk)]
        for n, part in enumerate(parts, 1):
            body = "\n".join(f"[{c.index}] {c.flat}" for c in part)
            (d / f"part{n:02d}.txt").write_text(body + "\n", encoding="utf-8")

        print(f"{f.name}: {len(cues)} cues ({len(targets)} translatable) "
              f"-> {d}/ ({len(parts)} part files)")
    return 0


# --------------------------------------------------------------------------
# merge
# --------------------------------------------------------------------------


def parse_part(path: Path) -> dict[int, str]:
    out: dict[int, str] = {}
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
        if not raw.strip():
            continue
        m = LINE_ENTRY.match(raw)
        if not m:
            raise ValueError(f"{path.name}:{lineno} malformed line: {raw[:60]!r}")
        idx = int(m.group(1))
        if idx in out:
            raise ValueError(f"{path.name}:{lineno} duplicate cue id {idx}")
        out[idx] = m.group(2)
    return out


def cmd_merge(args) -> int:
    dirs = [d for d in sorted(args.work.iterdir())
            if d.is_dir() and (d / "skeleton.json").exists()]
    if not dirs:
        print("No extracted work folders found.", file=sys.stderr)
        return 1

    failures = 0
    for d in dirs:
        skel = json.loads((d / "skeleton.json").read_text(encoding="utf-8"))
        translated: dict[int, str] = {}
        part_files = sorted(d.glob("part*.es.txt"))

        if not part_files:
            print(f"  !! {d.name}: no part*.es.txt files — not translated yet",
                  file=sys.stderr)
            failures += 1
            continue

        try:
            for pf in part_files:
                for k, v in parse_part(pf).items():
                    translated[k] = v
        except ValueError as e:
            print(f"  !! {d.name}: {e}", file=sys.stderr)
            failures += 1
            continue

        wanted = {c["i"] for c in skel["cues"] if not c["skip"]}
        missing = sorted(wanted - set(translated))
        extra = sorted(set(translated) - wanted)
        if missing:
            print(f"  !! {d.name}: {len(missing)} cues missing "
                  f"(first: {missing[:8]})", file=sys.stderr)
            failures += 1
            continue
        if extra:
            print(f"  .. {d.name}: ignoring {len(extra)} unknown ids {extra[:5]}")

        cues = []
        for c in skel["cues"]:
            text = c["x"] if c["skip"] else translated[c["i"]].replace("\\n", "\n")
            cues.append(Cue(c["i"], c["s"], c["e"], c["t"],
                            rewrap(text).split("\n")))

        dst = args.out / f"{d.name}{args.suffix}.srt"
        write_srt(cues, dst)
        print(f"  {d.name}: {len(cues)} cues -> {dst}")

    print(f"\n{len(dirs) - failures}/{len(dirs)} merged.")
    return 1 if failures else 0


# --------------------------------------------------------------------------
# check
# --------------------------------------------------------------------------


def cmd_check(args) -> int:
    originals = {p.stem: p for p in sorted(args.original.rglob("*.srt"))}
    problems = 0

    for tp in sorted(args.translated.rglob("*.srt")):
        base = tp.stem
        for suf in (".es", "_es"):
            if base.endswith(suf):
                base = base[: -len(suf)]
        op = originals.get(base) or originals.get(tp.stem)
        if not op:
            print(f"  ?? {tp.name}: no matching original, skipped")
            continue

        oc, tc = parse_srt(op), parse_srt(tp)
        issues = []

        if len(oc) != len(tc):
            issues.append(f"cue count {len(oc)} -> {len(tc)}")
        for a, b in zip(oc, tc):
            if a.index != b.index:
                issues.append(f"index drift at {a.index}")
                break
            if (a.start, a.end) != (b.start, b.end):
                issues.append(f"timing changed at cue {a.index}")
                break

        untranslated = [b.index for a, b in zip(oc, tc)
                        if a.translatable() and a.text.strip() == b.text.strip()]
        if len(untranslated) > max(3, len(tc) * 0.02):
            issues.append(f"{len(untranslated)} cues identical to source")

        long_lines = [c.index for c in tc
                      for ln in c.lines if len(ln) > args.max_chars]
        fast = [c.index for c in tc
                if c.duration() > 0
                and len(c.text.replace("\n", " ")) / c.duration() > 20]

        status = "OK " if not issues else "!! "
        print(f"  {status}{tp.name}: {len(tc)} cues")
        for i in issues:
            print(f"       - {i}")
            problems += 1
        if long_lines:
            print(f"       ~ {len(long_lines)} lines over {args.max_chars} chars "
                  f"(e.g. {long_lines[:5]})")
        if fast:
            print(f"       ~ {len(fast)} cues over 20 chars/sec — hard to read "
                  f"(e.g. {fast[:5]})")

    print(f"\n{problems} structural problem(s).")
    return 1 if problems else 0


# --------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    sub = ap.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("extract", help="SRT -> skeleton + translatable text")
    e.add_argument("input", type=Path)
    e.add_argument("--out", type=Path, default=Path("work"))
    e.add_argument("--chunk", type=int, default=CUES_PER_PART)
    e.set_defaults(fn=cmd_extract)

    m = sub.add_parser("merge", help="skeleton + translated text -> SRT")
    m.add_argument("work", type=Path)
    m.add_argument("--out", type=Path, default=Path("subs_es"))
    m.add_argument("--suffix", default=".es")
    m.set_defaults(fn=cmd_merge)

    c = sub.add_parser("check", help="validate translated SRTs against originals")
    c.add_argument("original", type=Path)
    c.add_argument("translated", type=Path)
    c.add_argument("--max-chars", type=int, default=MAX_LINE_CHARS)
    c.set_defaults(fn=cmd_check)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
