#!/usr/bin/env python3
"""
Release discipline: one-command deploy/revert flow.
Usage:
  python deploy.py promote <version>  # Deploy to production
  python deploy.py revert             # Rollback to previous version
  python deploy.py status             # Show current deployed version
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime
import json


RELEASE_DIR = Path("./releases")
CURRENT_LINK = RELEASE_DIR / "current"
MANIFEST_FILE = RELEASE_DIR / "manifest.json"


def init_release_dir():
    RELEASE_DIR.mkdir(exist_ok=True)
    if not MANIFEST_FILE.exists():
        MANIFEST_FILE.write_text(json.dumps({"releases": [], "current": None}))


def load_manifest() -> dict:
    return json.loads(MANIFEST_FILE.read_text())


def save_manifest(manifest: dict):
    MANIFEST_FILE.write_text(json.dumps(manifest, indent=2))


def promote(version: str) -> bool:
    """Promote version to production (create symlink + log)."""
    init_release_dir()
    release_path = RELEASE_DIR / version
    if not release_path.exists():
        print(f"❌ Release {version} not found")
        return False

    manifest = load_manifest()
    prev = manifest.get("current")

    # Smoke test: run quick validation
    result = __import__("subprocess").run(
        ["python", "-m", "pytest", "testing/", "-q"],
        cwd=str(release_path),
        capture_output=True,
    )
    if result.returncode != 0:
        print(f"❌ Smoke tests failed for {version}")
        return False

    # Atomic promote
    if CURRENT_LINK.exists():
        CURRENT_LINK.unlink()
    CURRENT_LINK.symlink_to(release_path)

    manifest["current"] = version
    manifest["releases"].append({"version": version, "promoted_at": datetime.utcnow().isoformat(), "previous": prev})
    save_manifest(manifest)

    print(f"✅ Promoted {version} (previous: {prev})")
    return True


def revert() -> bool:
    """Revert to previous version."""
    init_release_dir()
    manifest = load_manifest()
    releases = manifest.get("releases", [])

    if len(releases) < 2:
        print("❌ No previous release to revert to")
        return False

    prev_release = releases[-2]
    prev_version = prev_release["version"]

    if CURRENT_LINK.exists():
        CURRENT_LINK.unlink()
    release_path = RELEASE_DIR / prev_version
    CURRENT_LINK.symlink_to(release_path)

    manifest["current"] = prev_version
    save_manifest(manifest)

    print(f"✅ Reverted to {prev_version}")
    return True


def status():
    """Show current deployment status."""
    init_release_dir()
    manifest = load_manifest()
    current = manifest.get("current", "none")
    releases = manifest.get("releases", [])

    print(f"Current version: {current}")
    print(f"Total releases: {len(releases)}")
    if releases:
        print("\nRecent releases:")
        for r in releases[-5:]:
            print(f"  {r['version']} (promoted: {r.get('promoted_at', 'N/A')})")


def main():
    parser = argparse.ArgumentParser(description="Release discipline script")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("promote", help="Promote version to production").add_argument("version")
    subparsers.add_parser("revert", help="Revert to previous version")
    subparsers.add_parser("status", help="Show deployment status")

    args = parser.parse_args()

    if args.command == "promote":
        sys.exit(0 if promote(args.version) else 1)
    elif args.command == "revert":
        sys.exit(0 if revert() else 1)
    elif args.command == "status":
        status()
        sys.exit(0)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
