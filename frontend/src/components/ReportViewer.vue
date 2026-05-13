<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { JobRecord } from '../types'
import { getReportUrl, approveHumanReview, rejectHumanReview, getQualityReview } from '../api'

const props = defineProps<{
  job: JobRecord | null
}>()

// 人工审核状态
const reviewer = ref('')
const reviewPending = ref(false)
const qualityReviewData = ref<any>(null)

// 报告 URL — 只要报告可能存在就允许加载
const src = computed(() => {
  if (!props.job) return ''
  const viewable = ['completed', 'waiting_human_review', 'human_rejected', 'running_from_review']
  if (viewable.includes(props.job.status) && props.job.report_path) {
    return getReportUrl(props.job.job_id)
  }
  if (props.job.status === 'waiting_human_review' && props.job.data_root) {
    // 即使 report_path 为空也尝试加载（后端会自动查找 data_root/outputs/report.html）
    return getReportUrl(props.job.job_id)
  }
  return ''
})

// 监听 job 变化，completed 时加载质量评审数据
watch(() => props.job?.status, async (status) => {
  if (status === 'completed' && props.job) {
    reviewPending.value = false
    try {
      qualityReviewData.value = await getQualityReview(props.job.job_id)
    } catch {
      qualityReviewData.value = null
    }
  } else if (status === 'running_from_review') {
    reviewPending.value = true
  } else if (status === 'waiting_human_review') {
    reviewPending.value = false
  }
}, { immediate: true })

async function handleApprove() {
  if (!props.job) return
  try {
    await ElMessageBox.confirm('确认通过此报告？', '人工审核', {
      confirmButtonText: '通过',
      cancelButtonText: '取消',
      type: 'success',
    })
    reviewPending.value = true
    await approveHumanReview(props.job.job_id, reviewer.value || '前端用户', '')
    ElMessage.success('审核通过，任务将继续处理')
  } catch (e: any) {
    if (e !== 'cancel') {
      ElMessage.error(e.message || '操作失败')
    }
    reviewPending.value = false
  }
}

async function handleReject() {
  if (!props.job) return
  try {
    const { value } = await ElMessageBox.prompt(
      '请说明拒绝原因（至少一条，用逗号分隔）',
      '人工审核',
      {
        confirmButtonText: '拒绝',
        cancelButtonText: '取消',
        inputPlaceholder: '如：选题建议太模板化，缺少真实评论引用',
        inputValidator: (val: string) => !!val.trim() || '必须填写拒绝原因',
      }
    )
    const reasons = value.split(',').map((s: string) => s.trim()).filter(Boolean)
    reviewPending.value = true
    await rejectHumanReview(props.job.job_id, reviewer.value || '前端用户', '', reasons)
    ElMessage.warning('已提交拒绝，正在重新生成报告')
  } catch (e: any) {
    if (e !== 'cancel') {
      ElMessage.error(e.message || '操作失败')
    }
    reviewPending.value = false
  }
}

