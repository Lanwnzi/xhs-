import axios from 'axios'
import type { AnalyzeRequest, APIJobResponse, JobRecord, HealthResponse } from './types'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:9001'

const http = axios.create({
  baseURL: API_BASE_URL,
  timeout: 15000,
  headers: { 'Content-Type': 'application/json' },
})

// 响应拦截：统一错误处理
http.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.code === 'ERR_NETWORK') {
      throw new Error('后端服务不可用，请确认 FastAPI 已启动')
    }
    if (error.code === 'ECONNABORTED') {
      throw new Error('请求超时，请稍后重试')
    }
    if (error.response) {
      const detail = error.response.data?.detail || error.response.statusText
      throw new Error(detail)
    }
    throw new Error('请求失败，请检查网络连接')
  }
)

export function healthCheck(): Promise<HealthResponse> {
  return http.get('/health').then((r) => r.data)
}

export function startAnalysis(payload: AnalyzeRequest): Promise<APIJobResponse> {
  return http.post('/api/xhs/analyze', payload).then((r) => r.data)
}

export function getJob(jobId: string): Promise<JobRecord> {
  return http.get(`/api/jobs/${jobId}`).then((r) => r.data)
}

export function getLatestReport(): Promise<Blob> {
  return http.get('/api/reports/latest', { responseType: 'blob' }).then((r) => r.data)
}

export function getReportUrl(jobId: string): string {
  return `${API_BASE_URL}/api/reports/${jobId}`
}

// ---- 人工审核 API ----

export interface HumanReviewStatus {
  job_id: string
  keyword: string
  status: string
  report_url: string | null
  human_review: Record<string, any>
}

export function getHumanReviewStatus(jobId: string): Promise<HumanReviewStatus> {
  return http.get(`/api/jobs/${jobId}/human-review`).then((r) => r.data)
}

export function approveHumanReview(jobId: string, reviewer: string, comments: string): Promise<any> {
  return http.post(`/api/jobs/${jobId}/human-review/approve`, { reviewer, comments }).then((r) => r.data)
}

export function rejectHumanReview(jobId: string, reviewer: string, comments: string, reasons: string[]): Promise<any> {
  return http.post(`/api/jobs/${jobId}/human-review/reject`, { reviewer, comments, reasons }).then((r) => r.data)
}

export function getQualityReview(jobId: string): Promise<any> {
  return http.get(`/api/jobs/${jobId}/quality-review`).then((r) => r.data)
}
