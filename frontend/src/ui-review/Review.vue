<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { FlaskConical, ArrowRight, Layers3, SlidersHorizontal, Check, CircleHelp, ArrowUpRight } from 'lucide-vue-next'
import ExperimentResults from '../components/ExperimentResults.vue'
import SampleExperimentHistory from '../components/SampleExperimentHistory.vue'
import SampleResearchReview from '../components/SampleResearchReview.vue'
import ScientificPlot from '../components/ScientificPlot.vue'
import { runs, sample, review, analysis, measurements, result } from './fixture'

const theme = ref('soft')
const baseline = computed(() => theme.value === 'existing')
const advanced = ref(false)
const evidenceOpen = ref(false)
const linkedPreview = ref('')
const router = useRouter()
router.afterEach(to => { if (to.path !== '/') linkedPreview.value = to.path })
const variants = [{ value: 'existing', label: '现有组件原貌' }, { value: 'soft', label: '冷色轻拟物 · 推荐' }, { value: 'warm', label: '暖中性轻拟物' }]
const choices = [
  ['Element Plus', '复用', '表格、按钮、时间轴、展开区、对话框。延续现有操作与焦点行为。'],
  ['ECharts', '复用', '直接使用 ScientificPlot；保留六种图形、坐标规则、导出与数据口径。'],
  ['vue-echarts', '暂不引入', '已有初始化、ResizeObserver、销毁和按需注册，再包一层没有本阶段收益。'],
  ['AG Grid Community', '暂不引入', '当前逐片结果不需要复杂分组或海量单元格；先用现有表格。'],
  ['Vue Flow', '暂不引入', '科研履历为顺序记录，用 Element Plus Timeline 即可；真实分支案例再评估。'],
  ['Vue Data UI', '暂不引入', '现有 ECharts 已覆盖科学图形，避免重复图表引擎与导出路径。'],
  ['VueUse Motion', '暂不引入', '按钮按压用 160ms CSS，支持减少动态效果，无需动画运行时。'],
  ['CountUp.js', '暂不引入', '膜厚与循环数保持静态，便于比较，不让滚动数字干扰读数。'],
  ['PrimeVue Knob', '暂不引入', '本阶段没有旋钮优于选择器的场景；精确工艺参数继续使用既有表单。'],
]
</script>

