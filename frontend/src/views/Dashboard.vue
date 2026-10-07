<template>
  <section class="page">
    <header class="page-head">
      <div>
        <h2>运营概览</h2>
        <p class="page-desc">汇总各业务模块的关键指标，先看总量再看异常。</p>
      </div>
    </header>
    <div class="stat-row">
      <article v-for="card in cards" :key="card.label" class="stat-card">
        <span class="stat-label">{{ card.label }}</span>
        <strong class="stat-value">{{ card.value }}</strong>
      </article>
    </div>

    <h3 class="block-title">光伏阵列状态分布</h3>
    <div class="stat-row">
      <article v-for="item in pvStatusCards" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <table class="data-table">
      <thead>
        <tr><th>业务模块</th><th>今日新增</th><th>待处理</th><th>异常量</th><th>状态分布</th></tr>
      </thead>
      <tbody>
        <tr v-for="row in moduleRows" :key="row.name">
          <td>{{ row.name }}</td>
          <td>{{ row.created }}</td>
          <td>{{ row.pending }}</td>
          <td>{{ row.abnormal }}</td>
          <td>{{ formatStatuses(row.statuses) }}</td>
        </tr>
      </tbody>
    </table>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { fetchJson } from '@/api/client'

type Overview = {
  cards: { label: string; value: number }[]
  modules: { name: string; created: number; pending: number; abnormal: number; statuses?: Record<string, number> }[]
}

const PV_STATUSES = ["投运", "运行中", "限功率", "计划停机"]

const cards = ref<Overview['cards']>([])
const moduleRows = ref<Overview['modules']>([])

const pvStatusCards = computed(() => {
  const pv = moduleRows.value.find((row) => row.name === 'pv_array')
  return PV_STATUSES.map((status) => ({ label: `${status}阵列数`, value: pv?.statuses?.[status] ?? 0 }))
})

function formatStatuses(statuses?: Record<string, number>): string {
  if (!statuses) return '—'
  return PV_STATUSES.map((status) => `${status} ${statuses[status] ?? 0}`).join(' / ')
}

onMounted(async () => {
  try {
    const payload = await fetchJson<Overview>('/api/overview', { cache: 'no-store' })
    cards.value = payload.cards
    moduleRows.value = payload.modules
  } catch {
    cards.value = [{"label": "业务模块", "value": 0}, {"label": "今日新增", "value": 0}]
    moduleRows.value = [{"name": "光伏阵列", "created": 0, "pending": 0, "abnormal": 0}]
  }
})
</script>
