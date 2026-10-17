#!/usr/bin/env python3
"""Shared store of fetched article texts, outside any one clone.

SCREENY_TEXT_STORE overrides the folder. The default is ~/.screeny/fulltext_store.
The key is the file name used in fulltext/ (sa_<id>.txt or the Substack slug).

  python3 scripts/text_store.py import DIR [DIR ...]
  python3 scripts/text_store.py self-test
"""
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import ensure

BOT_PAGE = re.compile(r"press\s*&\s*hold|bot check|captcha", re.I)
MIN_WORDS = 20


def store_root():
    raw = (os.environ.get("SCREENY_TEXT_STORE") or "").strip()
    if raw:
        return os.path.expanduser(raw)
    return os.path.join(os.path.expanduser("~"), ".screeny", "fulltext_store")


def text_usable(text):
    """Reuse a saved article. A bot-check page or an empty file is not usable."""
    if BOT_PAGE.search(text or ""):
        return False
    return len((text or "").split()) >= MIN_WORDS


def _safe_name(name):
    base = os.path.basename(name or "")
    if not base or base in (".", "..") or os.sep in base:
        return ""
    return base


def read_text(path):
    try:
        return open(path, encoding="utf-8").read()
    except OSError:
        return ""


def publish(name, text):
    """Write usable text into the shared store under name. Return the path or ''."""
    safe = _safe_name(name)
    if not safe or not text_usable(text):
        return ""
    root = store_root()
    ensure(root)
    path = os.path.join(root, safe)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


def publish_file(path):
    text = read_text(path)
    if not text_usable(text):
        return ""
    return publish(os.path.basename(path), text)


def lookup(name):
    safe = _safe_name(name)
    if not safe:
        return ""
    text = read_text(os.path.join(store_root(), safe))
    return text if text_usable(text) else ""


def materialize(name, dest_dir):
    """Copy a usable store file into dest_dir. Return the text, or ''."""
    text = lookup(name)
    safe = _safe_name(name)
    if not text or not safe:
        return ""
    ensure(dest_dir)
    dest = os.path.join(dest_dir, safe)
    current = read_text(dest) if os.path.isfile(dest) else ""
    if not text_usable(current):
        with open(dest, "w", encoding="utf-8") as handle:
            handle.write(text)
    return text


def import_dirs(directories):
    """Copy usable .txt files from each directory tree into the store."""
    copied = 0
    skipped = 0
    for directory in directories:
        if not os.path.isdir(directory):
            print(f"skip missing {directory}")
            continue
        for dirpath, _dirs, files in os.walk(directory):
            for name in files:
                if not name.endswith(".txt"):
                    continue
                path = os.path.join(dirpath, name)
                if publish_file(path):
                    copied += 1
                else:
                    skipped += 1
    print(f"imported {copied} usable texts, skipped {skipped}")
    return copied


def self_test():
    """Offline. Uses a temporary SCREENY_TEXT_STORE and does not touch the home folder."""
    previous = os.environ.get("SCREENY_TEXT_STORE")
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["SCREENY_TEXT_STORE"] = os.path.join(tmp, "store")
        try:
            src = os.path.join(tmp, "fulltext")
            os.makedirs(src)
            good = " ".join(["alpha"] * 30)
            open(os.path.join(src, "sa_1.txt"), "w", encoding="utf-8").write(good)
            open(os.path.join(src, "slug.txt"), "w", encoding="utf-8").write(" ".join(["beta"] * 25))
            open(os.path.join(src, "sa_2.txt"), "w", encoding="utf-8").write("Press & Hold to continue")
            open(os.path.join(src, "empty.txt"), "w", encoding="utf-8").write("   \n")
            assert import_dirs([src]) == 2
            assert lookup("sa_2.txt") == ""
            assert lookup("empty.txt") == ""
            assert lookup("sa_1.txt").split()[0] == "alpha"
            dest = os.path.join(tmp, "fresh")
            copied = materialize("sa_1.txt", dest)
            assert copied.split()[0] == "alpha"
            assert open(os.path.join(dest, "sa_1.txt"), encoding="utf-8").read().split()[0] == "alpha"
            assert materialize("sa_2.txt", dest) == ""
            assert not os.path.exists(os.path.join(dest, "sa_2.txt"))
        finally:
            if previous is None:
                os.environ.pop("SCREENY_TEXT_STORE", None)
            else:
                os.environ["SCREENY_TEXT_STORE"] = previous
    print("text_store self-test ok")
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in ("import", "self-test"):
        print("usage: python3 scripts/text_store.py import DIR [DIR ...]")
        print("       python3 scripts/text_store.py self-test")
        return 2
    if argv[0] == "self-test":
        return self_test()
    if len(argv) < 2:
        print("import needs at least one directory")
        return 2
    import_dirs(argv[1:])
    return 0


if __name__ == "__main__":
    sys.exit(main())
