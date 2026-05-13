<script setup lang="ts">
import type { JobRecord } from '../types'

defineProps<{
  job: JobRecord | null
  healthy: boolean
}>()

const statusLabelMap: Record<string, string> = {
  pending: '等待中',
  running: '运行中',
  completed: '已完成',
  failed: '失败',
  waiting_human_review: '等待人工审核',
  human_rejected: '人工审核未通过',
}

const statusTypeMap: Record<string, string> = {
  pending: 'info',
  running: 'warning',
  completed: 'success',
  failed: 'danger',
  waiting_human_review: 'warning',
  human_rejected: 'danger',
}
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <span>任务状态</span>
    </template>

    <div v-if="!job" style="color: #999; padding: 20px 0; text-align: center;">
      暂无任务，请提交分析
    </div>

    <template v-else>
      <div class="status-header">
        <el-tag :type="statusTypeMap[job.status] as any" size="large">
          {{ statusLabelMap[job.status] || job.status }}
        </el-tag>
        <span class="job-id">{{ job.job_id.slice(0, 20) }}...</span>
      </div>

      <el-descriptions :column="1" border size="small" style="margin-top: 16px;">
        <el-descriptions-item label="关键词">{{ job.keyword }}</el-descriptions-item>
        <el-descriptions-item label="分析模式">{{ job.analysis_mode }}</el-descriptions-item>
        <el-descriptions-item label="mock_llm">{{ job.mock_llm }}</el-descriptions-item>
        <el-descriptions-item label="data_root">{{ job.data_root }}</el-descriptions-item>
        <el-descriptions-item v-if="job.status === 'failed' && job.error" label="错误">
          <span style="color: #e74c3c;">{{ job.error }}</span>
        </el-descriptions-item>
      </el-descriptions>
    </template>
  </el-card>
</template>

<style scoped>
.status-header {
  display: flex;
  align-items: center;
  gap: 12px;
}
.job-id {
  font-family: monospace;
  font-size: 0.85em;
  color: #999;
}
</style>
