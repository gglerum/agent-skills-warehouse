#!/usr/bin/env python3
"""Count session transcripts since the last transcript review (read-only unless --mark).
Usage: python3 -I scripts/review_due.py [--root DIR] [--threshold 20] [--config-dir DIR] [--mark]
Transcripts: <config>/projects/<key>/*.jsonl (key = absolute root with / and . replaced by -).
Marker: <config>/session-reviews/<key>/LAST_REVIEW (mtime = last review). --mark touches it (run at the end of a review).
Exit 0 always; prints one line. Due when count >= threshold."""
import argparse, os, sys
from pathlib import Path


def key_for(root):
    return str(Path(root).resolve()).replace("/", "-").replace(".", "-")


def status(root, config_dir, threshold=20):
    k = key_for(root)
    marker = Path(config_dir) / "session-reviews" / k / "LAST_REVIEW"
    since = marker.stat().st_mtime if marker.exists() else 0
    files = (Path(config_dir) / "projects" / k).glob("*.jsonl")
    n = sum(1 for f in files if f.stat().st_mtime > since)
    return n, n >= threshold, marker


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--threshold", type=int, default=20)
    ap.add_argument("--config-dir", default=os.environ.get("CLAUDE_CONFIG_DIR") or str(Path.home() / ".claude"))
    ap.add_argument("--mark", action="store_true")
    a = ap.parse_args(argv)
    n, due, marker = status(a.root, a.config_dir, a.threshold)
    if a.mark:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
        os.utime(marker)
        print("review marked: %s" % marker)
        return 0
    print("transcript review: %s (%d sessions since last review, threshold %d)%s"
          % ("DUE" if due else "not due", n, a.threshold, "; run skill transcript-review at session start or end" if due else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
