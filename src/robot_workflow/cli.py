"""Command-line entry point; sources are never imported or executed."""

import argparse
import json
from pathlib import Path
import subprocess
import sys

from .engine import compare, read_json, snapshot, validate_config, write_json
from .report import render
from .verification import verify


def fetch(config, root):
    validate_config(config)
    root = Path(root).resolve()
    for repo in config["repositories"]:
        destination = (root / repo["path"]).resolve()
        if not destination.is_relative_to(root):
            raise ValueError("Destination escapes --root")
        if destination.exists():
            raise ValueError(f"Destination exists; refusing to replace it: {destination}")
        url = repo.get("url", "")
        if not url.startswith("https://github.com/") or not url.endswith(".git"):
            raise ValueError("fetch accepts HTTPS github.com .git URLs; other checkouts can be provided locally")
        destination.parent.mkdir(parents=True, exist_ok=True)
        command = ["git", "clone", "--depth", "2", "--filter=blob:none", "--no-checkout"]
        if repo.get("ref"):
            command.extend(["--branch", repo["ref"]])
        command.extend(["--", url, str(destination)])
        subprocess.run(command, check=True, timeout=300)
        patterns = sorted({a["glob"] for n in config["nodes"] if n["repository"] == repo["id"] for a in n["artifacts"]})
        subprocess.run(["git", "-C", str(destination), "sparse-checkout", "set", "--no-cone", "--", *patterns], check=True, timeout=300)
        subprocess.run(["git", "-C", str(destination), "checkout"], check=True, timeout=300)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Robot Workflow: versioned engineering dependency and evidence analysis")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("snapshot", "fetch"):
        p = sub.add_parser(command)
        p.add_argument("--config", required=True)
        p.add_argument("--root", required=True, help="Directory containing repository paths from the config")
        if command == "snapshot":
            p.add_argument("--output", required=True)
            p.add_argument("--label", default="baseline")
    p = sub.add_parser("compare")
    p.add_argument("--before", required=True)
    p.add_argument("--after", required=True)
    p.add_argument("--evidence")
    p.add_argument("--output", required=True)
    p.add_argument("--html")
    p.add_argument("--fail-on-impact", action="store_true", help="Return 2 for semantic changes or unknown source coverage")
    p = sub.add_parser("verify")
    p.add_argument("--snapshot", required=True)
    p.add_argument("--output", required=True)
    p = sub.add_parser("report")
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "fetch":
            fetch(read_json(args.config), args.root)
        elif args.command == "snapshot":
            result = snapshot(read_json(args.config), args.root, args.label)
            write_json(args.output, result)
            print(json.dumps({"snapshot_id": result["snapshot_id"], "nodes": len(result["nodes"]),
                              "unknown": sum(bool(n["problems"]) for n in result["nodes"].values())}))
        elif args.command == "compare":
            result = compare(read_json(args.before), read_json(args.after), read_json(args.evidence) if args.evidence else None)
            write_json(args.output, result)
            if args.html:
                render(result, args.html)
            print(json.dumps(result["summary"]))
            if args.fail_on_impact and (result["summary"]["semantic_changes"] or result["summary"]["unknown"] or result["summary"]["unregistered_changes"]):
                return 2
        elif args.command == "verify":
            result = verify(read_json(args.snapshot))
            write_json(args.output, result)
            print(json.dumps({"recorded": len(result["records"]), "failed": sum(r["result"] == "fail" for r in result["records"])}))
            if any(r["result"] == "fail" for r in result["records"]):
                return 2
        else:
            value = read_json(args.input)
            if value.get("kind") != "impact_report":
                raise ValueError("Expected an impact_report")
            render(value, args.output)
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as exc:
        print(f"robot-workflow: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
