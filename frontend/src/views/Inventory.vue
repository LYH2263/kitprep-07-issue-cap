<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
const rows = ref<any[]>([])
const occupancy = ref<Record<number, any>>({})
const drafts = ref<Record<number, string>>({})
const saving = ref<Record<number, boolean>>({})
const messages = ref<Record<number, { ok: boolean; text: string }>>({})

async function loadOccupancy() {
  const res = await api('/prep/occupancy')
  occupancy.value = Object.fromEntries((res.items || []).map((x: any) => [x.ingredient_id, x]))
}
async function save(id: number) {
  const raw = (drafts.value[id] ?? '').trim()
  const value = Number(raw)
  messages.value[id] = { ok: true, text: '' }
  if (raw === '' || !Number.isFinite(value) || value < 0) {
    messages.value[id] = { ok: false, text: '当日上限不能为负数（0 表示不限）' }
    return
  }
  saving.value[id] = true
  try {
    const r = await api('/inventory/' + id, { method: 'PATCH', body: JSON.stringify({ daily_limit: value }) })
    const row = rows.value.find((x) => x.id === id)
    if (row) row.daily_limit = r.daily_limit
    drafts.value[id] = String(r.daily_limit)
    messages.value[id] = { ok: true, text: '已保存' }
    await loadOccupancy()
  } catch (e: any) {
    messages.value[id] = { ok: false, text: e?.message || '保存失败' }
  } finally {
    saving.value[id] = false
  }
}
onMounted(async () => {
  rows.value = await api('/inventory')
  for (const r of rows.value) drafts.value[r.id] = String(r.daily_limit ?? 0)
  await loadOccupancy()
})
</script>
<template>
  <h1>库存</h1>
  <p class="sub">中央厨房原料库存 · 当日最多可领量（0 = 不按当日上限拦截）· 当日已占来自已生成的备料单</p>
  <div class="card">
    <table>
      <thead>
        <tr><th>编码</th><th>名称</th><th>账面结存</th><th>单位</th><th>当日上限</th><th>当日已占</th><th>剩余可领</th><th></th></tr>
      </thead>
      <tbody>
        <tr v-for="r in rows" :key="r.id">
          <td>{{ r.code }}</td>
          <td>{{ r.name }}</td>
          <td>{{ r.stock_qty }}</td>
          <td>{{ r.unit }}</td>
          <td>
            <input
              v-model="drafts[r.id]"
              type="number"
              min="0"
              step="0.01"
              style="width:5.5rem"
              @keyup.enter="save(r.id)"
            />
          </td>
          <td>{{ occupancy[r.id]?.occupied_qty ?? 0 }}</td>
          <td>
            <span v-if="Number(r.daily_limit) > 0">
              {{ occupancy[r.id]?.remaining_qty ?? r.daily_limit }}
              <span
                v-if="(occupancy[r.id]?.occupied_qty ?? 0) >= r.daily_limit"
                class="badge badge-bad"
              >已满</span>
            </span>
            <span v-else class="muted">不限</span>
          </td>
          <td>
            <button class="btn" style="padding:0.2rem 0.6rem;font-size:0.75rem"
                    :disabled="saving[r.id]" @click="save(r.id)">
              {{ saving[r.id] ? '保存中' : '保存上限' }}
            </button>
            <span v-if="messages[r.id]?.text"
                  :style="{ fontSize: '0.72rem', marginLeft: '0.4rem', color: messages[r.id].ok ? 'var(--kp-ok)' : 'var(--kp-bad)' }">
              {{ messages[r.id].text }}
            </span>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
