<script setup lang="ts">
import {computed,onBeforeUnmount,onMounted,ref,watch,nextTick} from 'vue'
import LabMetric from './LabMetric.vue'
import {stages} from '../measurements/model'
import * as echarts from 'echarts/core'
import {LineChart,ScatterChart,BarChart} from 'echarts/charts'
import {GridComponent,TooltipComponent,LegendComponent,VisualMapComponent,DataZoomComponent,ToolboxComponent,AriaComponent} from 'echarts/components'
import {CanvasRenderer} from 'echarts/renderers'
echarts.use([LineChart,ScatterChart,BarChart,GridComponent,TooltipComponent,LegendComponent,VisualMapComponent,DataZoomComponent,ToolboxComponent,AriaComponent,CanvasRenderer])
const props=defineProps<{analysis:any}>()
const mode=ref('scatter'),metric=ref('thickness_nm'),axis=ref('point_no'),mappingIndex=ref(0),group=ref('source')
const showPlot=ref(false)
const compact=computed(()=>series.value.length===1&&series.value[0].raw_count<=8)
const chartShown=computed(()=>!compact.value||showPlot.value)
const number=(v:any)=>v==null?'未记录':Number(v).toLocaleString('zh-CN',{maximumSignificantDigits:8})
const el=ref<HTMLElement|null>(null)
let chart:echarts.ECharts|undefined,observer:ResizeObserver|undefined
const fields:Record<string,string>={thickness_nm:'厚度 (nm)',mse:'MSE（拟合质量，无量纲）',gof:'GOF（无量纲）',point_no:'点号',x_mm:'X (mm)',y_mm:'Y (mm)',cumulative_cycles:'已记录累计循环数',r1_temp_c:'已记录 R1 温度 (°C)',full_ale_cycles:'已记录完整 ALE 循环数',recorded_total_cycles:'流程显式总循环数',r2_temp_c:'已记录 R2 温度 (°C)'}
const series=computed(()=>props.analysis?.series??[])
const actualCount=computed(()=>series.value.reduce((n:number,s:any)=>n+s.included_count,0))
const excludedCount=computed(()=>series.value.reduce((n:number,s:any)=>n+s.excluded_count,0))
const mapping=computed(()=>series.value[mappingIndex.value]??series.value[0])
const finite=(v:any)=>v!==null&&v!==undefined&&v!==''&&Number.isFinite(Number(v))
const conditionAxes=['recorded_total_cycles','cumulative_cycles','full_ale_cycles','r1_temp_c','r2_temp_c']
const trendAxis=ref('recorded_total_cycles')
const plotData=ref<any[]>([])
const rowX=(s:any,p:any)=>axis.value==='cumulative_cycles'?s.source.cumulative_cycles:axis.value==='r1_temp_c'||axis.value==='full_ale_cycles'?s.source.recorded_conditions?.[axis.value]:p[axis.value]
const groupedName=(s:any)=>group.value==='stage'?`阶段 ${stages[s.source.stage]??s.source.stage??'未知'}`:group.value==='model'?`模型 ${s.source.optical_model_id??'未知'}`:s.source.label
const trendName=(s:any)=>`样品 ${s.source.sample_id??'未知 · '+s.source.label} · 模型 ${s.source.optical_model_id??'未知 · '+s.source.label}${group.value==='stage'?' · 阶段 '+(s.source.stage??'未知'):''}${group.value==='source'?' · '+s.source.label:''}`
const notice=computed(()=>mode.value==='trend'?'每次测量一个纳入测点均值；按已记录横轴排序，按样品和模型隔离，未知条件不绘制。流程总循环数、完整 ALE 循环数和累计循环数分别读取，不相乘。':mode.value==='mapping'?'仅显示文件中的真实 X/Y 坐标，颜色表示所选指标。插值不可用。':mode.value==='distribution'?'直方图仅统计本次纳入的真实测点；分箱数量最多 12。':mode.value==='line'?'折线按所选真实坐标排序；点号仅表示明确选择的测点顺序。排除点或缺值保留断线。':'空间测点散点；每个点均来自原始记录。')
const renderedCount=ref(0)
function draw(){
 if(!el.value||!chartShown.value||!el.value.clientWidth)return
 if(!chart)chart=echarts.init(el.value)
 if(!series.value.length){chart.clear();renderedCount.value=0;plotData.value=[];return}
 let options:any={animation:false,aria:{enabled:true},color:['#087f8c','#bc6a37','#6679ad','#64885c','#a65c78'],textStyle:{fontFamily:'Segoe UI, Microsoft YaHei, sans-serif',color:'#294355'},tooltip:{trigger:'item',renderMode:'richText',backgroundColor:'#102438',borderWidth:0,textStyle:{color:'#f4fafb'}},legend:{type:'scroll',top:5,left:12,right:12,textStyle:{color:'#425e70',fontSize:12}},grid:{left:65,right:30,top:70,bottom:95},dataZoom:[{type:'inside'},{type:'slider',bottom:10,height:18}],xAxis:{type:'value',name:fields[axis.value],nameLocation:'middle',nameGap:38},yAxis:{type:'value',name:fields[metric.value],scale:true},series:[]}
 options.xAxis.axisLine={lineStyle:{color:'#718998'}};options.xAxis.axisLabel={hideOverlap:true,color:'#425e70'};options.xAxis.splitLine={lineStyle:{color:'#e2eaef'}}
 options.yAxis.axisLabel={color:'#425e70'};options.yAxis.splitLine={lineStyle:{color:'#e2eaef'}}
 let count=0
 if(mode.value==='mapping'){
  const data=(mapping.value?.points??[]).filter((p:any)=>p.included&&finite(p.x_mm)&&finite(p.y_mm)&&finite(p[metric.value])).map((p:any)=>({symbol:p.is_outlier?'diamond':'circle',value:[Number(p.x_mm),Number(p.y_mm),Number(p[metric.value])],name:`点 ${p.point_no} · ${p[metric.value]} · ${p.is_outlier?'异常标记':'原始测点'}`}))
  count=data.length;const vals=data.map((d:any)=>d.value[2]);let min=Math.min(...vals),max=Math.max(...vals)
  if(min===max){min-=.5;max+=.5}
  options={...options,dataZoom:[],grid:{left:75,right:100,top:65,bottom:60},xAxis:{type:'value',name:'X (mm)',scale:true,nameLocation:'middle',nameGap:30},yAxis:{type:'value',name:'Y (mm)',scale:true},visualMap:data.length?{min,max,dimension:2,orient:'vertical',right:0,top:70,calculable:true,inRange:{color:['#e6f2f1','#73b8bb','#075f6c']},text:[fields[metric.value],'']}:undefined,series:[{name:mapping.value?.source.label,type:'scatter',symbolSize:13,data}]}
 }else if(mode.value==='distribution'){
  options.xAxis={type:'category',name:fields[metric.value],nameLocation:'middle',nameGap:40};options.yAxis={type:'value',name:'真实测点数',minInterval:1};options.dataZoom=[]
  const values=series.value.flatMap((s:any)=>s.points.filter((p:any)=>p.included&&finite(p[metric.value])).map((p:any)=>Number(p[metric.value])))
  if(values.length){const min=Math.min(...values),max=Math.max(...values),bins=min===max?1:Math.min(12,Math.ceil(Math.sqrt(values.length))),width=(max-min)/bins||1
   options.xAxis.data=Array.from({length:bins},(_,i)=>`${(min+i*width).toPrecision(5)}–${(min+(i+1)*width).toPrecision(5)}`)
   const grouped=new Map<string,number[]>()
   series.value.forEach((s:any)=>{const name=groupedName(s),counts=grouped.get(name)??new Array(bins).fill(0);s.points.forEach((p:any)=>{if(p.included&&finite(p[metric.value])){counts[Math.min(bins-1,Math.max(0,Math.floor((Number(p[metric.value])-min)/width)))]++;count++}});grouped.set(name,counts)})
   options.series=Array.from(grouped,([name,data])=>({type:'bar',name,data}))
  }
 }else if(mode.value==='bar'){
  options.xAxis={type:'category',data:series.value.map((s:any)=>`${groupedName(s)} · ${s.source.label}`),axisLabel:{hideOverlap:true},name:'来源 / 分组'};options.dataZoom=[]
  options.series=[{type:'bar',name:`${fields[metric.value]} 均值`,data:series.value.map((s:any)=>{const m=s.statistics[metric.value]?.mean;if(finite(m)){count++;return Number(m)}return null})}]
 }else if(mode.value==='trend'){
  options.xAxis.name=fields[trendAxis.value]
  const grouped=new Map<string,any[]>()
  series.value.forEach((s:any)=>{const x=trendAxis.value==='cumulative_cycles'?s.source.cumulative_cycles:s.source.recorded_conditions?.[trendAxis.value],y=s.statistics[metric.value]?.mean
   if(!finite(x))return
   const name=trendName(s),data=grouped.get(name)??[]
   data.push({value:[Number(x),finite(y)?Number(y):null],name:`${s.source.label} · 纳入 ${s.included_count} 点均值 ${y??'无'}`});grouped.set(name,data);if(finite(y))count++
  })
  options.series=Array.from(grouped,([name,data])=>({name,type:'line',connectNulls:false,showSymbol:true,data:data.sort((a:any,b:any)=>a.value[0]-b.value[0])}))
 }else{
  const grouped=new Map<string,any[]>()
  series.value.forEach((s:any)=>{
   const name=groupedName(s),data=grouped.get(name)??[]
   if(data.length&&mode.value==='line')data.push({value:[null,null]})
   const segments:any[][]=[[]]
   s.points.forEach((p:any)=>{if(finite(rowX(s,p)))segments[segments.length-1]!.push(p);else segments.push([])})
   const points=segments.flatMap((part:any[],i:number)=>[...(i?[null]:[]),...part.sort((a:any,b:any)=>Number(rowX(s,a))-Number(rowX(s,b)))])
   points.forEach((p:any)=>{if(p===null){if(mode.value==='line')data.push({value:[null,null]});return}const valid=p.included&&finite(p[metric.value]);if(valid)count++
    if(valid||mode.value==='line')data.push({value:[Number(rowX(s,p)),valid?Number(p[metric.value]):null],symbol:p.is_outlier?'diamond':'circle',symbolSize:p.is_outlier?11:7,name:`${s.source.label} · 点 ${p.point_no} · ${p[metric.value]} · ${p.is_outlier?'异常标记 · ':''}${p.source_sheet??''} ${p.source_cell??''}`})
   });grouped.set(name,data)
  })
  options.series=Array.from(grouped,([name,data])=>({name,type:mode.value==='line'?'line':'scatter',showSymbol:true,connectNulls:false,data}))
 }
 plotData.value=options.series.map((s:any)=>({name:s.name,type:s.type,data:s.data}))
 renderedCount.value=count
 chart.setOption(options,{notMerge:true})
}
function saveImage(){if(!chart)return;const a=document.createElement('a');a.download='scientific-analysis.png';a.href=chart.getDataURL({type:'png',pixelRatio:2,backgroundColor:'#ffffff'});a.click()}
function download(data:any,name:string){const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
onMounted(async()=>{await nextTick();if(el.value){observer=new ResizeObserver(()=>{chart?.resize();draw()});observer.observe(el.value);draw()}})
watch(()=>props.analysis,()=>{mappingIndex.value=0;showPlot.value=false;nextTick(draw)},{deep:false})
watch([mode,metric,axis,trendAxis,mappingIndex,group,chartShown],()=>nextTick(draw))
onBeforeUnmount(()=>{observer?.disconnect();chart?.dispose()})
</script>
<template>
<section class="scientific-plot panel panel-body" data-testid="scientific-plot">
<header class="plot-heading"><div><p class="plot-kicker">SCIENTIFIC DATA</p><h2>{{ compact?'测量摘要':'测量对比与分布' }}</h2><p class="field-hint">{{series.length}} 组来源 · 数据来自当前服务器计算结果，保留原始记录与来源。</p></div><el-button v-if="compact" :aria-expanded="showPlot" @click="showPlot=!showPlot">{{showPlot?'收起图表':'展开图表'}}</el-button></header>
<div v-if="compact" data-testid="compact-point-summary" class="compact-summary">
<div class="plot-metrics"><LabMetric label="纳入测点平均膜厚" :value="number(series[0].statistics.thickness_nm?.mean)" unit="nm"/><LabMetric label="纳入 / 原始测点" :value="`${series[0].included_count} / ${series[0].raw_count}`" note="异常标记与原值保留"/><LabMetric v-if="series[0].statistics.mse?.mean!=null" label="MSE（拟合质量）" :value="number(series[0].statistics.mse.mean)" note="不作为膜厚误差棒"/></div>
<el-table :data="series[0].points" aria-label="少点测量摘要"><el-table-column prop="point_no" label="测点" min-width="80"/><el-table-column prop="thickness_nm" label="膜厚 / nm" min-width="125"/><el-table-column v-if="series[0].points.some((p:any)=>p.mse!=null)" prop="mse" label="MSE" min-width="100"/><el-table-column label="状态" min-width="130"><template #default="{row}">{{row.included?'纳入':'已排除'}}{{row.is_outlier?' · 异常标记':''}}</template></el-table-column></el-table>
</div>
<div v-show="chartShown" class="plot-controls lab-data-toolbar"><label>图形<select v-model="mode" aria-label="分析图形"><option value="scatter">原始散点</option><option value="line">空间坐标 / 明确点号折线</option><option value="trend">测量均值工艺趋势</option><option value="bar">均值柱状</option><option value="distribution">分布直方图</option><option value="mapping">真实坐标 Mapping</option></select></label><label>纵轴 / 颜色<select v-model="metric" aria-label="分析指标"><option value="thickness_nm">厚度 (nm)</option><option value="mse">MSE（拟合质量）</option><option value="gof">GOF</option></select></label></div>
<details class="plot-advanced"><summary>坐标、分组与导出</summary><div class="plot-controls">
<label v-if="['line','scatter'].includes(mode)">横轴<select v-model="axis" aria-label="分析横轴"><option v-for="key in ['point_no','x_mm','y_mm']" :key="key" :value="key">{{fields[key]}}</option></select></label>
<label v-if="mode==='trend'">工艺横轴<select v-model="trendAxis" aria-label="趋势横轴"><option v-for="key in conditionAxes" :key="key" :value="key">{{fields[key]}}</option></select></label>
<label v-if="mode!=='mapping'">图例分组<select v-model="group" aria-label="图例分组"><option value="source">来源</option><option value="stage">按阶段合组</option><option value="model">按模型合组</option></select></label><label v-else>来源<select v-model="mappingIndex" aria-label="Mapping 来源"><option v-for="(s,i) in series" :key="i" :value="i">{{s.source.label}}</option></select></label>
<el-button :disabled="!chartShown||!renderedCount" @click="saveImage">导出图像 PNG</el-button><el-button @click="download(analysis,'scientific-analysis.json')">导出数据与计算记录</el-button></div><p class="field-hint">{{notice}} MSE 是拟合质量，不是膜厚不确定度。统计以服务器 50 位 Decimal 结果为准；图形使用数值近似显示。</p></details>
<p class="field-hint" data-testid="plot-source-count">本次纳入 {{actualCount}} 个原始测点，排除 {{excludedCount}} 个；<template v-if="chartShown">当前图形显示 {{renderedCount}} {{['bar','trend'].includes(mode)?'组均值':'个测点'}}</template><template v-else>少点测量默认显示摘要，需要时展开图表。</template></p>
<div v-show="chartShown" ref="el" class="plot-canvas" role="img" :aria-label="`${fields[metric]}科学图表`" data-testid="echarts-canvas" :data-rendered-count="renderedCount" :data-plot-series="JSON.stringify(plotData)"></div>
<p v-if="chartShown&&!renderedCount" class="danger-text" role="status">所选横轴 / 指标没有已记录的有效值，请切换指标或横轴。系统没有补造数据。</p>
<p v-if="chartShown" class="field-hint">异常标记以菱形显示，原值保留。不同模型的原始测点可并列查看，不代表跨模型差值可信。</p>
</section>
</template>
<style scoped>
.scientific-plot{margin:18px 0;min-width:0;background:#f8fafc;border-radius:14px;box-shadow:5px 5px 18px #c7d3dc45,-4px -4px 14px #fff}.plot-heading{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;margin-bottom:20px}.plot-heading h2{font-size:20px;margin:0}.plot-kicker{font-size:10px;letter-spacing:1.8px;color:#537282;margin:0 0 7px}.plot-controls{display:flex;flex-wrap:wrap;align-items:flex-end;gap:12px}.lab-data-toolbar{padding:14px 16px;background:#edf3f6;border:1px solid var(--line);border-radius:9px;box-shadow:inset 2px 2px 6px #d4dfe650,inset -2px -2px 6px #fff}.plot-controls label{display:grid;gap:6px;font-size:13px;color:var(--muted)}select{max-width:280px;border:1px solid #aebfca;background:#fff;color:#24394d;border-radius:6px;padding:8px;min-height:40px}.plot-canvas{width:100%;height:430px;min-width:0}.plot-controls select:focus-visible{outline:3px solid #087f8c;outline-offset:2px}.plot-advanced{margin:14px 0}.plot-advanced>summary{cursor:pointer;color:#076c78;min-height:40px;padding:8px 0;font-weight:600;font-size:13px}.plot-advanced .plot-controls{padding:12px 0}.plot-metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-bottom:18px}.compact-summary{margin-bottom:16px}.plot-controls .el-button{min-height:40px;margin-left:0}@media(max-width:640px){.scientific-plot{padding:16px}.plot-canvas{height:360px}.plot-heading{flex-wrap:wrap}.plot-controls label,.plot-controls select,.plot-controls .el-button{width:100%;max-width:none}.plot-metrics{grid-template-columns:minmax(0,1fr)}}
</style>
