<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, ApiError } from '../api'
const tree = ref<any[]>([])
const data = ref<any>(null)
const preview = ref<any>(null)
const shortages = ref<any[]>([])
const orders = ref<any[]>([])
const orderId = ref<number>(1)
const capError = ref<any>(null)
const running = ref(false)

async function loadLatest() {
  data.value = await api(`/prep/latest?order_id=${orderId.value}`)
  shortages.value = data.value.unprep || []
}
async function loadPreview() {
  preview.value = await api(`/prep/preview?order_id=${orderId.value}`)
}
async function run() {
  capError.value = null
  running.value = true
  try {
    await api(`/prep/run?order_id=${orderId.value}`, { method: 'POST' })
  } catch (e: any) {
    // 触顶整组失败：服务端只回「当日可领已满」；前端不写成结存不够
    if (e instanceof ApiError && e.status === 409) {
      capError.value = e.detail
    } else {
      capError.value = { message: e?.message || '生成失败' }
    }
  } finally {
    running.value = false
    // 无论成败都重拉同一套账本：失败时呈现的仍是触顶前已提交的备料单与占用
    await Promise.all([loadLatest(), loadPreview()])
  }
}
onMounted(async () => {
  tree.value = await api('/bom/tree')
  orders.value = await api('/orders')
  if (orders.value.length) orderId.value = orders.value[0].id
  await Promise.all([loadLatest(), loadPreview()])
})
</script>
<template>
  <h1>备料工作台</h1>
  <p class="sub">左 BOM 树 · 中备料单（含当日已占/上限/剩余）· 右未备清单 · 顶栏订单芯片</p>
  <div class="kp-chips" style="margin-bottom:0.75rem" v-if="orders.length">
    <span v-for="o in orders" :key="o.id" class="kp-chip" style="cursor:default">
      {{ o.code }} · {{ o.outlet }}
    </span>
  </div>
  <div style="display:flex;align-items:center;gap:0.75rem;flex-wrap:wrap">
    <button class="btn" :disabled="running" @click="run">{{ running ? '生成中…' : '生成备料单' }}</button>
    <span v-if="preview?.would_exceed_cap" class="badge badge-bad"
          style="font-size:0.78rem;padding:0.25rem 0.55rem">
      按当前上限本次会触顶（仍可点击，整组失败不落任何行）
    </span>
    <span v-if="data?.latest_run" class="muted" style="font-size:0.78rem">
      当前备料单 #{{ data.latest_run.id }} · {{ data.business_date }}
    </span>
    <span v-else class="muted" style="font-size:0.78rem">当日尚无备料单</span>
  </div>

  <div v-if="capError" class="card" style="margin-top:0.75rem;border-color:var(--kp-bad);background:#fbe6e2">
    <strong style="color:var(--kp-bad)">⛔ {{ capError.message }}</strong>
    <table style="margin-top:0.4rem">
      <thead><tr><th>原料</th><th>当日上限</th><th>当日已占</th><th>本次需求</th><th>单位</th></tr></thead>
      <tbody>
        <tr v-for="v in capError.violations || []" :key="v.ingredient_id">
          <td>{{ v.ingredient_name }}</td><td>{{ v.daily_limit }}</td>
          <td>{{ v.occupied_qty }}</td><td>{{ v.need_qty }}</td><td>{{ v.unit }}</td>
        </tr>
      </tbody>
    </table>
    <p class="muted" style="margin:0.4rem 0 0;font-size:0.75rem">
      整组失败：本次没有任何菜成单，已写行已撤回、占用退回、未备清单不挂行、账面结存不变。
    </p>
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
      <h2>备料单 · {{ data.order?.code }} · {{ data.order?.outlet }}</h2>
      <p v-if="!data.prep_lines.length" class="muted" style="font-size:0.8rem">
        当日还没有成功生成的备料单。触顶时不会出现半成品。
      </p>
      <table v-else>
        <thead>
          <tr><th>原料</th><th>本次需求</th><th>账面结存</th><th>当日上限</th><th>当日已占</th><th>剩余可领</th><th>单位</th></tr>
        </thead>
        <tbody>
          <tr v-for="l in data.prep_lines" :key="l.ingredient_id">
            <td>{{ l.ingredient_name }}</td>
            <td>{{ l.need_qty }}</td>
            <td>{{ l.stock_qty }}</td>
            <td>{{ l.daily_limit > 0 ? l.daily_limit : '不限' }}</td>
            <td>{{ l.occupied_qty }}</td>
            <td>
              <span v-if="l.remaining_qty !== null">{{ l.remaining_qty }}</span>
              <span v-else class="muted">不限</span>
            </td>
            <td>{{ l.unit }}</td>
          </tr>
        </tbody>
      </table>
    </section>
    <aside class="kp-shortage-sticky">
      <h2>📒 未备清单</h2>
      <div v-for="r in shortages" :key="r.ingredient_id" class="kp-shortage-item">
        <span>{{ r.ingredient_name }}<br /><small style="color:#8a7a40">{{ r.reason }}</small></span>
        <span class="kp-qty">−{{ r.qty }} {{ r.unit }}</span>
      </div>
      <p v-if="!shortages.length" style="font-size:0.8rem;margin:0.5rem 0 0">暂无未备</p>
    </aside>
  </div>
</template>
