'use client';

import React, { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react';
import Link from 'next/link';

interface GitlabProject {
  pathWithNamespace: string;
  name: string;
  description?: string | null;
  defaultBranch?: string;
  starCount?: number;
  webUrl?: string;
}

interface ProcessedProject {
  owner: string;
  repo: string;
  repo_type: string;
}

function splitRepo(pathWithNamespace: string): { owner: string; repo: string } {
  const parts = pathWithNamespace.split('/');
  return { owner: parts[0] || '', repo: parts.slice(1).join('/') };
}

export default function CatalogPage() {
  const [searchInput, setSearchInput] = useState('');
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(1);

  const [projects, setProjects] = useState<GitlabProject[]>([]);
  const [nextPage, setNextPage] = useState<number | null>(null);
  const [generated, setGenerated] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load already-generated projects (gitlab) once -> set of "owner/repo".
  useEffect(() => {
    fetch('/api/wiki/projects')
      .then((r) => r.json())
      .then((data: ProcessedProject[]) => {
        if (!Array.isArray(data)) return;
        const s = new Set<string>();
        for (const p of data) {
          if ((p.repo_type || '').toLowerCase().includes('gitlab')) {
            s.add(`${p.owner}/${p.repo}`.toLowerCase());
          }
        }
        setGenerated(s);
      })
      .catch(() => { /* best-effort */ });
  }, []);

  // Load GitLab projects on query / page change.
  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      setLoading(true);
      setError(null);
      try {
        const qs = new URLSearchParams({ search: query, page: String(page) });
        const res = await fetch(`/api/gitlab/projects?${qs.toString()}`);
        const data = await res.json();
        if (cancelled) return;
        if (data.error) setError(data.error);
        setProjects(data.projects || []);
        setNextPage(data.nextPage ?? null);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : '加载失败');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    run();
    return () => { cancelled = true; };
  }, [query, page]);

  const submitSearch = useCallback((e: FormEvent) => {
    e.preventDefault();
    setPage(1);
    setQuery(searchInput.trim());
  }, [searchInput]);

  const rows = useMemo(() => projects.map((p) => {
    const { owner, repo } = splitRepo(p.pathWithNamespace);
    const isGenerated = generated.has(p.pathWithNamespace.toLowerCase());
    const repoUrl = p.webUrl || `${''}`;
    const viewHref = `/${owner}/${repo}?type=gitlab&language=zh`;
    const genParams = new URLSearchParams();
    genParams.append('type', 'gitlab');
    genParams.append('repo_url', encodeURIComponent(repoUrl));
    genParams.append('provider', 'openai');
    genParams.append('model', 'qwen-plus');
    genParams.append('language', 'zh');
    const genHref = `/${owner}/${repo}?${genParams.toString()}`;
    const nested = repo.includes('/');
    return { p, owner, repo, isGenerated, viewHref, genHref, nested };
  }), [projects, generated]);

  return (
    <div className="container mx-auto p-4">
      <header className="mb-6 flex items-center justify-between">
        <h1 className="text-3xl font-bold text-[var(--accent-primary)]">仓库目录(GitLab)</h1>
        <div className="flex items-center gap-4">
          <Link href="/wiki/projects" className="text-sm text-[var(--accent-primary)] hover:underline">已生成项目</Link>
          <Link href="/" className="text-sm text-[var(--accent-primary)] hover:underline">返回首页</Link>
        </div>
      </header>

      <form onSubmit={submitSearch} className="mb-4">
        <input
          type="text"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          placeholder="搜索仓库(名称、路径或介绍),回车搜索…"
          className="block w-full px-4 py-2.5 border border-[var(--border-color)] rounded-lg bg-[var(--background)] text-[var(--foreground)] placeholder:text-[var(--muted)] focus:outline-none focus:border-[var(--accent-primary)]"
        />
      </form>

      {error && <p className="mb-4 text-sm text-[var(--highlight)]">加载出错:{error}</p>}

      <div className="overflow-x-auto border border-[var(--border-color)] rounded-lg">
        <table className="min-w-full text-sm">
          <thead className="bg-[var(--background)] text-left text-[var(--muted)]">
            <tr>
              <th className="px-4 py-3 font-medium">仓库路径</th>
              <th className="px-4 py-3 font-medium">仓库介绍</th>
              <th className="px-4 py-3 font-medium">默认分支</th>
              <th className="px-4 py-3 font-medium">状态</th>
              <th className="px-4 py-3 font-medium text-right">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--border-color)]">
            {loading && (
              <tr><td colSpan={5} className="px-4 py-8 text-center text-[var(--muted)]">加载中…</td></tr>
            )}
            {!loading && rows.length === 0 && (
              <tr><td colSpan={5} className="px-4 py-8 text-center text-[var(--muted)]">没有仓库</td></tr>
            )}
            {!loading && rows.map(({ p, isGenerated, viewHref, genHref, nested }) => (
              <tr key={p.pathWithNamespace} className="hover:bg-[var(--card-bg)] align-top">
                <td className="px-4 py-3 font-mono text-[var(--foreground)]">{p.pathWithNamespace}</td>
                <td className="px-4 py-3 text-[var(--muted)] max-w-xs truncate" title={p.description || ''}>
                  {p.description || '—'}
                </td>
                <td className="px-4 py-3 text-[var(--muted)]">{p.defaultBranch || '—'}</td>
                <td className="px-4 py-3">
                  {isGenerated
                    ? <span className="px-2 py-0.5 text-xs rounded-full bg-green-500/10 text-green-600 border border-green-500/20">已生成</span>
                    : <span className="px-2 py-0.5 text-xs rounded-full bg-[var(--background)] text-[var(--muted)] border border-[var(--border-color)]">未生成</span>}
                </td>
                <td className="px-4 py-3 text-right whitespace-nowrap">
                  {nested ? (
                    <span className="text-xs text-[var(--muted)]" title="deepwiki 路由暂不支持多层嵌套组">嵌套组暂不支持</span>
                  ) : isGenerated ? (
                    <Link href={viewHref} className="px-4 py-1.5 text-xs rounded-full bg-[var(--accent-primary)] text-white hover:opacity-90">查看</Link>
                  ) : (
                    <Link href={genHref} className="px-4 py-1.5 text-xs rounded-full border border-[var(--accent-primary)] text-[var(--accent-primary)] hover:bg-[var(--accent-primary)]/10">生成</Link>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {!query && (
        <div className="flex items-center justify-end gap-4 mt-4 text-sm text-[var(--muted)]">
          <button onClick={() => setPage((x) => Math.max(1, x - 1))} disabled={page <= 1 || loading} className="disabled:opacity-40 hover:text-[var(--foreground)]">← 上一页</button>
          <span>第 {page} 页</span>
          <button onClick={() => setPage((x) => x + 1)} disabled={!nextPage || loading} className="disabled:opacity-40 hover:text-[var(--foreground)]">下一页 →</button>
        </div>
      )}
    </div>
  );
}
