import {api} from '../api'

// Suggestions use visible records, including retired codes. The existing global
// UNIQUE index remains authoritative when another request creates concurrently.
export async function usedSampleCodes(batchId:number, prefix:string){
  const used=new Set<string>()
  for(let page=1;;page++){
    const r=await api<any[]>('/samples',{query:{batch_id:batchId,keyword:prefix,include_voided:true,include_archived:true,page,size:200}})
    r.data.forEach(s=>used.add(s.sample_code.toLocaleLowerCase()))
    if(!r.meta?.has_next)break
  }
  return used
}
export function suggestedCodes(prefix:string,count:number,used:Set<string>,start=1){
  const result:string[]=[]
  for(let n=start;result.length<count;n++){
    const code=`${prefix}-${n}`
    if(!used.has(code.toLocaleLowerCase()))result.push(code)
  }
  return result
}
