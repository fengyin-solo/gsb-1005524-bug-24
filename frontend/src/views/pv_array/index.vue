<template>
  <section class="page" data-module="pv_array">
    <header class="page-head">
      <div>
        <h2>光伏阵列管理</h2>
        <p class="page-desc">维护光伏阵列，围绕阵列编号、所属片区、组件型号、单块功率做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记光伏阵列</button>
        <button class="btn" type="button" @click="exportRows">导出光伏阵列清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>阵列编号</span>
        <input v-model="keyword" placeholder="按阵列编号检索" />
      </label>
      <label class="filter-item">
        <span>阵列状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <button v-if="column === '阵列编号'" class="link" type="button" @click="openDetail(row)">
              {{ row[column] ?? '—' }}
            </button>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">详情</button>
            <button class="link" type="button" @click="openEdit(row)">修改</button>
            <button
              v-if="nextAction(row)"
              class="link"
              type="button"
              @click="runAction(nextAction(row) as string, row)"
            >
              {{ nextAction(row) }}
            </button>
            <span v-else class="muted-text">已到末档</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无光伏阵列数据，可先登记光伏阵列</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条光伏阵列记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="formVisible" class="modal-mask" @click.self="closeForm">
      <div class="modal">
        <h3>{{ editingId === null ? '登记光伏阵列' : '修改光伏阵列' }}</h3>
        <p class="modal-tip">阵列编号、所属片区、组件型号为必填项；总装机容量保存后立即落库。</p>
        <form @submit.prevent="submitForm">
          <label v-for="field in formFields" :key="field.key" class="form-item">
            <span>{{ field.label }}<em v-if="field.required">*</em></span>
            <input
              v-model="form[field.key]"
              :type="field.type"
              :disabled="editingId !== null && field.key === '阵列编号'"
              :placeholder="`请输入${field.label}`"
            />
          </label>
          <p v-if="formError" class="error-text">{{ formError }}</p>
          <div class="modal-actions">
            <button class="btn" type="button" @click="closeForm">取消</button>
            <button class="btn primary" type="submit" :disabled="saving">{{ saving ? '保存中…' : '保存' }}</button>
          </div>
        </form>
      </div>
    </div>

    <div v-if="detail" class="modal-mask" @click.self="detail = null">
      <div class="modal">
        <h3>光伏阵列详情</h3>
        <dl class="detail-list">
          <div v-for="column in columns" :key="column">
            <dt>{{ column }}</dt>
            <dd>{{ detail[column] ?? '—' }}</dd>
          </div>
        </dl>
        <div class="modal-actions">
          <button class="btn" type="button" @click="detail = null">关闭</button>
          <button class="btn primary" type="button" @click="openEdit(detail)">修改</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>

const ENDPOINT = '/api/pv_array'
const columns = ["阵列编号", "所属片区", "组件型号", "单块功率", "串联片数", "总装机容量", "投运日期", "阵列状态"]
const statuses = ["投运", "运行中", "限功率", "计划停机"]
// 动作与状态档严格对齐：当前状态只能走到紧邻的下一档，页面上也只放出下一档动作。
const nextActionByStatus: Record<string, string> = {
  投运: '并网运行',
  运行中: '降功率运行',
  限功率: '申请停机',
}
const formFields = [
  { key: '阵列编号', label: '阵列编号', required: true, type: 'text' },
  { key: '所属片区', label: '所属片区', required: true, type: 'text' },
  { key: '组件型号', label: '组件型号', required: true, type: 'text' },
  { key: '单块功率', label: '单块功率', required: false, type: 'text' },
  { key: '串联片数', label: '串联片数', required: false, type: 'text' },
  { key: '总装机容量', label: '总装机容量', required: false, type: 'text' },
  { key: '投运日期', label: '投运日期', required: false, type: 'date' },
] as const

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')
const stats = ref([
  { label: '投运阵列数', value: 0 },
  { label: '运行阵列数', value: 0 },
  { label: '限电阵列数', value: 0 },
  { label: '停机阵列数', value: 0 },
])

const formVisible = ref(false)
const saving = ref(false)
const editingId = ref<number | null>(null)
const formError = ref('')
const form = reactive<Record<string, string>>({})
const detail = ref<Row | null>(null)

function emptyForm(): Record<string, string> {
  return { 阵列编号: '', 所属片区: '', 组件型号: '', 单块功率: '', 串联片数: '', 总装机容量: '', 投运日期: '' }
}

// 每次请求都带时间戳，叠加后端 no-store 响应头，保证刷新读到的是最后一次保存的值。
function freshUrl(path: string): string {
  const separator = path.includes('?') ? '&' : '?'
  return `${path}${separator}_=${Date.now()}`
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  // 导出与列表、详情走同一个数据源；时间戳避免浏览器复用上一版导出文件。
  window.open(freshUrl(`${ENDPOINT}/export`), '_blank')
}

function nextAction(row: Row): string | null {
  return nextActionByStatus[String(row.status ?? row['阵列状态'] ?? '')] ?? null
}

function openCreate() {
  editingId.value = null
  Object.assign(form, emptyForm())
  formError.value = ''
  formVisible.value = true
}

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(freshUrl(`${ENDPOINT}/${row.id}`))
    if (!response.ok) {
      throw new Error('光伏阵列详情读取失败')
    }
    detail.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '光伏阵列详情读取失败'
  }
}

