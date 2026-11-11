<script setup lang="ts">
import {computed} from 'vue'
import {display} from '../quick/model'
const props=defineProps<{report:any}>()
const missing=computed(()=>Object.entries(props.report.missing_fields??{}) as [string,number][])
const natureNames:Record<string,string>={real_experiment:'本人确认的真实实验',synthetic:'合成/软件验收数据',unknown_legacy:'遗留或真实性未知'}
function reasons(row:any){return String(row.meta_exclusion_reasons||'').split(';').filter(Boolean).map(code=>props.report.reason_labels?.[code]??code)}
</script>
<template>
 <div class="readiness-review">
  <h3>{{report.training_status}}</h3>
  <p>本次扫描 {{report.run_count}} 次运行、{{report.result_count}} 条样品测量。可训练 {{report.eligible_count}} 条；每条记录的缺口与审核原因见下表。</p>
  <p class="quick-help">同一运行的多片样品与连续实验按关联序列分组。只有满足真实性、审核、材料及工艺可比性要求的数据才可进入训练；本报告没有生成模型指标。</p>
  <div class="quick-metrics"><div><span>可训练测量</span><strong>{{report.eligible_count}} / {{report.result_count}}</strong></div><div><span>来源单位异常</span><strong>{{report.unit_audit?.anomaly_count??'待扫描'}}</strong></div><div><span>跨训练/测试的共享组</span><strong>{{report.group_split_audit?.shared_groups_across_splits?.length??'待扫描'}}</strong></div></div>
  <h4>材料覆盖</h4><div class="quick-scroll" tabindex="0" aria-label="材料覆盖与就绪数量"><table class="quick-table"><thead><tr><th scope="col">薄膜材料</th><th scope="col">测量条数</th><th scope="col">可训练条数</th></tr></thead><tbody><tr v-for="(value,name) in report.by_material" :key="name"><th scope="row">{{name}}</th><td>{{value.row_count}}</td><td>{{value.eligible_count}}</td></tr></tbody></table></div>
  <h4>数据真实性</h4><p v-for="(count,name) in report.data_nature" :key="name">{{natureNames[String(name)]??name}}：{{count}} 条</p>
  <h4>字段完整性</h4><p class="quick-help">零值计为已记录。承接参考膜厚不冒充本次实验前实测值；均匀性为空不填零。</p><div class="quick-scroll" tabindex="0" aria-label="数据字段缺失统计"><table class="quick-table"><thead><tr><th scope="col">字段</th><th scope="col">已记录</th><th scope="col">缺失</th></tr></thead><tbody><tr v-for="[name,count] in missing" :key="name"><th scope="row">{{report.field_labels?.[name]??name}}</th><td>{{report.result_count-count}}</td><td>{{count}}</td></tr></tbody></table></div>
  <h4>逐条测量审核</h4><p v-if="!report.rows?.length" class="empty">当前筛选范围没有测量记录，不能据此判断模型适用性。</p><div v-else class="quick-scroll" tabindex="0" aria-label="逐条测量可训练性与排除原因"><table class="quick-table"><thead><tr><th scope="col">实验日期 / 样品标识</th><th scope="col">薄膜材料</th><th scope="col">EPC (Å/cycle)</th><th scope="col">审核结果与原因</th></tr></thead><tbody><tr v-for="row in report.rows" :key="row.meta_result_id"><td><RouterLink :to="'/quick?run='+row.meta_run_id">{{row.meta_experiment_date}} · {{row.meta_result_alias||'未命名样品'}}</RouterLink></td><td>{{row.X_material||'未确认'}}</td><td>{{display(row.y_epc_a_per_cycle)}}</td><td><strong>{{row.meta_training_eligible?'可用于当前特征合同的训练':'暂不可训练'}}</strong><ul v-if="reasons(row).length"><li v-for="reason in reasons(row)" :key="reason">{{reason}}</li></ul></td></tr></tbody></table></div>
  <h4>补充建议</h4><ul><li v-for="item in report.recommendations" :key="item">{{item}}</li></ul>
  <details><summary>查看单位、分组与导出版本依据</summary><pre tabindex="0">{{JSON.stringify({units:report.unit_audit,group_split:report.group_split_audit,versions:report.versions,feature_schema_version:report.feature_schema_version},null,2)}}</pre></details>
  <details><summary>查看完整机器可读体检数据</summary><pre tabindex="0">{{JSON.stringify(report,null,2)}}</pre></details>
 </div>
</template>
<style scoped>
.readiness-review h4{margin:24px 0 8px;font-size:16px}.readiness-review li{margin-bottom:6px}.readiness-review .quick-table td{vertical-align:top}.readiness-review .quick-table td:last-child{min-width:260px}.readiness-review .quick-table ul{margin:8px 0;padding-left:18px}
</style>
