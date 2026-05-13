<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import type { AnalyzeRequest, JobRecord } from './types'
import { healthCheck, startAnalysis, getJob } from './api'
import AnalyzeForm from './components/AnalyzeForm.vue'
import JobStatusCard from './components/JobStatusCard.vue'
import ReportViewer from './components/ReportViewer.vue'

const healthy = ref(false)
const currentJob = ref<JobRecord | null>(null)

// 拆分状态：submitting 仅在 POST 期间为 true，running 在任务执行中为 true
const submitting = ref(false)
const running = ref(false)
const firstHumanReviewNotified = ref(false)

const pollFailures = ref(0)
const MAX_POLL_FAILURES = 5
let pollTimer: ReturnType<typeof setInterval> | null = null

// 健康检查
onMounted(async () => {
  try {
    await healthCheck()
    healthy.value = true
  } catch {
    healthy.value = false
  }
})

// 提交分析
async function handleSubmit(payload: AnalyzeRequest) {
  // 清理旧轮询
  stopPolling()
  currentJob.value = null
  firstHumanReviewNotified.value = false

  submitting.value = true
  running.value = false

  try {
    const resp = await startAnalysis(payload)
    ElMessage.success(`任务已提交: ${resp.job_id}`)
    submitting.value = false
    running.value = true

    // 创建临时记录
    currentJob.value = {
      job_id: resp.job_id,
      keyword: payload.keyword,
      status: resp.status,
      analysis_mode: payload.analysis_mode,
      mock_llm: payload.mock_llm,
      max_posts: payload.max_posts,
      max_comments: payload.max_comments,
      headless: payload.headless,
      data_root: resp.data_root || '',
      report_path: null,
      keyword_slug: '',
      run_id: '',
      created_at: '',
      updated_at: '',
      error: null,
    } as JobRecord

    // 开始轮询
    pollJob(resp.job_id)
  } catch (e: any) {
    submitting.value = false
    running.value = false

    // 处理 409 — 后端已有任务运行中
    const msg = e.message || ''
    if (msg.includes('已有任务运行')) {
      ElMessage.warning('当前已有任务运行中，请等待完成后再提交')
    } else {
      ElMessage.error(msg || '提交失败')
    }
  }
}

// 轮询
function pollJob(jobId: string) {
  pollTimer = setInterval(async () => {
    try {
      const job = await getJob(jobId)
      currentJob.value = job

      if (job.status === 'completed') {
        stopPolling()
        running.value = false
        ElMessage.success('分析完成！')
      } else if (job.status === 'failed') {
        stopPolling()
        running.value = false
        ElMessage.error('分析失败')
      } else if (job.status === 'waiting_human_review') {
        // 不停止轮询 — 后续 resume 会改变状态
        // 不重置 running — 任务仍在进行中
        if (!firstHumanReviewNotified.value) {
          ElMessage.info('报告已生成，等待人工审核')
          firstHumanReviewNotified.value = true
        }
      } else if (job.status === 'running_from_review') {
        ElMessage.info('审核结果已提交，正在继续处理...')
      } else if (job.status === 'human_rejected') {
        // P5.0: 新版流程中 resume 后始终标记 completed，此状态极少出现
        stopPolling()
        running.value = false
        ElMessage.warning('报告未通过人工审核')
      }
    } catch (e: any) {
      pollFailures.value++
      if (pollFailures.value >= MAX_POLL_FAILURES) {
        stopPolling()
        running.value = false
        ElMessage.error('轮询失败次数过多，请刷新页面重试')
      }
    }
  }, 3000)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function handleRetry() {
  stopPolling()
  submitting.value = false
  running.value = false
  currentJob.value = null
  ElMessage.info('请重新提交任务')
}

onUnmounted(() => {
  stopPolling()
})
</script>

<template>
  <div class="app-container">
    <header class="app-header">
      <h1>小红书评论洞察与文案选题助手</h1>
      <el-tag :type="healthy ? 'success' : 'danger'" size="small">
        后端 {{ healthy ? '已连接' : '未连接' }}
      </el-tag>
    </header>

    <div class="main-content">
      <div class="left-panel">
        <AnalyzeForm :submitting="submitting" :running="running" @submit="handleSubmit" />
        <div style="margin-top: 16px;">
          <JobStatusCard :job="currentJob" :healthy="healthy" />
        </div>
      </div>
      <div class="right-panel">
        <ReportViewer :job="currentJob" @retry="handleRetry" />
      </div>
    </div>
  </div>
</template>