<template>
<div class="ale-review" :class="`theme-${theme}`">
  <a class="review-skip" href="#summary">跳到实验结果</a>
  <header class="review-brand"><div class="brand-lockup"><span class="review-logo"><FlaskConical :size="21" /></span><strong>ALE <span>实验工作台</span></strong></div><span>局部视觉评审 <b>阶段 0</b></span></header>
  <main class="review-main">
    <div class="review-intro"><div><p class="eyebrow">EXPERIMENT / SAMPLE / DATA</p><h1>更清晰的结果，更轻的操作。</h1><p>保留熟悉的工作台，让实验、样品与证据更容易读懂。</p></div><span class="review-stamp">独立预览<br><strong>尚未应用正式页面</strong></span></div>
    <div class="review-bar"><div class="variant-options" role="group" aria-label="视觉路线"><button v-for="v in variants" :key="v.value" :aria-pressed="theme===v.value" @click="theme=v.value">{{v.label}}</button></div><span>三个局部 · 同一组数据</span></div>
    <p class="demo-note"><CircleHelp :size="16" /> 隔离演示记录，非正式科研数据。现有组件原貌直接加载项目组件；切换样式不改变数值与关联。</p>

    <section id="summary" class="review-section">
      <div class="section-caption"><span>01</span><h2>实验结果摘要</h2><p>把每片样品的结果放在一起</p></div>
      <div v-if="baseline" class="baseline-panel"><ExperimentResults :runs="runs" :writable="false" /></div>
      <article v-else class="instrument-card result-card">
        <header class="card-heading"><div><p class="eyebrow">DEMO-RUN-01 · 2026.01.01</p><h3>氮化硅刻蚀研究</h3><p>研究目标：比较处理前后的膜厚，保留明确配对与逐片参与依据。</p></div><span class="state-badge"><Check :size="14" /> 执行已记录</span></header>
        <div class="result-reading"><div class="reading-label">S01-1 <span>前后均值 · nm</span></div><div class="reading-values"><strong>11.00</strong><ArrowRight :size="22" /><strong>10.00</strong></div><div class="derived-reading"><span>表观减薄量</span><strong>{{result.thinning_nm.toFixed(2)}} <small>nm</small></strong><span>前 − 后 · 每循环 {{result.epc_nm_per_cycle}} nm/cycle</span></div></div>
        <div class="result-table-wrap"><el-table :data="runs[0]!.samples" class="result-table" aria-label="参与样品结果">
          <el-table-column label="样品 / 批次" min-width="145"><template #default="{row}"><a v-if="row.sample_id===1" href="#history" class="sample-link">{{row.sample.sample_code}} <ArrowUpRight :size="14" /></a><button v-else class="sample-link sample-button" @click="evidenceOpen=true">{{row.sample.sample_code}} <ArrowUpRight :size="14" /></button><div class="cell-note">S01 · SiNₓ</div></template></el-table-column>
          <el-table-column label="本片循环 / 节点" min-width="145"><template #default="{row}"><strong>{{row.cycles_confirmed?'100 cycles':'循环未确认'}}</strong><div class="cell-note">{{row.cycles_confirmed?'装载 #1 → 取出 #5':'仅绑定，未确认处理'}}</div></template></el-table-column>
          <el-table-column label="前 → 后均值 / nm" min-width="155"><template #default="{row}">{{row.sample_id===1?'11.00 → 10.00':'未提供演示均值'}}</template></el-table-column>
          <el-table-column label="表观减薄量 / nm" min-width="145"><template #default="{row}"><strong :class="row.sample_id===1?'teal-text':'warning-text'">{{row.sample_id===1?'1.00':'不可直接比较'}}</strong><div class="cell-note">{{row.sample_id===1?'同模型 · 配对已确认':'前后光学模型不同'}}</div></template></el-table-column>
        </el-table></div>
        <footer class="card-foot"><p>表观减薄量 = 前 − 后；正值表示减薄。缺少依据时保留未知。</p><el-button class="raised-action" @click="evidenceOpen=true">查看测量与依据 <ArrowUpRight :size="15" /></el-button></footer>
      </article>
    </section>

    <section id="history" class="review-section">
      <div class="section-caption"><span>02</span><h2>样品科研履历</h2><p>先读处理顺序，再展开条件与测量</p></div>
      <div v-if="baseline" class="baseline-panel"><SampleExperimentHistory :sample="sample" /><SampleResearchReview :sample="sample" :review="review" :writable="false" /></div>
      <article v-else class="instrument-card history-card">
        <header class="card-heading"><div class="sample-heading"><span class="sample-tile"><Layers3 :size="27" /></span><div><h3>S01-1 <span class="material-label">SiNₓ</span></h3><p>批次 S01 · 两次独立执行 · 一组已确认配对</p></div></div><div class="cycle-reading"><strong>100 <small>cycles</small></strong><span>仅演示体系 A 已确认累计</span></div></header>
        <p class="inline-caution">另一次执行缺少时间与逐片参与依据，单独保留，不计入累计。</p>
        <el-timeline class="research-timeline">
          <el-timeline-item timestamp="2026.01.01 · 09:00" placement="top"><div class="timeline-heading"><h4>处理前测量</h4><span>11.00 nm · 4 / 4 点</span></div><p>演示模型 A · 初始阶段</p><details><summary>展开四点测量</summary><div class="point-strip"><span v-for="(v,i) in measurements[0]!.values" :key="i">点 {{i+1}} <strong>{{v.toFixed(2)}} nm</strong></span></div><p>无真实文件挂载；MSE / SEM 未提供。</p></details></el-timeline-item>
          <el-timeline-item timestamp="2026.01.01 · 10:00—11:00" placement="top" type="primary" :hollow="true"><div class="timeline-heading"><h4>氮化硅刻蚀研究</h4><span class="state-badge">100 cycles · 已确认</span></div><p>DEMO-RUN-01 · 装载 #1 → 取出 #5</p><details><summary>查看本次条件与参与依据</summary><p>演示体系 A · 完整循环；记录了装载与取出。</p><p>R1 / R2 温度、N₂ 流量未记录，不代入默认值。</p><p>正式接入后复用已有实验详情链接；本预览不打开正式服务。</p></details></el-timeline-item>
          <el-timeline-item timestamp="2026.01.01 · 12:00" placement="top"><div class="timeline-heading"><h4>处理后测量</h4><span>10.00 nm · 4 / 4 点</span></div><p>演示模型 A · ALE 后 · 表观减薄 1.00 nm</p><details><summary>展开四点测量与来源</summary><div class="point-strip"><span v-for="(v,i) in measurements[1]!.values" :key="i">点 {{i+1}} <strong>{{v.toFixed(2)}} nm</strong></span></div><p>同模型配对；来源为本地演示夹具，不存在可下载原件。</p></details></el-timeline-item>
          <el-timeline-item timestamp="时间未记录 · 按执行记录顺序保留" placement="top" :hollow="true"><div class="timeline-heading"><h4>第二次处理 · 待核对</h4><span class="warning-text">参与依据未确认</span></div><p>DEMO-RUN-02 · 体系与循环未知；未推算累计或每循环变化。</p></el-timeline-item>
        </el-timeline>
        <details class="secondary-details"><summary>操作日志与技术溯源</summary><p>此处在正式页面复用已有事件记录与溯源区。演示未挂载原始日志，不生成接收、创建或装卸事件。</p></details>
      </article>
    </section>

    <section id="chart" class="review-section">
      <div class="section-caption"><span>03</span><h2>科研图表控制区</h2><p>常用选项在外，完整能力按需展开</p></div>
      <article :class="baseline?'baseline-panel':'instrument-card chart-card'">
        <header v-if="!baseline" class="card-heading"><div><p class="eyebrow">S01-1 / 演示模型 A</p><h3>膜厚测点对比</h3><p>四点文件先看摘要；此处仅演示已有图控件，不代表真实坐标 Mapping。</p></div><el-button :aria-expanded="advanced" class="raised-action" @click="advanced=!advanced"><SlidersHorizontal :size="15" /> {{advanced?'收起坐标与分组':'坐标与分组'}}</el-button></header>
        <div :class="{'simplified-plot':!baseline,'advanced-open':advanced}"><ScientificPlot :analysis="analysis" /></div>
        <p v-if="!baseline" class="chart-explanation">保留原有六种图形、PNG 与数据导出。缺少 X/Y、MSE 或 GOF 时，原组件显示无有效值，不补造曲线。</p>
      </article>
    </section>

    <section class="review-decisions"><p class="eyebrow">DESIGN DECISIONS</p><h2>少一套组件，多一分清晰。</h2><p>推荐冷色轻拟物：沿用海军蓝与青绿，仅在读数区和关键按钮增加轻微层次。暖中性色只作为局部候选。</p><div class="decision-grid"><article v-for="c in choices" :key="c[0]"><div><h3>{{c[0]}}</h3><span>{{c[1]}}</span></div><p>{{c[2]}}</p></article></div><p class="decision-boundary">本阶段新增依赖 0 · 生产页面改动 0 · API / 数据库写入 0。预览只改变呈现，不改科研计算；减少点击的收益尚未做正式用户计时。</p></section>
    <footer class="review-footer">ALE 工作台 · 局部评审样板 <span>2026.10.21 / 等待视觉路线确认</span></footer>
  </main>
  <el-dialog v-model="evidenceOpen" title="演示测量与计算依据" width="min(720px, 94vw)"><p>本地演示值：S01-1 前 11 nm、后 10 nm，表观减薄 1 nm，100 个逐片循环，对应 0.01 nm/cycle。S01-2 前后模型不同，不可直接比较。</p><SampleResearchReview :sample="sample" :review="review" :writable="false" /><p>未挂载真实原件，预览不提供原件下载，也不写入任何关联。</p></el-dialog>
  <el-dialog :model-value="!!linkedPreview" title="现有链接的预览边界" width="min(520px, 94vw)" @close="linkedPreview='' "><p>现有组件保留了目标链接：{{linkedPreview}}。此独立预览使用内存路由，不连接正式工作台；正式功能和链接未修改。</p></el-dialog>
</div>
</template>
