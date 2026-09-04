#!/usr/bin/env python3
"""
Undo the '-2' filename mangling in an archived copy.

The archive was written by a copy that collided on every name: the real file
was saved with '-2' appended to its stem, and an empty directory was left
holding the original name. This puts the file back under its own name.

    python tools/demangle.py <root>            plan only, changes nothing
    python tools/demangle.py <root> --apply    execute it, journalling each rename
    python tools/demangle.py --undo <journal>  reverse a previous --apply

The root is always given explicitly, never defaulted from config: this
renames files, and a tool that can be run destructively with no arguments
is one keystroke from being run on the wrong tree.

A pair is only ever acted on when the target name is held by an EMPTY
DIRECTORY. A file that is genuinely named 'foo-2.mp3' has no such twin, so it
is reported and skipped rather than renamed onto something else.

If the plan contains any problem at all, nothing is executed. This is
all-or-nothing by design: a half-done rename pass over tens of thousands of
files is far worse than one that refused to start.
"""

import argparse
import json
import os
import sys
import time


def target_of(name):
    """'foo-2.mp3' -> 'foo.mp3'. None if the name doesn't carry the marker."""
    stem, dot, ext = name.partition(".")
    return stem[:-2] + dot + ext if stem.endswith("-2") else None


def build_plan(root):
    """Walk once and classify every mangled file.

    Returns (pairs, left_alone, problems). Whether a name is taken, and whether
    a twin directory is empty, are both read out of what os.walk already
    reported, so classifying 36,000 files costs no syscalls beyond the walk.

    An unreadable directory raises rather than being silently misread as
    occupied, which would otherwise look like a conflict that isn't one.
    """

    def boom(err):
        raise err

    empty_dirs, found = set(), []
    for dirpath, dirnames, filenames in os.walk(root, onerror=boom):
        if not dirnames and not filenames:
            empty_dirs.add(dirpath)
        subdirs, files = set(dirnames), set(filenames)
        for name in filenames:
            target = target_of(name)
            if not target:
                # None = not mangled. Empty = a file named exactly '-2', whose
                # target would resolve to the parent directory itself.
                continue
            found.append((dirpath, name, target, target in subdirs, target in files))

    # Resolved after the walk, because a twin directory is often visited later
    # than the file that names it.
    pairs, left_alone, problems = [], [], []
    for dirpath, name, target, twin_is_dir, twin_is_file in found:
        src = os.path.join(dirpath, name)
        dst = os.path.join(dirpath, target)
        if twin_is_dir and dst in empty_dirs:
            pairs.append((src, dst))
        elif twin_is_dir:
            # A populated directory is real content, not a mangling artifact.
            problems.append(f"twin directory is not empty: {src!r}")
        elif twin_is_file:
            problems.append(f"a file already holds the target name: {src!r}")
        else:
            left_alone.append(src)

    seen = {}
    for src, dst in pairs:
        if dst in seen:
            problems.append(f"two files claim {dst!r}: {seen[dst]!r} and {src!r}")
        seen[dst] = src

    return pairs, left_alone, problems


def apply_plan(pairs, journal_path):
    """rmdir the blocker, then rename. Stops dead on the first surprise."""
    done = 0
    # 'x' mode: refuse to open an existing file, so no run can ever overwrite
    # another run's journal and strip away its undo.
    with open(journal_path, "x", encoding="utf-8", buffering=1) as journal:
        for src, dst in pairs:
            # rmdir refuses a non-empty directory, so it is itself the check
            # that we are removing nothing but the empty placeholder.
            os.rmdir(dst)

            # os.rename would fail with EISDIR if anything still occupied dst,
            # and never moves a file *into* a directory the way `mv` does.
            os.rename(src, dst)

            if not os.path.isfile(dst) or os.path.exists(src):
                raise RuntimeError(f"rename did not take effect: {src} -> {dst}")

            journal.write(json.dumps({"from": src, "to": dst}) + "\n")
            done += 1
            if done % 2000 == 0:
                print(f"  {done}/{len(pairs)}")
    return done


def undo(journal_path):
    """Reverse a completed run: put each file back and restore its placeholder."""
    entries = [json.loads(line) for line in open(journal_path, encoding="utf-8")]
    for e in reversed(entries):
        if not os.path.isfile(e["to"]):
            print(f"  skip (not where we left it): {e['to']}", file=sys.stderr)
            continue
        os.rename(e["to"], e["from"])
        os.mkdir(e["to"])
    print(f"reversed {len(entries)} renames")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--undo", metavar="JOURNAL")
    args = ap.parse_args()

    if args.undo:
        undo(args.undo)
        return

    if not args.root or not os.path.isdir(args.root):
        sys.exit("give me a directory to work on")

    root = os.path.abspath(args.root)
    pairs, left_alone, problems = build_plan(root)

    print(f"{root}")
    print(f"  {len(pairs)} files to rename")
    print(f"  {len(left_alone)} genuinely named '-2', left alone")
    for src in left_alone[:10]:
        print(f"      {src[len(root) + 1:]}")

    # Written beside us, never inside the tree we are about to modify.
    manifest = os.path.abspath("demangle-plan.tsv")
    with open(manifest, "w", encoding="utf-8") as fh:
        for src, dst in pairs:
            fh.write(f"{src}\t{dst}\n")
    print(f"  plan written to {manifest}")

    if problems:
        print(f"\nREFUSING TO RUN — {len(problems)} problems:", file=sys.stderr)
        for p in problems[:20]:
            print(f"  {p}", file=sys.stderr)
        sys.exit(1)

    if not args.apply:
        print("\ndry run — nothing changed. add --apply to execute.")
        return

    if not pairs:
        print("\nnothing to rename.")
        return

    stamp = time.strftime("%Y%m%d-%H%M%S")
    journal = os.path.abspath(f"demangle-journal-{stamp}.jsonl")
    done = apply_plan(pairs, journal)
    print(f"\nrenamed {done} files")
    print(f"journal: {journal}")
    print(f"to reverse: python tools/demangle.py --undo {journal}")


if __name__ == "__main__":
    main()
