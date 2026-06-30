'use client';

import React, { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react';
import Link from 'next/link';

interface WikiDoc {
  id: string;
  owner: string;
  repo: string;
  name: string;
  repo_type: string;
  submittedAt: number;
  language: string;
}

// 自建 GitLab 基址(可用 NEXT_PUBLIC_GITLAB_URL 覆盖)。
const GITLAB_BASE = process.env.NEXT_PUBLIC_GITLAB_URL || 'https://git.ymdd.tech';

// 由文档类型 + owner/repo 推出源仓库地址。
function sourceUrl(d: WikiDoc): string {
  const t = (d.repo_type || '').toLowerCase();
  if (t.includes('github')) return `https://github.com/${d.owner}/${d.repo}`;
  if (t.includes('bitbucket')) return `https://bitbucket.org/${d.owner}/${d.repo}`;
  return `${GITLAB_BASE}/${d.owner}/${d.repo}`;
}

/**
 * 已生成 Wiki 文档列表(表格:仓库路径/类型/语言/生成时间/操作)。
 * 数据来自 /api/wiki/projects,样式与 GitlabProjectList 一致。
 */
export default function WikiDocList({ className = '' }: { className?: string }) {
  const [docs, setDocs] = useState<WikiDoc[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchInput, setSearchInput] = useState('');
  const [query, setQuery] = useState('');

  const fetchDocs = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch('/api/wiki/projects');
      if (!res.ok) throw new Error(`加载失败:${res.statusText}`);
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      setDocs(Array.isArray(data) ? data : []);
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载失败');
      setDocs([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchDocs(); }, [fetchDocs]);

  const submitSearch = useCallback((e: FormEvent) => {
    e.preventDefault();
    setQuery(searchInput.trim().toLowerCase());
  }, [searchInput]);

  const rows = useMemo(() => {
    const q = query;
    if (!q) return docs;
    return docs.filter((d) =>
      d.name.toLowerCase().includes(q) ||
      d.owner.toLowerCase().includes(q) ||
      d.repo.toLowerCase().includes(q) ||
      d.repo_type.toLowerCase().includes(q)
    );
  }, [docs, query]);

  const handleDelete = async (d: WikiDoc) => {
    if (!confirm(`确定删除「${d.name}」的 wiki 吗?`)) return;
    try {
      const res = await fetch('/api/wiki/projects', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ owner: d.owner, repo: d.repo, repo_type: d.repo_type, language: d.language }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ error: res.statusText }));
        throw new Error(body.error || res.statusText);
      }
      setDocs((prev) => prev.filter((x) => x.id !== d.id));
    } catch (e) {
      alert(`删除失败:${e instanceof Error ? e.message : '未知错误'}`);
    }
  };

  return (
    <div className={className}>
      <form onSubmit={submitSearch} className="mb-4">
        <input
          type="text"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          placeholder="搜索已生成文档(名称、路径或类型),回车搜索…"
          className="block w-full px-4 py-2.5 border border-[var(--border-color)] rounded-lg bg-[var(--background)] text-[var(--foreground)] placeholder:text-[var(--muted)] focus:outline-none focus:border-[var(--accent-primary)]"
        />
      </form>

      {error && <p className="mb-4 text-sm text-[var(--highlight)]">加载出错:{error}</p>}

      <div className="overflow-x-auto border border-[var(--border-color)] rounded-lg">
        <table className="min-w-full text-sm">
          <thead className="bg-[var(--background)] text-left text-[var(--muted)]">
            <tr>
              <th className="px-4 py-3 font-medium">仓库路径</th>
              <th className="px-4 py-3 font-medium">类型</th>
              <th className="px-4 py-3 font-medium">语言</th>
              <th className="px-4 py-3 font-medium">生成时间</th>
              <th className="px-4 py-3 font-medium text-right">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--border-color)]">
            {loading && (
              <tr><td colSpan={5} className="px-4 py-8 text-center text-[var(--muted)]">加载中…</td></tr>
            )}
            {!loading && rows.length === 0 && (
              <tr><td colSpan={5} className="px-4 py-8 text-center text-[var(--muted)]">暂无已生成的 wiki 文档</td></tr>
            )}
            {!loading && rows.map((d) => {
              const viewHref = `/${d.owner}/${d.repo}?type=${d.repo_type}&language=${d.language}`;
              return (
                <tr key={d.id} className="hover:bg-[var(--card-bg)] align-top">
                  <td className="px-4 py-3 font-mono">
                    <a href={sourceUrl(d)} target="_blank" rel="noopener noreferrer" className="text-[var(--link-color)] hover:underline">{d.owner}/{d.repo}</a>
                  </td>
                  <td className="px-4 py-3">
                    <span className="px-2 py-0.5 text-xs rounded-full bg-[var(--accent-primary)]/10 text-[var(--accent-primary)] border border-[var(--accent-primary)]/20">{d.repo_type}</span>
                  </td>
                  <td className="px-4 py-3 text-[var(--muted)]">{d.language}</td>
                  <td className="px-4 py-3 text-[var(--muted)] whitespace-nowrap">{new Date(d.submittedAt).toLocaleString()}</td>
                  <td className="px-4 py-3 text-right whitespace-nowrap">
                    <Link href={viewHref} className="px-4 py-1.5 text-xs rounded-full bg-[var(--accent-primary)] text-white hover:opacity-90">查看</Link>
                    <button
                      type="button"
                      onClick={() => handleDelete(d)}
                      className="ml-2 px-4 py-1.5 text-xs rounded-full border border-[var(--highlight)] text-[var(--highlight)] hover:bg-[var(--highlight)]/10"
                    >删除</button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
