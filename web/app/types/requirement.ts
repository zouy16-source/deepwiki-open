// requirement 服务（services/requirement）的 API 数据结构，经 BFF /api/requirements 代理。
export interface Requirement {
  id: number
  project_id: number
  parent_id: number | null
  req_type: 'business' | 'system'
  title: string
  description: string
  status: string
  priority: 'P0' | 'P1' | 'P2'
  complexity: string | null
  expected_online_date: string | null
  creator: string
  // 外部来源（TAPD 镜像，单向只读）；source='native' 时以下为空
  source: 'native' | 'tapd'
  external_id: string | null
  external_url: string
  external_status: string
  assignee: string
  synced_at: string | null
  created_at: string
  updated_at: string
}

export interface FlowEvent {
  id: number
  requirement_id: number
  from_status: string | null
  to_status: string
  action: string
  operator: string
  comment: string
  artifact_type: string | null
  artifact_ref: string | null
  created_at: string
}

// 可行性分析执行记录（FR-ANA，requirement 服务；任务在 api 服务执行后回调）。
export interface AnalysisRun {
  id: number
  requirement_id: number
  task_id: string | null
  status: 'queued' | 'running' | 'succeeded' | 'failed'
  summary: string
  complexity: string | null
  report_md: string
  error: string
  created_by: string
  created_at: string
  finished_at: string | null
}

// 评审单（FR-REV-01/02，requirement 服务）。conclusion 为空 = 评审中。
export interface Review {
  id: number
  requirement_id: number
  initiator: string
  agenda: string
  participants: string[]
  scheduled_at: string | null
  conclusion: 'approved' | 'conditional' | 'rejected' | null
  conclusion_comment: string
  concluded_by: string | null
  concluded_at: string | null
  created_at: string
}

// identity 服务的用户（经 BFF /api/users 代理），评审圈人用。
export interface PlatformUser {
  id: number
  username: string
  display_name: string
  email: string
  tapd_nick: string
  is_active: boolean
}

// identity 服务的项目空间（经 BFF /api/projects 代理）。
export interface Project {
  id: number
  code: string
  name: string
  description: string
  repos: string[]
  tapd_workspace_id: string
  created_at: string
}
