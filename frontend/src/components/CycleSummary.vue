<script setup lang="ts">
import {label} from '../experiments/model'
defineProps<{summary:any}>()
</script>
<template><div v-if="summary" data-testid="sample-participation-summary"><p>已确认累计 {{summary.recorded_participations?(summary.recorded_cycles===null?'按体系分别累计':summary.recorded_cycles+' cycles'):'暂无'}}；{{summary.missing_participations}} 次缺少参与依据或循环，未推算。</p><ul v-if="summary.cycle_groups?.length"><li v-for="(g,i) in summary.cycle_groups" :key="i">{{g.label}} · {{label(g.process_mode)}}：{{g.recorded_participations?g.recorded_cycles+' cycles':'暂无已确认循环'}}（{{g.recorded_participations}} 次有依据<span v-if="g.missing_participations">，{{g.missing_participations}} 次未知</span>）</li></ul><p v-if="summary.cycle_groups?.length>1" class="field-hint">不同体系、不同处理模式及体系未确认的执行分别保留，不合计为一个循环数。</p></div></template>
