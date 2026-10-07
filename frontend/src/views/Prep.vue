<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
const tree = ref<any[]>([])
const data = ref<any>(null)
const shortages = ref<any[]>([])
const orders = ref<any[]>([])
const limitError = ref<any>(null)
const running = ref(false)
function parseError(e: any): any {
  try {
    const d = JSON.parse(e?.message || '')
    const det = d?.detail
    if (det && typeof det === 'object' && det.code === 'daily_limit_exceeded') return det
    if (typeof det === 'string') return { message: det, items: [] }
  } catch { /* fall through */ }
  return { message: e?.message || '生成失败', items: [] }
}
async function refresh() {
  // 备料台 / 占用列 / 未备清单统一回读已提交账面，三块永远是同一套账
  try { data.value = await api('/prep/latest?order_id=1') } catch { data.value = null }
  try {
    const res = await api('/prep/shortages?order_id=1')
    shortages.value = res.shortages || []
  } catch { shortages.value = [] }
}
async function run() {
  running.value = true
  limitError.value = null
  try {
    data.value = await api('/prep/run?order_id=1', { method: 'POST' })
  } catch (e: any) {
    limitError.value = parseError(e)  // 触顶整组失败：账面未被这次生成改动
  } finally {
    running.value = false
  }
  await refresh()
}
onMounted(async () => {
  tree.value = await api('/bom/tree')
  orders.value = await api('/orders')
  await refresh()
})
</script>
<template>
  <h1>备料工作台</h1>
  <p class="sub">左 BOM 树 · 中备料表 · 右缺料便利贴 · 顶栏订单芯片</p>
  <div class="kp-chips" style="margin-bottom:0.75rem" v-if="orders.length">
    <span v-for="o in orders" :key="o.id" class="kp-chip" style="cursor:default">
      {{ o.code }} · {{ o.outlet }}
    </span>
  </div>
  <button class="btn" :disabled="running" @click="run">生成备料单</button>
  <div v-if="limitError" class="kp-banner">
    <strong>⚠ {{ limitError.message || '当日可领已满' }}</strong>
    — 本次生成已整组撤回：未写出备料行、未挂当日占用、未新增未备行、库存结存未变。
    <ul>
      <li v-for="it in limitError.items" :key="it.ingredient_id">
        {{ it.ingredient_name }}：本次需 {{ it.need_qty }} {{ it.unit }}，当日已占 {{ it.occupied_today }}，当日上限 {{ it.daily_limit }}
      </li>
    </ul>
  </div>
  <div class="kp-workbench" style="margin-top:0.85rem">
    <aside class="kp-bom-tree">
      <h2>菜品 / BOM</h2>
      <div v-for="d in tree" :key="d.code" class="kp-dish-node">
        <strong>{{ d.dish }}</strong>
        <span style="font-size:0.7rem;color:#8a8078">{{ d.code }}</span>
        <ul>
          <li v-for="(c,i) in d.children" :key="i">{{ c.ingredient }} · {{ c.qty }} {{ c.unit }}</li>
        </ul>
      </div>
    </aside>
    <section class="kp-worksheet" v-if="data">
      <h2>备料单 · {{ data.order?.code }} · {{ data.order?.outlet }}<span v-if="data.biz_date"> · {{ data.biz_date }}</span></h2>
      <table>
        <thead><tr><th>原料</th><th>需求</th><th>库存</th><th>单位</th><th>当日上限</th><th>当日已占(含本次)</th></tr></thead>
        <tbody>
          <tr v-for="l in data.prep_lines" :key="l.ingredient_id">
            <td>{{ l.ingredient_name }}</td><td>{{ l.need_qty }}</td><td>{{ l.stock_qty }}</td><td>{{ l.unit }}</td>
            <td>{{ l.daily_limit > 0 ? l.daily_limit : '不限' }}</td>
            <td>{{ l.occupied_after ?? '—' }}</td>
          </tr>
        </tbody>
      </table>
    </section>
    <section class="kp-worksheet" v-else>
      <h2>备料单</h2>
      <p class="muted" style="font-size:0.85rem">尚未生成备料单，点击上方「生成备料单」。</p>
    </section>
    <aside class="kp-shortage-sticky">
      <h2>⚠ 缺料便利贴</h2>
      <div v-for="r in shortages" :key="r.ingredient_id" class="kp-shortage-item">
        <span>{{ r.ingredient_name }}</span>
        <span class="kp-qty">−{{ r.shortage }} {{ r.unit }}</span>
      </div>
      <p v-if="!shortages.length" style="font-size:0.8rem;margin:0.5rem 0 0">暂无缺料</p>
    </aside>
  </div>
</template>
