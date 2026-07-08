// 需求状态机的前端映射：与 services/requirement/app/state_machine.py 保持一致（共享契约，改动需同步）。
// 状态/动作定义是后端权威，前端只做展示与入口收敛；非法流转后端仍会 409 兜底。

export const STATUS_META: Record<string, { label: string, color: string }> = {
  draft: { label: '草稿', color: 'neutral' },
  pending_analysis: { label: '待分析', color: 'warning' },
  analyzed: { label: '分析完成', color: 'info' },
  in_review: { label: '评审中', color: 'secondary' },
  scheduled: { label: '已排期', color: 'info' },
  in_dev: { label: '开发中', color: 'primary' },
  in_test: { label: '测试中', color: 'warning' },
  pending_acceptance: { label: '待验收', color: 'warning' },
  released: { label: '已上线', color: 'success' },
  closed: { label: '已关闭', color: 'neutral' },
  rejected: { label: '已打回', color: 'error' },
}

export const TYPE_LABELS: Record<string, string> = {
  business: '业务需求',
  system: '系统需求',
}

export const PRIORITY_COLORS: Record<string, string> = {
  P0: 'error',
  P1: 'warning',
  P2: 'neutral',
}

export interface FlowAction {
  action: string
  label: string
  to: string
  color: string
  /** 该动作语义上应当填写意见（如打回原因）；后端不强制，前端提示 */
  wantComment?: boolean
}

// (当前状态) -> 可执行动作。analysis_done 一期为手动按钮，W5 接入分析任务后由回调触发。
export const TRANSITIONS: Record<string, FlowAction[]> = {
  draft: [{ action: 'submit', label: '提交分析', to: 'pending_analysis', color: 'primary' }],
  // 正常路径由 AI 分析任务回调驱动（RequirementAnalysis 组件）；此按钮是 AI 不可用时的人工降级（NFR-02）
  pending_analysis: [{ action: 'analysis_done', label: '手动标记分析完成（降级）', to: 'analyzed', color: 'neutral' }],
  analyzed: [
    { action: 'start_review', label: '发起评审', to: 'in_review', color: 'primary' },
    { action: 'reanalyze', label: '重新分析', to: 'pending_analysis', color: 'neutral' },
  ],
  in_review: [
    { action: 'approve', label: '评审通过', to: 'scheduled', color: 'success' },
    { action: 'reject', label: '打回', to: 'rejected', color: 'error', wantComment: true },
  ],
  rejected: [
    { action: 'resubmit', label: '重新提交', to: 'pending_analysis', color: 'primary' },
    { action: 'close', label: '关闭', to: 'closed', color: 'neutral', wantComment: true },
  ],
  scheduled: [{ action: 'start_dev', label: '开始开发', to: 'in_dev', color: 'primary' }],
  in_dev: [{ action: 'submit_test', label: '提测', to: 'in_test', color: 'primary' }],
  in_test: [
    { action: 'test_passed', label: '测试通过', to: 'pending_acceptance', color: 'success' },
    { action: 'test_failed', label: '测试不通过', to: 'in_dev', color: 'error', wantComment: true },
  ],
  pending_acceptance: [
    { action: 'accept', label: '验收通过', to: 'released', color: 'success' },
    { action: 'acceptance_failed', label: '验收不通过', to: 'in_test', color: 'error', wantComment: true },
  ],
  released: [{ action: 'close', label: '关闭', to: 'closed', color: 'neutral' }],
}

export function allowedActions(status: string): FlowAction[] {
  return TRANSITIONS[status] ?? []
}

export const ARTIFACT_LABELS: Record<string, string> = {
  analysis_report: '分析报告',
  doc: '文档',
  mr: '代码变更',
  test_result: '测试结果',
  review: '评审单',
  chat: '对话记录',
}

// 评审结论（FR-REV-02）。approved/conditional 驱动 approve 流转，rejected 驱动 reject。
export const REVIEW_CONCLUSIONS: Record<string, { label: string, color: string }> = {
  approved: { label: '通过', color: 'success' },
  conditional: { label: '有条件通过', color: 'warning' },
  rejected: { label: '打回', color: 'error' },
}

// 这些动作由评审流程（RequirementReviews 组件）驱动，不出现在通用流转按钮里。
export const REVIEW_MANAGED_ACTIONS = new Set(['start_review', 'approve', 'reject'])

// 后端存 UTC naive 时间戳，先原样展示到分钟（时区统一待后端加 tz 后处理）。
export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  return iso.replace('T', ' ').slice(0, 16)
}
