<script setup lang="ts">
defineProps<{label:string;value:string|number|null|undefined;unit?:string;note?:string}>()
</script>
<template><div class="lab-metric"><span class="lab-metric-label">{{label}}</span><strong>{{value??'未记录'}}<small v-if="value!=null&&unit">{{unit}}</small></strong><span v-if="note" class="lab-metric-note">{{note}}</span></div></template>
<style scoped>.lab-metric{padding:16px 20px;border:1px solid var(--line);border-radius:10px;background:var(--lab-inset-surface,#edf3f6);box-shadow:var(--lab-inset, inset 2px 2px 6px #d4dfe650,inset -2px -2px 6px #fff);display:grid;gap:5px;min-width:0}.lab-metric-label,.lab-metric-note{font-size:12px;color:var(--muted);line-height:1.6}.lab-metric strong{font-size:27px;font-weight:600;font-variant-numeric:tabular-nums;overflow-wrap:anywhere;color:var(--ink)}.lab-metric small{font-size:12px;font-weight:400;margin-left:7px}</style>
