<template>
  <section class="page" data-module="pv_array">
    <header class="page-head">
      <div>
        <h2>光伏阵列管理</h2>
        <p class="page-desc">维护光伏阵列，围绕阵列编号、所属片区、组件型号、总装机容量做登记、筛选与逐档状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记光伏阵列</button>
        <button class="btn" type="button" @click="exportRows">导出光伏阵列清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in statCards" :key="item.label" class="stat-card">
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
        <span>所属片区</span>
        <input v-model="area" placeholder="按所属片区检索" />
      </label>
      <label class="filter-item">
        <span>阵列状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
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
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-if="nextAction(row['阵列状态'])"
              class="link"
              type="button"
              @click="runAction(String(nextAction(row['阵列状态'])), row)"
            >
              {{ nextAction(row['阵列状态']) }}
            </button>
            <span v-else class="muted-text">—</span>
          </td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">查看</button>
            <button class="link" type="button" @click="openEdit(row)">修改</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无光伏阵列数据，可先登记光伏阵列</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条光伏阵列记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 登记 / 修改：每次打开都重建空表单，不残留上一次的数 -->
    <div v-if="formVisible" class="modal-mask" @click.self="closeForm">
      <div class="modal">
        <h3 class="modal-title">{{ editingId === null ? '登记光伏阵列' : '修改光伏阵列' }}</h3>
        <form @submit.prevent="submitForm">
          <label v-for="field in formFields" :key="field" class="form-item">
            <span>{{ field }}<em v-if="requiredFields.includes(field)" class="required-mark">*</em></span>
            <input
              v-model="formValues[field]"
              :type="field === '投运日期' ? 'date' : 'text'"
              :placeholder="`请输入${field}`"
            />
          </label>
          <div class="modal-foot">
            <span v-if="formError" class="error-text">{{ formError }}</span>
            <div>
              <button class="btn ghost" type="button" @click="closeForm">取消</button>
              <button class="btn primary" type="submit">{{ saving ? '保存中…' : '保存' }}</button>
            </div>
          </div>
        </form>
      </div>
    </div>

    <!-- 单条详情：点开时按 id 向服务取最新值，不用列表里的旧对象 -->
    <div v-if="detailVisible" class="modal-mask" @click.self="closeDetail">
      <div class="modal">
        <h3 class="modal-title">光伏阵列详情</h3>
        <table v-if="detailRow" class="detail-table">
          <tbody>
            <tr v-for="field in detailFields" :key="field">
              <th>{{ field }}</th>
              <td>{{ detailRow[field] ?? '—' }}</td>
            </tr>
          </tbody>
        </table>
        <div class="modal-foot">
          <span v-if="detailError" class="error-text">{{ detailError }}</span>
          <button class="btn primary" type="button" @click="closeDetail">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type FormValues = Record<string, string>

const ENDPOINT = '/api/pv_array'
const columns = ["阵列编号", "所属片区", "组件型号", "单块功率", "串联片数", "总装机容量", "投运日期", "阵列状态"]
const requiredFields = ["阵列编号", "所属片区", "组件型号"]
const formFields = ["阵列编号", "所属片区", "组件型号", "单块功率", "串联片数", "总装机容量", "投运日期"]
const detailFields = ["阵列编号", "所属片区", "组件型号", "单块功率", "串联片数", "总装机容量", "投运日期", "阵列状态"]
const statuses = ["投运", "运行中", "限功率", "计划停机"]
// 逐档推进：每行只出现当前档允许的唯一下一档动作，天然不能跨档
const NEXT_ACTION: Record<string, string | undefined> = {
  "投运": "确认投运",
  "运行中": "降功率运行",
  "限功率": "申请停机",
  "计划停机": undefined,
  "故障停机": undefined,
}

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const statusStats = ref<Record<string, number>>({})

const keyword = ref('')
const area = ref('')
const statusFilter = ref('')

const statCards = computed(() => statuses.map((s) => ({ label: `${s}阵列数`, value: statusStats.value[s] ?? 0 })))

function nextAction(status: string | number | null | undefined): string | undefined {
  return NEXT_ACTION[String(status ?? '')]
}

function buildQuery(): string {
  const params = new URLSearchParams()
  if (keyword.value.trim()) params.set('keyword', keyword.value.trim())
  if (area.value.trim()) params.set('area', area.value.trim())
  if (statusFilter.value) params.set('status', statusFilter.value)
  return params.toString()
}

