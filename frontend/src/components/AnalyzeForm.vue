<script setup lang="ts">
import { reactive, ref } from 'vue'
import type { AnalyzeRequest } from '../types'

const props = defineProps<{
  submitting: boolean
  running: boolean
}>()

const emit = defineEmits<{
  submit: [payload: AnalyzeRequest]
}>()

const form = reactive<AnalyzeRequest>({
  keyword: '',
  max_posts: 1,
  max_comments: 20,
  analysis_mode: 'llm_annotation',
  mock_llm: true,
  headless: true,
  human_review_required: false,
})

const showAdvanced = ref(false)

function handleSubmit() {
  if (!form.keyword.trim()) return
  emit('submit', { ...form })
}
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <span>分析参数</span>
    </template>
    <el-form label-position="top" @submit.prevent="handleSubmit">
      <el-form-item label="关键词" :required="true">
        <el-input v-model="form.keyword" placeholder="输入搜索关键词" />
      </el-form-item>

      <el-row :gutter="12">
        <el-col :span="12">
          <el-form-item label="最大帖子数">
            <el-input-number v-model="form.max_posts" :min="1" :max="50" />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="每帖评论数">
            <el-input-number v-model="form.max_comments" :min="0" :max="200" />
          </el-form-item>
        </el-col>
      </el-row>

      <el-form-item label="分析模式">
        <el-select v-model="form.analysis_mode">
          <el-option label="规则模式 (rule)" value="rule" />
          <el-option label="LLM 标注 (llm_annotation)" value="llm_annotation" />
        </el-select>
      </el-form-item>

      <el-divider />
      <el-button type="text" @click="showAdvanced = !showAdvanced">
        {{ showAdvanced ? '收起' : '展开' }}高级设置
      </el-button>
      <template v-if="showAdvanced">
        <el-form-item label="Mock LLM">
          <el-switch v-model="form.mock_llm" />
        </el-form-item>
        <el-form-item label="无头模式 (Headless)">
          <el-switch v-model="form.headless" />
        </el-form-item>
        <el-form-item label="启用人工审核">
          <el-switch v-model="form.human_review_required" />
          <div style="font-size: 12px; color: #999; margin-top: 4px;">
            报告生成后暂停，等待人工审核通过/拒绝
          </div>
        </el-form-item>
      </template>

      <el-divider />
      <el-button
        type="primary"
        :loading="props.submitting || props.running"
        :disabled="props.submitting || props.running || !form.keyword.trim()"
        style="width: 100%"
        @click="handleSubmit"
      >
        {{ props.running ? '任务进行中...' : '开始分析' }}
      </el-button>
    </el-form>
  </el-card>
</template>