async function openEdit(row: Row) {
  detail.value = null
  errorMessage.value = ''
  try {
    // 修改前先按 id 拉单条最新值，不用列表上的旧对象，避免页面残留上一次的数。
    const response = await request(freshUrl(`${ENDPOINT}/${row.id}`))
    if (!response.ok) {
      throw new Error('光伏阵列详情读取失败')
    }
    const latest: Row = await response.json()
    editingId.value = Number(latest.id)
    const values = emptyForm()
    for (const field of formFields) {
      values[field.key] = latest[field.key] == null ? '' : String(latest[field.key])
    }
    Object.assign(form, values)
    formError.value = ''
    formVisible.value = true
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '光伏阵列详情读取失败'
  }
}

function closeForm() {
  formVisible.value = false
  formError.value = ''
}

async function submitForm() {
  formError.value = ''
  const missing = formFields
    .filter((field) => field.required && !form[field.key].trim())
    .map((field) => field.label)
  if (missing.length) {
    formError.value = `缺少必填字段：${missing.join('、')}`
    return
  }
  const values: Record<string, string | null> = {}
  for (const field of formFields) {
    values[field.key] = form[field.key] === '' ? null : form[field.key].trim()
  }
  saving.value = true
  try {
    const path = editingId.value === null ? ENDPOINT : `${ENDPOINT}/${editingId.value}`
    const response = await request(freshUrl(path), {
      method: editingId.value === null ? 'POST' : 'PUT',
      body: JSON.stringify({ values }),
    })
    if (!response.ok) {
      throw new Error('光伏阵列保存失败，请稍后重试')
    }
    const payload = await response.json()
    if (!payload.ok) {
      // 重复编号等业务拒收原样展示，保留表单数据让操作者核对。
      formError.value = payload.message || '光伏阵列保存被拒绝'
      return
    }
    formVisible.value = false
    await Promise.all([reload(), loadStats()])
  } catch (error) {
    formError.value = error instanceof Error ? error.message : '光伏阵列保存失败'
  } finally {
    saving.value = false
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(freshUrl(`${ENDPOINT}/${row.id}/actions`), {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    if (!response.ok) {
      throw new Error('光伏阵列动作未生效，请稍后重试')
    }
    const payload = await response.json()
    if (!payload.ok) {
      errorMessage.value = payload.message || '光伏阵列操作未生效'
      return
    }
    await Promise.all([reload(), loadStats()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '光伏阵列操作失败'
  }
}

async function loadStats() {
  try {
    const response = await request(freshUrl(`${ENDPOINT}/stats`))
    if (!response.ok) {
      return
    }
    const payload = await response.json()
    const statusCount: Record<string, number> = payload.statuses ?? {}
    stats.value = [
      { label: '投运阵列数', value: statusCount['投运'] ?? 0 },
      { label: '运行阵列数', value: statusCount['运行中'] ?? 0 },
      { label: '限电阵列数', value: statusCount['限功率'] ?? 0 },
      { label: '停机阵列数', value: statusCount['计划停机'] ?? 0 },
    ]
  } catch {
    // 统计失败不阻塞列表使用，下次刷新会再拉。
  }
}

async function reload() {
  errorMessage.value = ''
  const params = new URLSearchParams()
  if (keyword.value.trim()) {
    params.set('keyword', keyword.value.trim())
  }
  if (statusFilter.value) {
    params.set('status', statusFilter.value)
  }
  try {
    const response = await request(freshUrl(`${ENDPOINT}?${params.toString()}`))
    if (!response.ok) {
      throw new Error('光伏阵列列表读取失败')
    }
    const payload = await response.json()
    // 整体替换列表数据，避免上一版的行在页面上重复残留。
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '光伏阵列列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void loadStats()
})
</script>

<style scoped>
.muted-text { color: var(--muted, #667085); font-size: 12px; }
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(16, 24, 40, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.modal {
  background: #fff;
  border-radius: 10px;
  padding: 20px 24px;
  width: 520px;
  max-height: 85vh;
  overflow-y: auto;
}
.modal h3 { margin: 0 0 4px; font-size: 16px; }
.modal-tip { margin: 0 0 12px; color: var(--muted, #667085); font-size: 12px; }
.form-item { display: block; margin-bottom: 10px; }
.form-item span { display: block; font-size: 12px; color: var(--muted, #667085); margin-bottom: 4px; }
.form-item em { color: #b42318; font-style: normal; margin-left: 2px; }
.form-item input,
.form-item select,
.filter-item select {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--border, #d0d5dd);
  border-radius: 6px;
  padding: 6px 8px;
  font-size: 13px;
}
.filter-item select { width: auto; min-width: 120px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 14px; }
.detail-list { margin: 0; }
.detail-list div { display: flex; justify-content: space-between; gap: 16px; padding: 6px 0; border-bottom: 1px solid var(--border, #eaecf0); }
.detail-list dt { color: var(--muted, #667085); font-size: 13px; }
.detail-list dd { margin: 0; font-size: 13px; text-align: right; }
</style>
