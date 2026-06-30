'use client';

import React, { useState } from 'react';
import { FaWikipediaW, FaList, FaBook } from 'react-icons/fa';
import ThemeToggle from '@/components/theme-toggle';
import GitlabProjectList from '@/components/GitlabProjectList';
import WikiDocList from '@/components/WikiDocList';

type View = 'projects' | 'wikis';

export default function Home() {
  const [view, setView] = useState<View>('projects');

  const menu: { key: View; label: string; icon: React.ReactNode }[] = [
    { key: 'projects', label: '项目列表', icon: <FaList /> },
    { key: 'wikis', label: 'Wiki文档', icon: <FaBook /> },
  ];

  return (
    <div className="h-screen flex flex-col bg-[var(--background)] text-[var(--foreground)]">
      {/* Top bar */}
      <header className="flex items-center justify-between px-6 py-3 border-b border-[var(--border-color)] bg-[var(--card-bg)] shadow-custom">
        <div className="flex items-center gap-3">
          <div className="bg-[var(--accent-primary)] p-2 rounded-lg">
            <FaWikipediaW className="text-xl text-white" />
          </div>
          <h1 className="text-lg font-bold text-[var(--accent-primary)]">DeepWiki</h1>
        </div>
        <ThemeToggle />
      </header>

      {/* Body: left menu + content */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left sidebar */}
        <aside className="w-52 shrink-0 border-r border-[var(--border-color)] bg-[var(--card-bg)] p-3 overflow-y-auto">
          <nav className="flex flex-col gap-1">
            {menu.map((m) => (
              <button
                key={m.key}
                onClick={() => setView(m.key)}
                className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors text-left ${
                  view === m.key
                    ? 'bg-[var(--accent-primary)] text-white'
                    : 'text-[var(--foreground)] hover:bg-[var(--background)]'
                }`}
              >
                <span className="text-base">{m.icon}</span>
                <span>{m.label}</span>
              </button>
            ))}
          </nav>
        </aside>

        {/* Right content */}
        <main className="flex-1 overflow-y-auto p-6">
          <h2 className="text-xl font-bold text-[var(--foreground)] mb-4">
            {view === 'projects' ? '项目列表(GitLab)' : 'Wiki 文档(已生成)'}
          </h2>
          {view === 'projects' ? (
            <GitlabProjectList />
          ) : (
            <WikiDocList className="w-full" />
          )}
        </main>
      </div>
    </div>
  );
}
