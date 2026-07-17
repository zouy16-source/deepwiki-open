#!/usr/bin/env python3
"""从 wiki 缓存回填 identity 项目的 repo_meta(git_url + default_branch)。

背景:生成 wiki 时 api 服务必须 clone 仓库,已把真实 `repo_url` / `default_branch` 写进
      ~/.adalflow/wikicache/deepwiki_cache_<type>_<owner>_<repo>_<lang>.json。
      故仓库地址/分支是"系统已有数据",不该让人再手填。

本脚本:扫 wiki 缓存 → 按 clone 目录名(<owner>_<repo>,即 identity 项目 repos 里的名字)
        匹配 → 自动 PATCH 各项目的 repo_meta。幂等;--dry-run 只打印不写。纯 stdlib。

用法:
    python scripts/backfill_repo_meta.py --dry-run          # 先看会写什么
    python scripts/backfill_repo_meta.py                    # 实际回填
env:  IDENTITY_BASE_URL(默认 http://localhost:8003)、INTERNAL_JWT(identity 开鉴权时才需要)
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import urllib.error
import urllib.request

DEFAULT_CACHE = os.path.expanduser("~/.adalflow/wikicache")


def load_from_cache(cache_dir: str) -> dict[str, dict]:
    """{ "<owner>_<repo>": {"git_url":..., "default_branch":...} } —— 同名多语言缓存取其一。"""
    out: dict[str, dict] = {}
    for path in sorted(glob.glob(os.path.join(cache_dir, "deepwiki_cache_*.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        repo = d.get("repo") or {}
        owner, name = repo.get("owner"), repo.get("repo")
        url = d.get("repo_url") or repo.get("repoUrl") or repo.get("repo_url")
        branch = d.get("default_branch") or repo.get("default_branch") or "main"
        if owner and name and url:
            out.setdefault(f"{owner}_{name}", {"git_url": url, "default_branch": branch})
    return out


def _http(method: str, url: str, token: str | None = None, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--identity", default=os.environ.get("IDENTITY_BASE_URL", "http://localhost:8003"))
    ap.add_argument("--cache-dir", default=DEFAULT_CACHE)
    ap.add_argument("--token", default=os.environ.get("INTERNAL_JWT", ""))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    token = args.token or None

    meta = load_from_cache(args.cache_dir)
    print(f"从 wiki 缓存({args.cache_dir})解析出 {len(meta)} 个仓库地址:")
    for k, v in meta.items():
        print(f"  {k:32s} -> {v['git_url']}  @ {v['default_branch']}")
    if not meta:
        print("(未从缓存解析到任何仓库地址,退出)")
        return 1

    try:
        projects = _http("GET", f"{args.identity.rstrip('/')}/api/projects", token=token)
    except urllib.error.URLError as e:
        print(f"连不上 identity({args.identity}):{e}")
        return 2

    total_changed = 0
    for p in projects:
        bound = p.get("repos") or []
        existing = p.get("repo_meta") or {}
        new_meta = dict(existing)
        hits = []
        for name in bound:
            if name in meta and existing.get(name, {}).get("git_url") != meta[name]["git_url"]:
                new_meta[name] = meta[name]
                hits.append(name)
        misses = [n for n in bound if n not in meta]
        if hits:
            total_changed += 1
            print(f"\n项目 #{p['id']} {p.get('code')}: 回填 {hits}")
            for n in hits:
                print(f"    {n} -> {new_meta[n]['git_url']} @ {new_meta[n]['default_branch']}")
            if not args.dry_run:
                _http("PATCH", f"{args.identity.rstrip('/')}/api/projects/{p['id']}",
                      token=token, body={"repo_meta": new_meta})
        if misses:
            print(f"  项目 #{p['id']} {p.get('code')}: 这些绑定仓库在 wiki 缓存里没找到地址(未生成过 wiki?):{misses}")

    print(f"\n完成:{total_changed} 个项目有更新" + ("(dry-run,未写入)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
