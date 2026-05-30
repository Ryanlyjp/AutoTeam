<template>
  <div>
    <h2 class="text-xl font-bold text-white mb-2">任务历史</h2>
    <p class="text-sm text-gray-400 mb-6">
      查看后台任务的执行状态、耗时、参数和结果，也可以在这里强行停止当前活动或暂停全部自动行为。
    </p>

    <div class="mb-6 rounded-2xl border border-gray-800 bg-gray-900/90 p-5">
      <div class="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div class="space-y-2">
          <div class="text-sm text-gray-400">当前运行状态</div>
          <div class="text-base font-semibold text-white">
            {{ runtimeControl?.paused ? '已暂停全部活动' : '活动中' }}
          </div>
          <div class="text-sm text-gray-400">
            {{ currentActivityLabel }}
          </div>
          <div v-if="runtimeControl?.paused_at" class="text-xs text-gray-500">
            暂停时间：{{ formatTime(runtimeControl.paused_at) }}
          </div>
        </div>

        <div class="flex flex-wrap gap-3">
          <button
            @click="stopCurrent"
            :disabled="!runtimeControl?.current_activity || actionLoading"
            class="rounded-xl border px-4 py-2 text-sm font-medium transition"
            :class="!runtimeControl?.current_activity || actionLoading
              ? 'cursor-not-allowed border-gray-700 bg-gray-800 text-gray-500'
              : 'border-amber-500/30 bg-amber-500/10 text-amber-300 hover:bg-amber-500/20'"
          >
            {{ actionLoading === 'stop' ? '停止中...' : '强行停止当前活动' }}
          </button>

          <button
            @click="pauseAll"
            :disabled="runtimeControl?.paused || actionLoading"
            class="rounded-xl border px-4 py-2 text-sm font-medium transition"
            :class="runtimeControl?.paused || actionLoading
              ? 'cursor-not-allowed border-gray-700 bg-gray-800 text-gray-500'
              : 'border-rose-500/30 bg-rose-500/10 text-rose-300 hover:bg-rose-500/20'"
          >
            {{ actionLoading === 'pause' ? '暂停中...' : '暂停全部活动' }}
          </button>

          <button
            @click="resumeAll"
            :disabled="!runtimeControl?.paused || actionLoading"
            class="rounded-xl border px-4 py-2 text-sm font-medium transition"
            :class="!runtimeControl?.paused || actionLoading
              ? 'cursor-not-allowed border-gray-700 bg-gray-800 text-gray-500'
              : 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20'"
          >
            {{ actionLoading === 'resume' ? '恢复中...' : '恢复活动' }}
          </button>
        </div>
      </div>

      <div
        v-if="message"
        class="mt-4 rounded-xl border px-4 py-3 text-sm"
        :class="messageClass"
      >
        {{ message }}
      </div>
    </div>

    <TaskHistory :tasks="tasks" @cancel-task="cancelTask" />
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { api } from '../api.js'
import TaskHistory from './TaskHistory.vue'

const props = defineProps({
  tasks: { type: Array, default: () => [] },
  runtimeControl: {
    type: Object,
    default: null,
  },
})

const emit = defineEmits(['refresh'])

const actionLoading = ref('')
const message = ref('')
const messageClass = ref('')

const currentActivityLabel = computed(() => {
  const activity = props.runtimeControl?.current_activity
  if (!activity) {
    return props.runtimeControl?.paused ? '当前没有活动中的任务或流程' : '当前没有活动中的任务或流程'
  }
  const step = activity.step ? ` · ${activity.step}` : ''
  return `当前活动：${activity.command || activity.task_id || 'unknown'}${step}`
})

function formatTime(ts) {
  if (!ts) return '-'
  const d = new Date(ts * 1000)
  return `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`
}

function setMessage(text, tone = 'info') {
  message.value = text || ''
  messageClass.value = {
    success: 'border-green-500/20 bg-green-500/10 text-green-300',
    danger: 'border-red-500/20 bg-red-500/10 text-red-300',
    info: 'border-blue-500/20 bg-blue-500/10 text-blue-300',
  }[tone] || 'border-blue-500/20 bg-blue-500/10 text-blue-300'
  setTimeout(() => {
    if (message.value === text) {
      message.value = ''
    }
  }, 8000)
}

async function stopCurrent() {
  if (!props.runtimeControl?.current_activity || actionLoading.value) return
  actionLoading.value = 'stop'
  try {
    const result = await api.stopCurrentActivity()
    setMessage(result.message || '当前活动已强制停止', 'success')
    emit('refresh')
  } catch (e) {
    setMessage(e.message, 'danger')
  } finally {
    actionLoading.value = ''
  }
}

async function pauseAll() {
  if (props.runtimeControl?.paused || actionLoading.value) return
  actionLoading.value = 'pause'
  try {
    const result = await api.pauseAllActivity()
    setMessage(result.message || '全部活动已暂停', 'success')
    emit('refresh')
  } catch (e) {
    setMessage(e.message, 'danger')
  } finally {
    actionLoading.value = ''
  }
}

async function resumeAll() {
  if (!props.runtimeControl?.paused || actionLoading.value) return
  actionLoading.value = 'resume'
  try {
    const result = await api.resumeAllActivity()
    setMessage(result.message || '全部活动已恢复', 'success')
    emit('refresh')
  } catch (e) {
    setMessage(e.message, 'danger')
  } finally {
    actionLoading.value = ''
  }
}

async function cancelTask(task) {
  if (!task?.task_id || actionLoading.value) return
  actionLoading.value = `task:${task.task_id}`
  try {
    const result = await api.cancelTask(task.task_id)
    setMessage(result.message || `任务 ${task.task_id} 已进入终止流程`, 'success')
    emit('refresh')
  } catch (e) {
    setMessage(e.message, 'danger')
  } finally {
    actionLoading.value = ''
  }
}
</script>
