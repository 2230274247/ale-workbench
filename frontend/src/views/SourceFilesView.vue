<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PageHeading from '../components/PageHeading.vue'
import FormSection from '../components/FormSection.vue'
import StatePanel from '../components/StatePanel.vue'
import { api, downloadSource, errorText } from '../api'
import { type SourceRow, positiveId, text, json, time } from '../measurements/model'
const route=useRoute(),router=useRouter()
const filter=reactive({sample_id:''}),appliedSample=ref<number>(),page=ref(1),size=ref(20),total=ref(0),rows=ref<SourceRow[]>([]),loading=ref(false),listError=ref('')
const selected=ref<SourceRow|null>(null),detailLoading=ref(false),detailError=ref(''),idInput=ref(''),requestedId=ref<number>()
const downloading=ref(false),downloadError=ref(''),lastDownload=ref<{id:number;name?:string}>()
let listSeq=0,detailSeq=0
async function load(){const n=++listSeq;loading.value=true;listError.value='';try{const r=await api<SourceRow[]>('/source-files',{query:{sample_id:appliedSample.value,page:page.value,size:size.value}});if(n===listSeq){rows.value=r.data;total.value=r.meta?.total??r.data.length}}catch(e){if(n===listSeq)listError.value=errorText(e)}finally{if(n===listSeq)loading.value=false}}
async function search(){try{appliedSample.value=positiveId(filter.sample_id,'样品 ID');page.value=1;await load()}catch(e){listError.value=errorText(e)}}
async function detail(id:number){const n=++detailSeq;requestedId.value=id;detailLoading.value=true;detailError.value='';selected.value=null;try{const r=await api<SourceRow>(`/source-files/${id}`);if(n===detailSeq)selected.value=r.data}catch(e){if(n===detailSeq)detailError.value=errorText(e)}finally{if(n===detailSeq)detailLoading.value=false}}
async function choose(id:number){if(detailLoading.value)return;if(String(route.query.id??route.query.file_id)===String(id)){await detail(id);return}await router.push({path:route.path,query:{...route.query,id:String(id),file_id:undefined}})}
async function openId(){try{const id=positiveId(idInput.value,'源文件 ID');if(!id)throw new Error('请填写源文件 ID');await choose(id)}catch(e){detailError.value=errorText(e)}}
async function download(id:number,name?:string){if(downloading.value)return;downloading.value=true;downloadError.value='';lastDownload.value={id,name};try{await downloadSource(id,name)}catch(e){downloadError.value=errorText(e)}finally{downloading.value=false}}
async function entry(){filter.sample_id=String(route.query.sample_id??'');await search();try{const id=positiveId(route.query.id??route.query.file_id,'源文件 ID');if(id){idInput.value=String(id);await detail(id)}else{detailSeq++;selected.value=null;requestedId.value=undefined;detailError.value='';detailLoading.value=false}}catch(e){detailError.value=errorText(e)}}
watch(()=>route.fullPath,entry)
onMounted(entry)
onBeforeUnmount(()=>{listSeq++;detailSeq++})
</script>
<template>
<div class="source-files-workspace" data-testid="source-files-view">
  <PageHeading title="原始文件" description="按样品追溯原始文件、SHA-256 与可见上传记录。下载内容由服务端读取并校验完整性。"><template #actions><el-button :loading="loading" @click="load" data-testid="source-files-refresh">刷新列表</el-button></template></PageHeading>
  <p class="readonly-note" data-testid="source-parse-status-unavailable">解析状态：接口未提供（parse_status）。文件出现在列表、存在测量或上传记录，均不能据此断言“解析成功”。此页仅展示接口实际返回的数据。</p>
  <StatePanel v-if="downloadError" title="原始文件下载失败" :description="downloadError" tone="error" data-testid="source-download-error"><el-button v-if="lastDownload" :disabled="downloading" @click="download(lastDownload.id,lastDownload.name)" data-testid="source-download-retry">重试下载</el-button></StatePanel>
  <section class="panel">
    <form class="toolbar" @submit.prevent="search"><el-input v-model="filter.sample_id" class="search-input" placeholder="样品 ID（空为全部）" aria-label="按样品 ID 筛选" clearable data-testid="source-sample-filter" /><el-button native-type="submit" :loading="loading" data-testid="source-filter-submit">筛选</el-button><span class="field-hint">按服务端可见范围查询，文件名取自可见上传记录。</span></form>
    <StatePanel v-if="listError" title="原始文件列表加载失败" :description="listError" tone="error"><el-button @click="load" data-testid="source-list-retry">重试列表</el-button></StatePanel>
    <div v-else class="table-wrap" v-loading="loading"><el-table :data="rows" empty-text="没有符合条件的原始文件" data-testid="source-files-table">
      <el-table-column label="文件" min-width="230"><template #default="{row}"><el-button link type="primary" :disabled="detailLoading" @click="choose(row.file_id)" :data-testid="`source-open-${row.file_id}`">{{ row.file_name }}</el-button><div class="table-sub">#{{ row.file_id }} · {{ text(row.file_ext) }}</div></template></el-table-column>
      <el-table-column label="SHA-256" min-width="260"><template #default="{row}"><code class="sha">{{ row.file_sha256 }}</code></template></el-table-column>
      <el-table-column label="大小（bytes）" min-width="125"><template #default="{row}">{{ text(row.size_bytes) }}</template></el-table-column>
      <el-table-column label="文件属性" min-width="130"><template #default="{row}"><el-tag :type="row.is_readonly?'info':'warning'">{{ row.is_readonly?'只读':'接口标记非只读' }}</el-tag></template></el-table-column>
      <el-table-column label="登记时间" min-width="180"><template #default="{row}">{{ time(row.created_at) }}</template></el-table-column>
      <el-table-column label="操作" width="140" fixed="right"><template #default="{row}"><el-button link type="primary" :disabled="downloading" @click="download(row.file_id,row.file_name)" :data-testid="`source-download-${row.file_id}`">下载原始文件</el-button></template></el-table-column>
    </el-table></div>
    <div class="pagination"><span>共 {{ total }} 个文件 · SHA-256 标识原始内容</span><el-pagination v-model:current-page="page" v-model:page-size="size" :total="total" :page-sizes="[10,20,50,100]" layout="prev,pager,next,sizes" :disabled="loading" @current-change="load" @size-change="page=1;load()" data-testid="source-files-pagination" /></div>
  </section>
  <section class="panel source-detail">
    <form class="toolbar" @submit.prevent="openId"><el-input v-model="idInput" class="search-input" placeholder="通过源文件 ID 读取详情" aria-label="源文件详情 ID" data-testid="source-id" /><el-button native-type="submit" :disabled="detailLoading" data-testid="source-load-id">读取详情</el-button><el-button v-if="requestedId" :disabled="detailLoading" @click="detail(requestedId)" data-testid="source-detail-refresh">刷新详情</el-button></form>
    <StatePanel v-if="detailError" title="文件详情加载失败" :description="detailError" tone="error"><el-button v-if="requestedId" :disabled="detailLoading" @click="detail(requestedId)" data-testid="source-detail-retry">重试详情</el-button></StatePanel>
    <div v-else-if="detailLoading" class="panel-body"><el-skeleton :rows="5" animated /></div>
    <div v-else-if="selected" class="panel-body" data-testid="source-detail">
      <div class="detail-title"><h2>{{ selected.file_name }}</h2><el-tag>源文件 #{{ selected.file_id }}</el-tag><el-button type="primary" :disabled="downloading" :loading="downloading" @click="download(selected.file_id,selected.file_name)" data-testid="source-detail-download">下载原始文件</el-button></div>
      <dl class="detail-grid"><div class="span-2"><dt>SHA-256（内容标识）</dt><dd class="sha" data-testid="source-sha256">{{ selected.file_sha256 }}</dd></div><div><dt>文件大小（bytes） / 扩展名</dt><dd>{{ text(selected.size_bytes) }} / {{ text(selected.file_ext) }}</dd></div><div><dt>只读标记 / 登记时间</dt><dd>{{ selected.is_readonly?'只读':'接口标记非只读' }} / {{ time(selected.created_at) }}</dd></div><div class="span-2"><dt>存储键</dt><dd>{{ text(selected.storage_key) }}</dd></div><div><dt>解析状态</dt><dd>接口未提供</dd></div></dl>
      <FormSection title="可见上传记录（occurrences）" description="同一内容可以来自多个导入条目。这里只展示当前用户可见记录；空列表不代表没有其他上传。">
        <el-table :data="selected.occurrences??[]" empty-text="没有可见的上传记录" data-testid="source-occurrences">
          <el-table-column prop="occurrence_id" label="记录 ID" width="100" /><el-table-column prop="filename" label="上传文件名" min-width="210" />
          <el-table-column label="样品" min-width="115"><template #default="{row}"><router-link v-if="row.sample_id" :to="{path:'/samples',query:{sample_id:row.sample_id}}">样品 #{{ row.sample_id }}</router-link><span v-else>未关联</span></template></el-table-column>
          <el-table-column label="导入条目" min-width="220"><template #default="{row}"><span>import_item #{{ row.import_item_id }}</span><div class="table-sub">接口未提供 job_id，无法定位导入任务。</div></template></el-table-column>
          <el-table-column prop="owner_user_id" label="上传人 ID" width="110" /><el-table-column label="登记时间" min-width="180"><template #default="{row}">{{ time(row.created_at) }}</template></el-table-column><el-table-column label="备注" min-width="200"><template #default="{row}">{{ text(row.notes) }}</template></el-table-column>
        </el-table>
      </FormSection>
      <FormSection title="接口原始记录" description="保留实际返回字段，便于核对内容哈希与来源。"><details data-testid="source-raw-json"><summary>文件详情与 occurrences 原始 JSON</summary><pre class="raw-json">{{ json(selected) }}</pre></details></FormSection>
    </div>
    <StatePanel v-else title="选择一个原始文件" description="点击文件名或填写源文件 ID，查看 SHA-256、可见上传记录和原始接口数据。" />
  </section>
</div>
</template>
<style scoped>
.source-detail{margin-top:24px}.sha{font-family:Consolas,monospace;overflow-wrap:anywhere;user-select:all}.source-files-workspace .form-section-block{margin-top:24px}.source-files-workspace summary{color:var(--teal);cursor:pointer;font-size:13px}.raw-json{max-height:480px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;padding:16px;background:var(--soft);border:1px solid var(--line);border-radius:6px;font-size:12px}.source-files-workspace>.state-panel{margin-bottom:20px}@media(max-width:760px){.source-files-workspace .detail-grid{grid-template-columns:1fr}.source-files-workspace .pagination{overflow:auto}}
</style>