defineEmits<{
  retry: []
  reviewDone: []
}>()
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <span>评论洞察报告预览</span>
    </template>

    <div v-if="!job" class="placeholder">
      <el-empty description="等待提交任务" />
    </div>

    <div v-else-if="job.status === 'pending' || job.status === 'running'" class="placeholder">
      <el-empty description="分析进行中，请稍候..." />
    </div>

    <div v-else-if="job.status === 'failed'" class="placeholder">
      <el-result status="error" title="分析失败" :sub-title="job.error || '未知错误'">
        <template #extra>
          <el-button type="primary" @click="$emit('retry')">重新提交</el-button>
        </template>
      </el-result>
    </div>

    <div v-else-if="job.status === 'human_rejected'" class="placeholder">
      <el-result status="warning" title="报告未通过人工审核" :sub-title="job.error || ''">
        <template #extra>
          <el-button type="primary" @click="$emit('retry')">重新提交</el-button>
        </template>
      </el-result>
    </div>

    <!-- running_from_review：审核结果提交后正在处理 -->
    <div v-else-if="job.status === 'running_from_review'" class="placeholder">
      <el-empty description="正在处理审核结果，请稍候..." />
    </div>

    <!-- 已完成或等待审核：显示报告预览 -->
    <template v-else-if="job.status === 'completed' || job.status === 'waiting_human_review'">
      <div class="report-wrapper">
      <div class="iframe-container">
        <iframe
          :src="src"
          width="100%"
          style="border: none; border-radius: 8px;"
          title="分析报告"
        />
      </div>

      <!-- 人工审核区域（waiting_human_review 时显示） -->
      <div v-if="job.status === 'waiting_human_review' && !reviewPending" class="review-area">
        <el-divider />
        <h3 style="margin: 0 0 8px; font-size: 15px;">📋 人工审核</h3>
        <p style="color: #999; font-size: 13px; margin: 0 0 12px;">
          报告已生成，请审核后决定是否通过。
        </p>
        <el-input
          v-model="reviewer"
          placeholder="审核人（选填）"
          size="small"
          style="max-width: 240px; margin-bottom: 12px;"
        />
        <div class="review-actions">
          <el-button type="success" @click="handleApprove" :disabled="reviewPending">✅ 通过</el-button>
          <el-button type="danger" @click="handleReject" :disabled="reviewPending">❌ 拒绝</el-button>
        </div>
      </div>

      <!-- 审核结果处理中 -->
      <div v-if="reviewPending" class="review-area">
        <el-divider />
        <el-alert type="info" :closable="false" show-icon>
          <template #title>正在处理审核结果，请稍候...</template>
        </el-alert>
      </div>

      <!-- Agent 质量评审结果（completed 后显示） -->
      <div v-if="job.status === 'completed' && qualityReviewData" class="review-area">
        <el-divider />
        <h3 style="margin: 0 0 8px; font-size: 15px;">📊 报告质量评审</h3>
        <el-alert
          :type="qualityReviewData.passed ? 'success' : 'warning'"
          :closable="false"
          show-icon
        >
          <template #title>
            {{ qualityReviewData.passed ? '质量评审通过' : '质量评审未通过' }}
          </template>
        </el-alert>
        <div v-if="qualityReviewData.hard_fail_reasons?.length" style="margin-top: 8px;">
          <p style="font-weight: 600; margin: 8px 0 4px;">主要原因：</p>
          <ul style="margin: 0; padding-left: 20px;">
            <li v-for="(r, i) in qualityReviewData.hard_fail_reasons.slice(0, 5)" :key="i">
              {{ r }}
            </li>
          </ul>
        </div>
        <div v-if="qualityReviewData.reasons?.length" style="margin-top: 8px;">
          <p style="font-weight: 600; margin: 8px 0 4px;">评审意见：</p>
          <ul style="margin: 0; padding-left: 20px;">
            <li v-for="(r, i) in qualityReviewData.reasons.slice(0, 5)" :key="i">
              {{ r }}
            </li>
          </ul>
        </div>
        <div v-if="qualityReviewData.summary" style="margin-top: 8px; color: #666;">
          {{ qualityReviewData.summary }}
        </div>
      </div>
      </div><!-- /report-wrapper -->
    </template>
  </el-card>
</template>

<script lang="ts">
export default {
  emits: ['retry', 'reviewDone'],
}
</script>

<style scoped>
.placeholder {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* 报告占 ~80%，审核占 ~20% */
.report-wrapper {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.iframe-container {
  flex: 4;
  min-height: 0;
  display: flex;
  overflow: hidden;
}
.iframe-container iframe {
  flex: 1;
  border: none;
  border-radius: 8px;
}
.review-area {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding-top: 4px;
}
.review-actions {
  display: flex;
  gap: 8px;
}
.review-area h3 {
  margin: 0 0 4px;
  font-size: 14px;
}
.review-area p {
  font-size: 12px;
}
.review-area ul {
  font-size: 12px;
}
</style>
