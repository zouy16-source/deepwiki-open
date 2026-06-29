import { NextRequest, NextResponse } from 'next/server';

// Proxy to the Python backend's GitLab file-tree endpoint (server-side fetch).
const PYTHON_BACKEND_URL = process.env.PYTHON_BACKEND_HOST || 'http://localhost:8001';

export async function GET(request: NextRequest) {
  const sp = request.nextUrl.searchParams;
  const qs = new URLSearchParams();
  qs.set('repo_url', sp.get('repo_url') || '');
  const token = sp.get('token');
  if (token) qs.set('token', token);

  try {
    const response = await fetch(`${PYTHON_BACKEND_URL}/api/gitlab/file_tree?${qs.toString()}`, {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' },
      cache: 'no-store',
    });
    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : 'An unknown error occurred';
    return NextResponse.json(
      { error: `Failed to connect to backend. ${message}`, file_tree: '', default_branch: 'main', readme: '' },
      { status: 503 },
    );
  }
}