function resetFilters() {
  keyword.value = ''
  area.value = ''
  statusFilter.value = ''
  void reload()
}

// 每次都重新拉取并整体替换，本地不缓存上一版
async function reload() {
  errorMessage.value = ''
  try {
    const query = buildQuery()
    const response = await request(`${ENDPOINT}?${query}`, { cache: 'no-store' })
    if (!response.ok) {
      throw new Error('光伏阵列列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    statusStats.value = payload.stats ?? {}
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '光伏阵列列表读取失败'
  }
}

function emptyForm(): FormValues {
  return Object.fromEntries(formFields.map((field) => [field, '']))
}

const formVisible = ref(false)
const saving = ref(false)
const formError = ref('')
const editingId = ref<number | null>(null)
const formValues = reactive<FormValues>(emptyForm())

function openCreate() {
  Object.assign(formValues, emptyForm())
  editingId.value = null
  formError.value = ''
  formVisible.value = true
}

async function openEdit(row: Row) {
  formError.value = ''
  formVisible.value = true
  // 先给空表单，再按 id 拉最新值，避免残留上一次打开的数据
  Object.assign(formValues, emptyForm())
  editingId.value = Number(row.id)
  try {
    const response = await request(`${ENDPOINT}/${row.id}`, { cache: 'no-store' })
    if (!response.ok) {
      throw new Error('光伏阵列详情读取失败')
    }
    const latest: Row = await response.json()
    for (const field of formFields) {
      formValues[field] = latest[field] == null ? '' : String(latest[field])
    }
  } catch (error) {
    formError.value = error instanceof Error ? error.message : '光伏阵列详情读取失败'
  }
}

function closeForm() {
  formVisible.value = false
  saving.value = false
  formError.value = ''
  Object.assign(formValues, emptyForm())
}

async function submitForm() {
  formError.value = ''
  const missing = requiredFields.filter((field) => !formValues[field].trim())
  if (missing.length) {
    formError.value = `缺少必填字段：${missing.join('、')}，不许保存`
    return
  }
  saving.value = true
  try {
    const values: FormValues = {}
    for (const field of formFields) values[field] = formValues[field].trim()
    const url = editingId.value === null ? ENDPOINT : `${ENDPOINT}/${editingId.value}`
    const method = editingId.value === null ? 'POST' : 'PUT'
    const response = await request(url, {
      method,
      cache: 'no-store',
      body: JSON.stringify({ values }),
    })
    const payload = await response.json().catch(() => ({ ok: false, message: '服务无响应，请稍后重试' }))
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message || '光伏阵列保存未生效，请稍后重试')
    }
    closeForm()
    await reload()
  } catch (error) {
    formError.value = error instanceof Error ? error.message : '光伏阵列保存失败'
  } finally {
    saving.value = false
  }
}

const detailVisible = ref(false)
const detailRow = ref<Row | null>(null)
const detailError = ref('')

async function openDetail(row: Row) {
  detailVisible.value = true
  detailRow.value = null
  detailError.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`, { cache: 'no-store' })
    if (!response.ok) {
      throw new Error('光伏阵列详情读取失败')
    }
    detailRow.value = await response.json()
  } catch (error) {
    detailError.value = error instanceof Error ? error.message : '光伏阵列详情读取失败'
  }
}

function closeDetail() {
  detailVisible.value = false
  detailRow.value = null
  detailError.value = ''
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      cache: 'no-store',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json().catch(() => ({ ok: false, message: '服务无响应，请稍后重试' }))
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message || '光伏阵列动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '光伏阵列操作失败'
  }
}

// 导出与列表同一过滤口径：带查询参数、no-store，并按返回条数下载，不用 window.open 缓存
async function exportRows() {
  errorMessage.value = ''
  try {
    const query = buildQuery()
    const response = await request(`${ENDPOINT}/export?${query}`, { cache: 'no-store' })
    if (!response.ok) {
      throw new Error('光伏阵列清单导出失败')
    }
    const payload = await response.json()
    const items: Row[] = payload.items ?? []
    if (items.length !== payload.total) {
      throw new Error('导出清单条数与列表不一致，请重新导出')
    }
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = 'pv_array_export.json'
    link.click()
    URL.revokeObjectURL(url)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '光伏阵列清单导出失败'
  }
}

onMounted(reload)
</script>
