'use client';

import Link from 'next/link';
import GitlabProjectList from '@/components/GitlabProjectList';

export default function CatalogPage() {
  return (
    <div className="container mx-auto p-4">
      <header className="mb-6 flex items-center justify-between">
        <h1 className="text-3xl font-bold text-[var(--accent-primary)]">仓库目录(GitLab)</h1>
        <div className="flex items-center gap-4">
          <Link href="/wiki/projects" className="text-sm text-[var(--accent-primary)] hover:underline">已生成项目</Link>
          <Link href="/" className="text-sm text-[var(--accent-primary)] hover:underline">返回首页</Link>
        </div>
      </header>

      <GitlabProjectList />
    </div>
  );
}
