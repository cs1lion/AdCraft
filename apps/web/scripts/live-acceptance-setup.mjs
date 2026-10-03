import { mkdir, writeFile } from 'node:fs/promises';
const base='http://127.0.0.1:8000';
const workflowId='adwf_v2_01c0f83902e0e0b8';
const output=new URL('../e2e_output/live-acceptance/',import.meta.url);
await mkdir(output,{recursive:true});
async function request(path,method='GET',body) {
 const headers={'Content-Type':'application/json'};
 if(method!=='GET') {
  const existing=await fetch(`${base}/api/v2/workflows/${workflowId}`);
  headers['If-Match']=existing.headers.get('etag');
 }
 const response=await fetch(base+path,{method,headers,body:body ? JSON.stringify(body):undefined});
 const data=await response.json();
 if(!response.ok) throw new Error(`${method} ${path}: ${response.status} ${JSON.stringify(data).slice(0,1000)}`);
 return data;
}
const blueprint={blueprint_version:'replica-blueprint-v1',duration_seconds:8,aspect:'16:9',replica_goal:'真实Flash两镜头生成到预览验收',whole_piece_reading:'原创最小验收：清晨果园红苹果，然后木桌切面特写。不使用现有用户项目或参考片声音。',shots:[{index:1,start_seconds:0,end_seconds:4,shot_size:'close_up',camera_motion:'slow_push_in',subject_action:'清晨果园，一颗红苹果挂在枝头，露珠沿果皮缓慢滑落。暖色侧光，镜头缓慢推进，写实自然，没有人物。',on_screen_text:'清晨的新鲜',recreate_hint:'单一连续镜头，真实摄影，禁止字幕和品牌文字。'},{index:2,start_seconds:4,end_seconds:8,shot_size:'close_up',camera_motion:'static',subject_action:'红苹果切面放在浅色木桌，果肉细节与微小汁滴，窗边清晨暖光，镜头固定，浅景深，没有人物。',on_screen_text:'每一口，刚刚好',recreate_hint:'单一连续镜头，真实摄影，禁止字幕和品牌文字。'}],systems_captions:'验收后由编排层添加行级字幕，不要求模型生成文字。'};
const workflow=await request(`/api/v2/workflows/${workflowId}`);
let replica=workflow.nodes.find(n=>n.title==='实机验收 · Flash 苹果两镜头');
if(!replica) {
 const result=await request(`/api/v2/workflows/${workflowId}/nodes`,'POST',{node_type:'replica',creative_role:'replica_blueprint',role_contract_version:'ad-media-role-v2',title:'实机验收 · Flash 苹果两镜头',position:{x:180,y:140},structured_content:blueprint});
 replica=result.workflow?.nodes?.find(n=>n.title==='实机验收 · Flash 苹果两镜头') ?? result.node;
 const latest=await request(`/api/v2/workflows/${workflowId}`);
 replica=latest.nodes.find(n=>n.title==='实机验收 · Flash 苹果两镜头');
}
const evidence={workflowId,replicaNodeId:replica?.node_id,modelRef:'volcengine_ark:agnes-video-2.5-flash',blueprint};
await writeFile(new URL('setup.json',output),JSON.stringify(evidence,null,2));
console.log(JSON.stringify({workflowId,replicaNodeId:replica?.node_id,nodeCount:(await request(`/api/v2/workflows/${workflowId}`)).nodes.length},null,2));
