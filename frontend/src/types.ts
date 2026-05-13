export interface AnalyzeRequest {
  keyword: string
  max_posts: number
  max_comments: number
  analysis_mode: 'rule' | 'llm_annotation'
  mock_llm: boolean
  headless: boolean
  human_review_required: boolean
}

export type JobStatus = 'pending' | 'running' | 'completed' | 'failed' | 'waiting_human_review' | 'human_rejected' | 'running_from_review'

export interface APIJobResponse {
  job_id: string
  status: JobStatus
  message: string
  report_url: string | null
  data_root: string | null
}

export interface JobRecord {
  job_id: string
  keyword: string
  keyword_slug: string
  run_id: string
  status: JobStatus
  analysis_mode: 'rule' | 'llm_annotation'
  mock_llm: boolean
  max_posts: number
  max_comments: number
  headless: boolean
  data_root: string
  report_path: string | null
  created_at: string
  updated_at: string
  error: string | null
}

export interface HealthResponse {
  status: string
}
