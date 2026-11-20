/* Online flow demo only. No remote audio processing, voice cloning or LLM calls. */
(() => {
  "use strict";
  const DB_NAME = "musiccraft-online-v1";
  const state = {assets:new Map(),plans:new Map(),jobs:new Map(),showcases:new Map()};
  let db = null, volatile = false;
  const id = () => crypto.randomUUID().replaceAll("-", "");
  const now = () => new Date().toISOString();
  const copy = value => JSON.parse(JSON.stringify(value));
  const audioURL = assetId => state.assets.get(assetId)?.url || "";
  const taskNames = {restyle:"风格改编",voice_cover:"音色翻唱"};
  const warnings = ["在线流程演示：输出是浏览器程序合成的占位旋律，未改编原曲、转换声音或调用真实模型。"];
  const STYLE = {pop:["流行","pop"],guofeng:["古风","国风"],classical:["古典","classical"],rock:["摇滚","rock"],jazz:["爵士","jazz"],electronic:["电子","electronic"]};
  const INST = {piano:["钢琴"],guitar:["吉他"],strings:["弦乐"],drums:["鼓"],bass:["贝斯"],guzheng:["古筝"],violin:["小提琴"],flute:["笛"]};

  async function persist(kind,record) {
    const value = {...record}; delete value.url;
    if (!db) return;
    await new Promise((resolve,reject) => {
      const tx = db.transaction(kind,"readwrite"); tx.objectStore(kind).put(value);
      tx.oncomplete=resolve; tx.onerror=()=>reject(new Error("浏览器存储空间不足。请在页面底部清空演示数据后重试。"));
      tx.onabort=tx.onerror;
    });
  }
  async function save(kind,record) {
    await persist(kind,record);
    state[kind].set(record.id,record); return record;
  }
  async function asset(name,blob,role="source",demo=false) {
    const record={id:id(),name,role,demo,size:blob.size,mime:blob.type || "audio/wav",created_at:now(),blob};
    await persist("assets",record);
    record.url=URL.createObjectURL(blob);state.assets.set(record.id,record);
    return record;
  }
  function publicAsset(a) {if (!a) return null;const {blob,...rest}=a;return {...rest};}
  function synthesize(spec={}) {
    const seconds=spec.duration || 10, rate=16000, frames=Math.round(seconds*rate);
    const buffer=new ArrayBuffer(44+frames*2), view=new DataView(buffer);
    const text=(at,value)=>{for(let i=0;i<value.length;i++)view.setUint8(at+i,value.charCodeAt(i));};
    text(0,"RIFF");view.setUint32(4,36+frames*2,true);text(8,"WAVEfmt ");view.setUint32(16,16,true);
    view.setUint16(20,1,true);view.setUint16(22,1,true);view.setUint32(24,rate,true);view.setUint32(28,rate*2,true);
    view.setUint16(32,2,true);view.setUint16(34,16,true);text(36,"data");view.setUint32(40,frames*2,true);
    const notes=spec.style==="guofeng"?[60,62,64,67,69,67,64,62]:[60,64,67,72,69,67,64,62];
    const beat=60/(spec.bpm || 90);const shift=(spec.seed || 42)%notes.length;
    for(let i=0;i<frames;i++) {
      const t=i/rate, step=Math.floor(t/beat), within=t%beat, note=notes[(step+shift)%notes.length];
      const f=440*2**((note-69)/12), env=Math.min(within/.018,1)*Math.exp(-within*4);
      const fade=Math.min(t/.04,(seconds-t)/.1,1);
      const value=(Math.sin(2*Math.PI*f*t)+.22*Math.sin(4*Math.PI*f*t))*.24*env*Math.max(0,fade);
      view.setInt16(44+i*2,Math.round(value*32767),true);
    }
    return new Blob([buffer],{type:"audio/wav"});
  }

  function buildPlan(payload) {
    const prompt=payload.prompt?.trim();if(!prompt || prompt.length>4000)throw new Error("请填写 1–4000 字的音乐要求");
    const controls=payload.controls || {};
    const parent=payload.parent_job_id ? state.jobs.get(payload.parent_job_id) : null;
    if(payload.parent_job_id && parent?.status!=="succeeded")throw new Error("只能基于已完成版本继续编辑");
    const spec={task:"restyle",style:"pop",instruments:["piano"],vocal:"any",theme:"自由创作",lyrics:"",duration:20,bpm:90,seed:42,language:"zh",source_asset_id:"",voice_asset_id:"",clip_start:0,cover_strength:.65,vocal_gain_db:0,...copy(parent?.spec || {}),preserve:[]};
    const p=prompt.toLowerCase();
    spec.task=/翻唱|我的声音|换人声|换音色|音色转换/.test(p)?"voice_cover":"restyle";
    let position=-1;
    for(const [key,words] of Object.entries(STYLE)) for(const word of words)if(p.lastIndexOf(word)>position){position=p.lastIndexOf(word);spec.style=key;}
    const instruments=[],removed=[];
    for(const [key,words] of Object.entries(INST))for(const word of words)if(p.includes(word)){
      if(new RegExp(`(?:不要|不用|去掉|移除|去除)\\s*${word}`).test(p))removed.push(key);else instruments.push(key);
    }
    spec.instruments=(instruments.length?instruments:spec.instruments).filter(x=>!removed.includes(x));
    if(/纯音乐|无人声|不要人声/.test(p))spec.vocal="instrumental";else if(p.includes("女声"))spec.vocal="female";else if(p.includes("男声"))spec.vocal="male";
    const duration=p.match(/(\d+)\s*(?:秒|seconds?\b)/), bpm=p.match(/(?:bpm\s*[:：]?\s*(\d+)|(\d+)\s*bpm)/);
    if(duration)spec.duration=Number(duration[1]);if(bpm)spec.bpm=Number(bpm[1]||bpm[2]);
    for(const theme of ["毕业","爱情","离别","夏天","旅行","思乡","治愈","友情","梦想"])if(p.includes(theme)){spec.theme=theme;break;}
    for(const [key,word] of [["melody","旋律"],["lyrics","歌词"],["accompaniment","伴奏"]])if(new RegExp(`保留(?:原来的|原有|原曲的|原|主)?${word}`).test(p))spec.preserve.push(key);
    const known=Object.keys(spec);
    for(const [key,value] of Object.entries(controls)){
      if(!known.includes(key))throw new Error("不支持的参数："+key);
      if(value!==null && value!=="auto")spec[key]=copy(value);
    }
    if(!taskNames[spec.task])throw new Error("在线演示只开放风格改编和音色翻唱，作曲暂缓");
    if(!Object.hasOwn(STYLE,spec.style) || !["instrumental","female","male","any"].includes(spec.vocal))throw new Error("不支持的风格或人声选项");
    for(const [key,lo,hi,integer] of [["duration",10,40,true],["bpm",40,200,true],["seed",0,2147483647,true],["clip_start",0,3600,false],["cover_strength",0,1,false],["vocal_gain_db",-12,6,false]]){
      if(typeof spec[key]!=="number" || !Number.isFinite(spec[key]) || spec[key]<lo || spec[key]>hi || integer&&!Number.isInteger(spec[key]))throw new Error(`${key} 必须介于 ${lo} 和 ${hi}${integer?" 且为整数":""}`);
    }
    if(!Array.isArray(spec.instruments) || spec.instruments.some(x=>!Object.hasOwn(INST,x)))throw new Error("不支持的乐器");
    if(parent&&!controls.source_asset_id)spec.source_asset_id=parent.output_asset_id;
    if(spec.task==="voice_cover"){spec.preserve=["melody","lyrics","accompaniment"];spec.vocal="any";}
    else if(!spec.preserve.length)spec.preserve=["melody"];
    const blockers=[];
    if(!state.assets.has(spec.source_asset_id))blockers.push("请选择原曲，或点击「载入演示素材」");
    if(spec.task==="voice_cover"&&!state.assets.has(spec.voice_asset_id))blockers.push("请选择声音参考，或载入演示素材");
    if(spec.task==="restyle"&&spec.preserve.includes("accompaniment"))blockers.push("整体改编不能严格锁定原伴奏，请取消保留原伴奏，或选择音色翻唱");
    if(spec.task==="restyle"&&spec.preserve.includes("lyrics")&&!spec.lyrics)blockers.push("保留歌词需要显式粘贴原歌词");
    if(spec.task==="restyle"&&/(?:只|仅).*(?:钢琴|吉他).*(?:换成|替换|改成)/.test(p))blockers.push("单一乐器精确替换尚未实现，可改成整体风格改编");
    if(spec.vocal==="instrumental")spec.lyrics="";
    const steps=[{key:"prepare",label:"演示：检查素材与参数"},{key:spec.task==="restyle"?"restyle":"voice",label:spec.task==="restyle"?"演示路线：参考音频风格改编（不调用模型）":"演示路线：分离 → 转换 → 混音（不调用模型）"},{key:"validate",label:"生成并检查合成占位音"},{key:"save",label:"保存浏览器演示版本"}];
    return {id:id(),created_at:now(),prompt,spec,parent_job_id:parent?.id || null,mode:"demo",planner:"rules",steps,warnings:[...warnings,...(spec.task==="restyle"?["真实 Cover 属于整段重生成，旋律保持是软约束，实际效果待 GPU 验证。"]:[])],blockers,lyrics_origin:"用户输入或继承；演示占位不演唱歌词"};
  }

  async function execute(jobId) {
    let job=state.jobs.get(jobId);
    const step=async(index,status)=>{job.steps[index].status=status;await save("jobs",job);};
    try {
      for(let i=0;i<job.steps.length;i++) {
        if(job.status==="canceling")throw new Error("DEMO_CANCELED");
        job.status="running";job.events.push({at:now(),message:job.steps[i].label});await step(i,"running");
        await new Promise(resolve=>setTimeout(resolve,450));
        if(job.status==="canceling")throw new Error("DEMO_CANCELED");
        await step(i,"succeeded");
      }
      const output=await asset(`DEMO-${job.id.slice(0,8)}.wav`,synthesize(job.spec),"output",true);
      if(job.status==="canceling")throw new Error("DEMO_CANCELED");
      job.status="succeeded";job.output_asset_id=output.id;job.finished_at=now();
      job.metrics={duration_seconds:job.spec.duration,sample_rate:16000,channels:1,musical_quality:"合成占位，不评价模型效果"};
      job.events.push({at:now(),message:"仅生成合成占位旋律；未处理输入歌曲或参考声音。"});
      await save("jobs",job);
    } catch(error) {
      job.status=error.message==="DEMO_CANCELED"?"canceled":"failed";
      job.error=error.message==="DEMO_CANCELED"?"演示任务已取消":error.message;
      for(const step of job.steps)if(step.status==="running")step.status=job.status;
      job.finished_at=now();await save("jobs",job).catch(()=>state.jobs.set(job.id,job));
    }
  }

  async function initialize() {
    try {
      db=await new Promise((resolve,reject)=>{
        const open=indexedDB.open(DB_NAME,1);
        open.onupgradeneeded=()=>{for(const key of Object.keys(state))open.result.createObjectStore(key,{keyPath:"id"});};
        open.onsuccess=()=>resolve(open.result);open.onerror=()=>reject(open.error);
      });
      for(const kind of Object.keys(state)){
        const values=await new Promise((resolve,reject)=>{const tx=db.transaction(kind,"readonly");const read=tx.objectStore(kind).getAll();read.onsuccess=()=>resolve(read.result);read.onerror=()=>reject(read.error);});
        for(const record of values){if(kind==="assets")record.url=URL.createObjectURL(record.blob);state[kind].set(record.id,record);}
      }
    } catch(_) {if(db)db.close();db=null;volatile=true;for(const map of Object.values(state))map.clear();}
    for(const job of state.jobs.values())if(["running","queued","canceling"].includes(job.status)){
      job.status="failed";job.error="页面已刷新，演示任务中断。可恢复请求后重新运行。";await save("jobs",job);
    }
  }
  const ready=initialize();
  async function api(path,payload,options={}) {
    await ready;
    if(path==="/api/config")return {mode:"demo",planner:"rules",generation_ready:false,voice_ready:false,enable_compose:false,version:"0.2-online",storage:volatile?"memory":"indexeddb"};
    if(path==="/api/services")return {mode:"demo",ace:{state:"unconfigured",message:"在线演示未连接 GPU，风格改编仅展示流程"},voice:{state:"unconfigured",message:"在线演示未连接 GPU，参考声音不会被转换"},ffmpeg:false,compose_enabled:false};
    if(path==="/api/assets"&&options.method==="POST"){
      const file=options.body;
      if(!(file instanceof Blob)||!file.size||file.size>32*1024*1024)throw new Error("请选取非空且不超过 32 MB 的音频");
      const name=decodeURIComponent(options.headers?.["X-Filename"]||"audio.wav");
      if(!/\.(wav|mp3|flac|ogg|m4a|webm)$/i.test(name))throw new Error("请选择支持的音频文件格式");
      return publicAsset(await asset(name,file,options.headers?.["X-Asset-Role"]||"source"));
    }
    if(path==="/api/assets")return {assets:[...state.assets.values()].map(publicAsset)};
    if(path==="/api/demo-assets")return {source:publicAsset(await asset("演示旋律.wav",synthesize({duration:20,seed:17}),"source",true)),voice:publicAsset(await asset("参考占位音-非真人.wav",synthesize({duration:3,seed:5}),"voice",true))};
    if(path==="/api/plans"){const plan=buildPlan(payload);await save("plans",plan);return copy(plan);}
    if(path==="/api/jobs"&&payload!==undefined){
      const plan=state.plans.get(payload.plan_id);if(!plan)throw new Error("方案不存在，请重新解析");
      if(plan.blockers.length)throw new Error(plan.blockers.join("；"));
      if(plan.job_id)return copy(state.jobs.get(plan.job_id));
      const job={id:id(),created_at:now(),plan_id:plan.id,parent_job_id:plan.parent_job_id,title:plan.spec.theme+" · "+taskNames[plan.spec.task],prompt:plan.prompt,spec:copy(plan.spec),mode:"demo",planner:"rules",status:"queued",steps:plan.steps.map(x=>({...x,status:"pending"})),events:[],warnings:plan.warnings,output_asset_id:null,error:null,artifacts:{}};
      await save("jobs",job);plan.job_id=job.id;await save("plans",plan);setTimeout(()=>execute(job.id),0);return copy(job);
    }
    if(path==="/api/jobs")return {jobs:copy([...state.jobs.values()].sort((a,b)=>b.created_at.localeCompare(a.created_at)))};
    if(path==="/api/showcases")return {showcases:copy([...state.showcases.values()].sort((a,b)=>b.created_at.localeCompare(a.created_at)))};
    const match=path.match(/^\/api\/jobs\/([a-f0-9]{32})(?:\/(cancel|pin))?$/);
    if(match){
      const job=state.jobs.get(match[1]);if(!job)throw new Error("演示版本不存在");
      if(match[2]==="cancel"&&["queued","running"].includes(job.status)){job.status="canceling";await save("jobs",job);}
      if(match[2]==="pin"){
        if(job.status!=="succeeded")throw new Error("只能收藏已完成版本");
        const record={id:job.id,job_id:job.id,title:job.title,mode:"demo",origin:"流程演示占位",created_at:now()};await save("showcases",record);return copy(record);
      }
      return copy(job);
    }
    throw new Error("在线演示不支持此操作");
  }
  async function clear() {
    await ready;
    if(db){const database=db;await new Promise((resolve,reject)=>{const tx=database.transaction(Object.keys(state),"readwrite");for(const key of Object.keys(state))tx.objectStore(key).clear();tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);});}
    for(const record of state.assets.values())URL.revokeObjectURL(record.url);
    for(const map of Object.values(state))map.clear();
    localStorage.removeItem("musiccraft.currentJob");location.reload();
  }
  window.MusicCraftOnline={api,audioURL,clear};
})();
