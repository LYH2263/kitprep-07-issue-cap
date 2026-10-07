<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
const rows = ref<any[]>([])
const flashOk = ref('')
const flashErr = ref('')
function errText(e: any): string {
  try {
    const d = JSON.parse(e?.message || '')
    if (typeof d?.detail === 'string') return d.detail
    if (Array.isArray(d?.detail)) return d.detail.map((x: any) => x?.msg).filter(Boolean).join('；')
  } catch { /* fall through */ }
  return e?.message || '保存失败'
}
async function load() { rows.value = await api('/inventory') }
async function save(r: any) {
  flashOk.value = ''; flashErr.value = ''
  try {
    await api(`/inventory/${r.id}/limit`, {
      method: 'PUT',
      body: JSON.stringify({ daily_limit: Number(r.daily_limit) }),
    })
    flashOk.value = `「${r.name}」当日上限已保存`
  } catch (e: any) {
    flashErr.value = errText(e)  // 负数被拒：定义与已有单都不动
  }
  await load()  // 回读账面：保存失败时输入框回退到已保存值
}
onMounted(load)
</script>
<template>
  <h1>库存</h1>
  <p class="sub">中央厨房原料库存 · 当日上限 0 = 当日不限 · 当日已占为今日成功备料单占用合计，不扣减库存结存</p>
  <div class="card">
    <p v-if="flashOk" class="kp-flash-ok">{{ flashOk }}</p>
    <p v-if="flashErr" class="kp-flash-err">{{ flashErr }}</p>
    <table>
      <thead><tr><th>编码</th><th>名称</th><th>库存</th><th>单位</th><th>当日已占</th><th>当日上限</th><th></th></tr></thead>
      <tbody>
        <tr v-for="r in rows" :key="r.id ?? JSON.stringify(r)">
          <td>{{ r.code }}</td><td>{{ r.name }}</td><td>{{ r.stock_qty }}</td><td>{{ r.unit }}</td>
          <td>{{ r.occupied_today }}</td>
          <td>
            <input v-model.number="r.daily_limit" class="kp-limit-input" type="number" min="0" step="any" />
          </td>
          <td><button class="btn" @click="save(r)">保存上限</button></td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
