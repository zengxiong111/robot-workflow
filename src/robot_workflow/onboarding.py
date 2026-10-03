"""Guided local setup; never synchronizes the inspected repositories."""

from pathlib import Path
import shlex
import webbrowser

from .discovery import discover
from .engine import read_json, write_json, validate_config
from .monitor import watch_once


def latest_report(state_dir):
    reports = sorted(Path(state_dir).resolve().glob('report-*.html'))
    if not reports:
        raise ValueError('No report yet; run setup or watch --once first')
    return reports[-1]


def open_report(path):
    opened = webbrowser.open(Path(path).resolve().as_uri())
    if not opened:
        print(f'Open in your browser / 请用浏览器打开: {path}')
    return opened


def setup(args):
    zh = args.lang == 'zh'
    def say(en, cn):
        print(cn if zh else en)
    def ask(en, cn, default):
        if args.yes:
            return default
        answer = input(f'{cn if zh else en} [{default}]: ').strip()
        return answer or default
    root_value = args.root or ask('Directory containing Git repositories', '包含 Git 仓库的父目录', str(Path.cwd()))
    root = Path(root_value).expanduser().resolve()
    state_value = args.state_dir or ask('Workflow state directory (outside repository root)',
                                       '工作流状态目录（须位于仓库根目录之外）', str(root.parent / (root.name + '-workflow')))
    state = Path(state_value).expanduser().resolve()
    if state == root or state.is_relative_to(root):
        raise ValueError('state_dir must be outside the repository root')
    path = state / 'workflow.json'
    identity = state / 'root-identity.json'
    if identity.exists() and read_json(identity) != {'root': str(root)}:
        raise ValueError('state_dir is already bound to a different repository root')
    if path.exists():
        config = read_json(path)
        say('Reusing saved configuration; existing owners and edges are preserved.', '复用已保存配置，保留已有负责人及依赖。')
    else:
        config = discover(root, args.project)
        config['project'] = ask('Workflow name', '工作流名称', args.project)
        say(f"Found {len(config['repositories'])} repositories.", f"发现 {len(config['repositories'])} 个仓库。")
        for node in config['nodes']:
            node['owner'] = ask(f"Owner of {node['label']}", f"{node['label']} 的负责人", args.owner or 'unassigned')
        reviewed = []
        for edge in config['edges']:
            say(f"Dependency: {edge['from']} → {edge['to']}\n  {edge['reason']}",
                f"依赖：{edge['from']} → {edge['to']}\n  {edge['reason']}")
            answer = ask('Keep / remove / reverse (k/d/r)', '保留 / 删除 / 反向（k/d/r）', 'k').lower()
            while answer not in {'k', 'd', 'r'}:
                answer = ask('Enter k, d or r', '请输入 k、d 或 r', 'k').lower()
            if answer == 'd':
                continue
            if answer == 'r':
                edge['from'], edge['to'] = edge['to'], edge['from']
                edge['basis'] = 'user-reviewed: reversed ' + edge.get('basis', 'inferred reference')
            elif not args.yes:
                edge['basis'] = 'user-reviewed: accepted ' + edge.get('basis', 'inferred reference')
            reviewed.append(edge)
        config['edges'] = reviewed
        validate_config(config)
        write_json(path, config)
    from .diagnostics import inspect_workflow
    findings = inspect_workflow(config, root)
    say('Setup checks (references still require engineering review):', '配置检查（引用关系仍需工程审查）：')
    for issue in findings['issues']:
        print(f"  [{issue['severity']}] {issue['message']}\n    {issue['action']}")
    result = watch_once(config, root, state, update=False, notify=False)
    say(f"Report: {result['html']}", f"报告：{result['html']}")
    say('Observed local source only. No fetch or webhook delivery occurred.', '本轮仅观察本地源码，没有拉取提交或投递 Webhook。')
    watch_args = ['robot-workflow', 'watch', '--config', str(path), '--root', str(root), '--state-dir', str(state), '--no-update']
    say('Continue observing:', '继续观察：')
    print('  ' + shlex.join(watch_args))
    say('To enable Git updates, remove --no-update from that command.', '需要自动更新 Git 时，去掉上述命令的 --no-update。')
    if not args.no_open:
        open_report(result['html'])
    return 2 if any(i['severity'] == 'error' for i in findings['issues']) else 0
