#!/usr/bin/env python3
"""위키 번들을 GitHub Pages용 정적 사이트로 변환한다.

- 모든 .md 파일 → 같은 경로의 .html (frontmatter는 상단 메타 표로 표시)
- 그 외 파일(html, png 등) → 그대로 복사
- 번들 내부 링크 규약(루트 절대 경로 `/wiki/...md`)을 Pages 경로(base 접두 + .html)로 재작성

사용: python build_site.py --base /interview-wiki --out _site
"""
import argparse
import re
import shutil
from pathlib import Path

import markdown
import yaml

SKIP_DIRS = {".git", ".github", ".context", ".playwright-mcp", "_site", "node_modules", "raw"}
FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.S)
MD_EXTENSIONS = ["extra", "toc", "sane_lists"]

TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} · Interview Wiki</title>
<style>
  :root {{ --ink:#202631; --paper:#f8f6ef; --card:#fff; --muted:#70788a; --blue:#4a78e8; --line:#dfe3ea; --soft:#f2f4f8; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font-family:"Pretendard","Apple SD Gothic Neo","Noto Sans KR",sans-serif; background:var(--paper); color:var(--ink); line-height:1.7; }}
  .wrap {{ max-width:920px; margin:0 auto; padding:32px 20px 80px; }}
  nav {{ display:flex; gap:14px; font-size:14px; color:var(--muted); margin-bottom:18px; }}
  nav a {{ color:var(--blue); text-decoration:none; font-weight:700; }}
  article {{ background:var(--card); border-radius:20px; padding:36px 40px; box-shadow:0 4px 24px rgba(32,38,49,.07); }}
  h1 {{ font-size:32px; line-height:1.3; margin:0 0 14px; }}
  h2 {{ font-size:24px; margin:40px 0 12px; padding-bottom:6px; border-bottom:2px solid var(--line); }}
  h3 {{ font-size:19px; margin:28px 0 8px; }}
  h4 {{ font-size:16px; margin:20px 0 6px; }}
  a {{ color:var(--blue); }}
  table {{ border-collapse:collapse; width:100%; margin:14px 0; font-size:14.5px; display:block; overflow-x:auto; }}
  th, td {{ border:1px solid var(--line); padding:8px 10px; text-align:left; vertical-align:top; }}
  th {{ background:var(--soft); }}
  code {{ padding:1px 5px; border-radius:5px; background:#e9edf5; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:.9em; }}
  pre {{ background:var(--ink); color:#f5f7fb; padding:16px 18px; border-radius:12px; overflow-x:auto; font-size:13.5px; line-height:1.55; }}
  pre code {{ background:none; color:inherit; padding:0; font-size:inherit; }}
  blockquote {{ margin:16px 0; padding:12px 18px; border-left:4px solid var(--blue); background:var(--soft); border-radius:8px; color:#3d4555; }}
  img {{ max-width:100%; height:auto; border-radius:12px; border:1px solid var(--line); }}
  .meta {{ font-size:13px; color:var(--muted); margin:0 0 26px; }}
  .meta table {{ width:auto; display:table; font-size:13px; }}
  .meta td:first-child {{ color:var(--muted); font-weight:700; white-space:nowrap; }}
  details summary {{ cursor:pointer; font-weight:700; color:var(--blue); }}
  footer {{ margin-top:30px; text-align:center; color:var(--muted); font-size:13px; }}
  @media (max-width:640px) {{ article {{ padding:22px 18px; border-radius:14px; }} h1 {{ font-size:26px; }} }}
</style>
</head>
<body>
<div class="wrap">
<nav><a href="{base}/index.html">카탈로그</a><a href="{base}/log.html">연대기</a><a href="{repo_url}">GitHub</a></nav>
<article>
{meta}
{body}
</article>
<footer>Interview LLM Wiki · 정적 빌드</footer>
</div>
</body>
</html>
"""


def split_frontmatter(text: str):
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return {}, text
    return (meta if isinstance(meta, dict) else {}), m.group(2)


def render_meta(meta: dict) -> str:
    if not meta:
        return ""
    rows = []
    for key, value in meta.items():
        if key == "title":
            continue
        if isinstance(value, list):
            shown = "<br>".join(str(v) for v in value)
        else:
            shown = str(value)
        rows.append(f"<tr><td>{key}</td><td>{shown}</td></tr>")
    return f'<div class="meta"><table>{"".join(rows)}</table></div>'


def rewrite_links(html: str, base: str) -> str:
    # 루트 절대 경로(/wiki/...)에 Pages base 접두를 붙인다. 프로토콜 상대(//)는 제외.
    html = re.sub(r'(href|src)="/(?!/)', lambda m: f'{m.group(1)}="{base}/', html)
    # 번들 내부 .md 링크는 변환된 .html로 향하게 한다.
    pattern = re.compile(r'href="(' + re.escape(base) + r'/[^"#]+)\.md(#[^"]*)?"')
    html = pattern.sub(lambda m: f'href="{m.group(1)}.html{m.group(2) or ""}"', html)
    return html


def convert_markdown(src: Path, dst: Path, base: str, repo_url: str) -> None:
    meta, body_md = split_frontmatter(src.read_text(encoding="utf-8"))
    md = markdown.Markdown(extensions=MD_EXTENSIONS)
    # 링크 재작성은 본문에만 적용한다. 템플릿의 내비게이션은 이미 base를 포함한다.
    body_html = rewrite_links(md.convert(body_md), base)
    title = meta.get("title") or _first_heading(body_md) or src.stem
    page = TEMPLATE.format(title=title, base=base, repo_url=repo_url, meta=render_meta(meta), body=body_html)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(page, encoding="utf-8")


def _first_heading(body_md: str):
    for line in body_md.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return None


def build(root: Path, out: Path, base: str, repo_url: str) -> int:
    if out.exists():
        shutil.rmtree(out)
    count = 0
    for src in sorted(root.rglob("*")):
        rel = src.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts) or rel.name.startswith("."):
            continue
        if src.is_dir():
            continue
        if len(rel.parts) == 1 and src.suffix == ".png":
            continue  # 루트의 임시 스크린샷은 사이트에 넣지 않는다
        if src.suffix == ".md":
            convert_markdown(src, out / rel.with_suffix(".html"), base, repo_url)
        else:
            (out / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, out / rel)
        count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="위키 루트 (기본: 현재 디렉토리)")
    parser.add_argument("--out", default="_site", help="출력 디렉토리")
    parser.add_argument("--base", default="", help="Pages base 경로. 프로젝트 사이트면 /<repo>")
    parser.add_argument("--repo-url", default="https://github.com/yongjin5184/interview-wiki")
    args = parser.parse_args()
    base = args.base.rstrip("/")
    n = build(Path(args.root).resolve(), Path(args.out).resolve(), base, args.repo_url)
    print(f"built {n} files into {args.out} (base='{base}')")


if __name__ == "__main__":
    main()
