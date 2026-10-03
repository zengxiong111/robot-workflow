"""Command-line entry point; sources are never imported or executed."""

import argparse
import json
from pathlib import Path
import subprocess
import sys

from .engine import compare, read_json, snapshot, validate_config, write_json
from .report import render
from .verification import verify


def initialize(args, output):
    from .discovery import discover

    output = Path(output).resolve()
    if output.exists():
        raise ValueError("Configuration exists; choose a new output to preserve reviewed dependencies")
    config = discover(args.root, args.project)
    for repo in config['repositories']:
        if output.is_relative_to((Path(args.root) / repo['path']).resolve()):
            raise ValueError("Keep generated workflow configuration outside inspected repositories")
    if args.owner:
        for node in config['nodes']:
            node['owner'] = args.owner
    notifications = {}
    if args.webhook_env:
        notifications['webhook_env'] = args.webhook_env
    if args.route:
        recipients = {}
        for item in args.route:
            owner, separator, env = item.partition('=')
            if not separator or not owner or not env:
                raise ValueError("Notification route must be OWNER=ENVIRONMENT_VARIABLE")
            recipients[owner] = env
        notifications['recipients'] = recipients
    if notifications:
        config['notifications'] = notifications
    write_json(output, config)
    print(json.dumps({'config': str(output), 'repositories': len(config['repositories']),
                      'inferred_dependencies': len(config['edges'])}))
    return config


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
    p = sub.add_parser('setup', help='Guided setup and first local report; no Git updates')
    p.add_argument('--root')
    p.add_argument('--state-dir')
    p.add_argument('--project', default='Robot Workflow')
    p.add_argument('--owner')
    p.add_argument('--lang', choices=['zh', 'en'], default='zh')
    p.add_argument('--yes', action='store_true', help='Use defaults; inferred dependencies remain unreviewed')
    p.add_argument('--no-open', action='store_true')
    p = sub.add_parser('doctor', help='Explain configuration, coverage and local Git issues')
    p.add_argument('--config', required=True)
    p.add_argument('--root', required=True)
    p = sub.add_parser('open', help='Open the latest local monitor report')
    p.add_argument('--state-dir', required=True)
    for command in ('init', 'start'):
        p = sub.add_parser(command, help='Discover local repositories and bootstrap a workflow')
        p.add_argument('--root', required=True)
        p.add_argument('--project', default='Robot Workflow')
        p.add_argument('--owner', help='Initial owner for all discovered components; editable per node')
        p.add_argument('--webhook-env', help='Environment variable containing a default notification webhook URL')
        p.add_argument('--route', action='append', help='Owner-specific notification route: OWNER=ENVIRONMENT_VARIABLE')
        if command == 'init':
            p.add_argument('--output', required=True)
        else:
            p.add_argument('--state-dir', required=True)
            p.add_argument('--interval', type=float, default=30)
            p.add_argument('--once', action='store_true')
            p.add_argument('--no-update', action='store_true')
    p = sub.add_parser('sync', help='Fast-forward clean existing repository branches')
    p.add_argument('--config', required=True)
    p.add_argument('--root', required=True)
    p = sub.add_parser('watch', help='Poll repositories, analyze changes and notify owners')
    p.add_argument('--config', required=True)
    p.add_argument('--root', required=True)
    p.add_argument('--state-dir', required=True)
    p.add_argument('--interval', type=float, default=30)
    p.add_argument('--once', action='store_true')
    p.add_argument('--no-update', action='store_true')
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
    p.add_argument("--root", help="Source root for explicit command checks")
    p.add_argument("--run-checks", action="store_true", help="Explicitly execute configured validation commands")
    p = sub.add_parser("cases", help="Create and manage local change cases")
    p.add_argument("action", choices=["sync", "list", "update"])
    p.add_argument("--state", required=True)
    p.add_argument("--input", help="Impact report for sync")
    p.add_argument("--id", help="Case identity for update")
    p.add_argument("--status", choices=["open", "claimed", "resolved", "dismissed"])
    p.add_argument("--actor")
    p.add_argument("--owner")
    p.add_argument("--note", default="")
    p = sub.add_parser("report")
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--cases", help="Local case state to embed in the report")
    args = parser.parse_args(argv)
    try:
        if args.command == 'setup':
            from .onboarding import setup
            return setup(args)
        elif args.command == 'doctor':
            from .diagnostics import inspect_workflow
            result = inspect_workflow(read_json(args.config), args.root)
            for issue in result['issues']:
                print(f"[{issue['severity']}] {issue['message']}\n  {issue['action']}")
            print(json.dumps(result, ensure_ascii=False))
            return 2 if any(i['severity'] == 'error' for i in result['issues']) else 0
        elif args.command == 'open':
            from .onboarding import latest_report, open_report
            path = latest_report(args.state_dir)
            print(str(path))
            open_report(path)
        elif args.command == 'init':
            initialize(args, args.output)
        elif args.command in ('watch', 'start'):
            from .monitor import watch
            root = Path(args.root).resolve()
            state = Path(args.state_dir).resolve()
            if state.is_relative_to(root):
                raise ValueError('state_dir must be outside the repository root')
            if args.interval <= 0 or not args.interval < float('inf'):
                raise ValueError('interval must be a positive finite number')
            if args.command == 'start':
                path = Path(args.state_dir).resolve() / 'workflow.json'
                config = read_json(path) if path.exists() else initialize(args, path)
            else:
                config = read_json(args.config)
            watch(config, args.root, args.state_dir, interval=args.interval,
                  once=args.once, no_update=args.no_update)
        elif args.command == 'sync':
            from .monitor import sync_repositories
            results = sync_repositories(read_json(args.config), args.root)
            print(json.dumps(results, ensure_ascii=False))
            if any(item['status'] == 'error' for item in results):
                return 1
            if any(item['status'] not in {'updated', 'current'} for item in results):
                return 2
        elif args.command == "fetch":
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
            result = verify(read_json(args.snapshot), root=args.root, run_commands=args.run_checks)
            write_json(args.output, result)
            print(json.dumps({"recorded": len(result["records"]), "failed": sum(r["result"] == "fail" for r in result["records"]),
                              "unknown": sum(r["result"] == "unknown" for r in result["records"])}))
            if any(r["result"] in {"fail", "unknown"} for r in result["records"]):
                return 2
        elif args.command == "cases":
            from .cases import sync_cases, update_case
            if args.action == "sync":
                if not args.input:
                    raise ValueError("cases sync requires --input")
                result = sync_cases(read_json(args.input), args.state)
            elif args.action == "update":
                if not args.id or not args.status or not args.actor:
                    raise ValueError("cases update requires --id, --status and --actor")
                result = update_case(args.state, args.id, args.status, args.actor, args.note, args.owner)
            else:
                result = read_json(args.state)
            print(json.dumps(result, ensure_ascii=False))
        else:
            value = read_json(args.input)
            if value.get("kind") != "impact_report":
                raise ValueError("Expected an impact_report")
            if args.cases:
                value["case_state"] = read_json(args.cases)
            render(value, args.output)
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as exc:
        print(f"robot-workflow: {exc}", file=sys.stderr)
        return 1
    except EOFError:
        print("Interactive input unavailable; use setup --root DIR --yes or an interactive terminal", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
