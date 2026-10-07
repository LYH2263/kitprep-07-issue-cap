<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
const rows = ref<any[]>([])
const stats = ref<any>({})
onMounted(async () => {
  const orders = await api('/orders')
  const orderId = orders.length ? orders[0].id : 1
  const res = await api('/prep/shortages?order_id=' + orderId)
  rows.value = res.unprep || []
  stats.value = res.stats || {}
})
</script>
<template>
  <h1>未备清单</h1>
  <p class="sub">只登记整组成功的备料单；触顶整组失败时这里不会出现任何半成品行</p>
  <div class="kp-shortage-sticky" style="max-width:380px;transform:rotate(-1deg);margin-bottom:1rem">
    <h2>📒 未备 {{ stats.unprep_count ?? 0 }} · 合计 {{ stats.total_unprep_qty ?? 0 }}</h2>
    <div v-for="r in rows" :key="r.ingredient_id" class="kp-shortage-item">
      <span>{{ r.ingredient_name }} · {{ r.reason }}</span>
      <span class="kp-qty">−{{ r.qty }} {{ r.unit }}</span>
    </div>
    <p v-if="!rows.length" style="font-size:0.8rem;margin:0.5rem 0 0">暂无未备</p>
  </div>
  <div class="card" v-if="rows.length">
    <table>
      <thead><tr><th>原料</th><th>未备数量</th><th>事由</th><th>单位</th><th>备料单</th></tr></thead>
      <tbody>
        <tr v-for="r in rows" :key="r.ingredient_id">
          <td>{{ r.ingredient_name }}</td>
          <td><span class="badge badge-bad">{{ r.qty }}</span></td>
          <td>{{ r.reason }}</td>
          <td>{{ r.unit }}</td>
          <td>#{{ r.run_id }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
