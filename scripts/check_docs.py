"""Check paired Markdown structure, command parity and local links."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def body(text):
    return re.sub(r'```[^\n]*\n.*?```', '', text, flags=re.S)


def headings(text):
    return [(len(m[1]), m[2]) for m in re.finditer(r'^(#{1,6}) (.+)$', body(text), re.M)]


def slug(text):
    return re.sub(r'[^\w\- ]', '', text.lower()).replace(' ', '-')


def main():
    failures = []
    files = sorted(p for p in ROOT.rglob('*.md') if not any(
        part in {'.venv', 'build', 'dist', '.git', 'runs', 'repos'} or part.endswith('.egg-info')
        for part in p.relative_to(ROOT).parts))
    for path in files:
        text = path.read_text()
        hs = headings(text)
        if sum(level == 1 for level, _ in hs) != 1:
            failures.append(f'{path}: expected one document title')
        for previous, current in zip(hs, hs[1:]):
            if current[0] > previous[0] + 1:
                failures.append(f'{path}: heading level skipped')
        anchors = {slug(title) for _, title in hs}
        for target in re.findall(r'\[[^\]]+\]\(([^)]+)\)', body(text)):
            if target.startswith(('https://', 'http://', 'mailto:')):
                continue
            if target.startswith('#'):
                if target[1:] not in anchors:
                    failures.append(f'{path}: missing anchor {target}')
            elif not (path.parent / target.split('#')[0]).exists():
                failures.append(f'{path}: missing link {target}')
        if sum(level == 2 for level, _ in hs) >= 3 and not re.search(r'\]\(#[^)]+\)', text):
            failures.append(f'{path}: missing clickable contents')
        if '.zh-CN.' in path.name:
            continue
        counterpart = path.with_name(path.stem + '.zh-CN.md')
        if not counterpart.exists():
            failures.append(f'{path}: missing Chinese counterpart')
            continue
        other = counterpart.read_text()
        if [level for level, _ in hs] != [level for level, _ in headings(other)]:
            failures.append(f'{path}: bilingual heading structures differ')
        if re.findall(r'```[^\n]*\n(.*?)```', text, re.S) != re.findall(r'```[^\n]*\n(.*?)```', other, re.S):
            failures.append(f'{path}: bilingual code/command blocks differ')
    if failures:
        raise SystemExit('\n'.join(failures))
    print(f'Checked {len(files)} Markdown files: pairs, heading structure, command parity and local links')


if __name__ == '__main__':
    main()
