"""Fetch the exact Swiftlet source used by local and cloud builds."""
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((ROOT / "dependencies/swiftlet.json").read_text())
DEST = ROOT / ".dependencies/swiftlet"


def git(*args, capture=False):
    result = subprocess.run(
        ["git", "-C", str(DEST), *args], check=True, text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    return result.stdout.strip() if capture else None


def main():
    if not (DEST / ".git").exists():
        if DEST.exists() and any(DEST.iterdir()):
            raise SystemExit(f"Refusing to overwrite non-Git directory: {DEST}")
        DEST.mkdir(parents=True, exist_ok=True)
        git("init")
        git("remote", "add", "origin", LOCK["repository"])
    if git("remote", "get-url", "origin", capture=True) != LOCK["repository"]:
        raise SystemExit("Swiftlet remote differs from dependencies/swiftlet.json")
    if git("status", "--porcelain", capture=True):
        raise SystemExit("Swiftlet has local changes; refusing to overwrite them")
    git("fetch", "--depth", "1", "origin", LOCK["revision"])
    git("checkout", "--detach", LOCK["revision"])
    if git("rev-parse", "HEAD", capture=True) != LOCK["revision"]:
        raise SystemExit("Swiftlet revision verification failed")
    # Keep generated SPM files out of Git while versioning their authoritative
    # copies beside the engine revision. Both cloud workflows use this setup.
    for source, target in (
        (ROOT / "dependencies/swiftlet.Package.resolved", DEST / "Package.resolved"),
        (ROOT / "dependencies/app.Package.resolved", ROOT / "localLLM.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved"),
    ):
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    print(f"Swiftlet ready: {LOCK['revision']}")


if __name__ == "__main__":
    main()
