"use strict";

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const escapeHTML = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const labels = {compose:"灵感作曲",restyle:"风格改编",voice_cover:"音色翻唱",pop:"流行",guofeng:"古风",classical:"古典",rock:"摇滚",jazz:"爵士",electronic:"电子",piano:"钢琴",guitar:"木吉他",strings:"弦乐",drums:"鼓",bass:"贝斯",guzheng:"古筝",violin:"小提琴",flute:"笛子",instrumental:"纯音乐",female:"女声",male:"男声",any:"不限人声",melody:"主旋律",lyrics:"歌词",accompaniment:"原伴奏",queued:"排队中",running:"处理中",succeeded:"已完成",failed:"失败",canceling:"正在取消",canceled:"已取消"};
const state = {task:"restyle",config:null,plan:null,planRevision:0,revision:0,parent:null,source:null,voice:null,jobs:[],currentJob:null,showcases:[],polling:false,uploading:0,planning:false,submitting:false,renderKey:"",recorder:null,recordTimer:null};
let toastTimer;

function toast(message, error = false) {
  const el = $("#toast");
  el.textContent = message; el.classList.toggle("error", error); el.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => {el.hidden = true;}, error ? 6500 : 3500);
}

async function api(path, payload, options = {}) {
  const headers = {"X-MusicCraft":"1", ...options.headers};
  if (payload !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(path, {...options, headers, ...(payload !== undefined ? {method:"POST",body:JSON.stringify(payload)} : {})});
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || `请求失败 (${response.status})`);
  return value;
}

function view(name) {
  ["studio","library","showcase","architecture"].forEach((key) => {
    $(`#${key}View`).hidden = key !== name;
    $(`[data-view="${key}"]`).classList.toggle("active", key === name);
  });
  $("#viewLabel").textContent = {studio:"STUDIO",library:"LIBRARY",showcase:"SHOWCASE",architecture:"ARCHITECTURE"}[name];
  window.scrollTo({top:0,behavior:"smooth"});
}

function dirty() {
  state.revision++;
  if (state.plan) {
    const button = $("#runButton");
    if (button) {button.disabled = true; button.textContent = "要求已修改，请重新解析";}
    $("#resultStatus").textContent = "方案待更新";
  }
}

function setTask(task, markDirty = true) {
  if (task === "compose" && !state.config?.enable_compose) return;
  state.task = task;
  $$(".generation-only").forEach((el) => {el.hidden = task === "voice_cover";});
  $("#coverControl").hidden = task !== "restyle";
  $("#gainControl").hidden = task !== "voice_cover";
  $(".clip-controls").hidden = task === "compose";
  $$(".task-tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.task === task);
    button.setAttribute("aria-selected", String(button.dataset.task === task));
  });
  $("#assetSection").hidden = task === "compose";
  $("#voiceBox").hidden = task !== "voice_cover";
  $("#demoAssets").hidden = state.config?.mode !== "demo";
  const placeholders = {
    compose:"写一段关于毕业的古风纯音乐，以钢琴为主，像夏日晚风一样温柔……",
    restyle:"保留这段歌曲的主旋律，改成温暖的木吉他流行风格……",
    voice_cover:"保留原来的伴奏和旋律，把歌声换成我上传的声音……"
  };
  $("#prompt").placeholder = placeholders[task];
  if (markDirty) dirty();
}

function setAsset(role, asset) {
  state[role] = asset;
  $(`[data-remove="${role}"]`).hidden = false;
  $(`#${role}Status`).textContent = `${asset.name}${asset.demo ? " · 演示素材" : ""}`;
  const player = $(`#${role}Preview`);
  player.src = asset.url; player.hidden = false;
  dirty();
}

async function upload(role, file) {
  if (!file) return;
  if (file.size > 32 * 1024 * 1024 || file.size === 0) return toast("请上传非空且不超过 32 MB 的音频", true);
  state.uploading++;
  dirty();
  $("#planButton").disabled = true;
  $(`#${role}Status`).textContent = "上传中…";
  try {
    const asset = await api("/api/assets", undefined, {method:"POST",body:file,headers:{"Content-Type":"application/octet-stream","X-Filename":encodeURIComponent(file.name),"X-Asset-Role":role}});
    setAsset(role, asset); toast("音频已加入创作素材");
  } catch (error) {
    $(`#${role}Status`).textContent = state[role]?.name || "上传失败，请重试";
    toast(error.message, true);
  } finally {
    state.uploading--; $("#planButton").disabled = state.uploading > 0 || state.planning;
  }
}

function controls() {
  const result = {task:state.task,clip_start:Number($("#clip_start").value || 0)};
  if (state.task === "restyle") result.cover_strength = Number($("#cover_strength").value);
  if (state.task === "voice_cover") result.vocal_gain_db = Number($("#vocal_gain_db").value || 0);
  for (const name of (state.task === "voice_cover" ? [] : ["style","vocal"])) if ($(`#${name}`).value !== "auto") result[name] = $(`#${name}`).value;
  if ($("#duration").value !== "auto") result.duration = Number($("#duration").value);
  if ($("#bpm").value) result.bpm = Number($("#bpm").value);
  if ($("#seed").value) result.seed = Number($("#seed").value);
  if ($("#theme").value.trim()) result.theme = $("#theme").value.trim();
  if ($("#lyrics").value.trim()) result.lyrics = $("#lyrics").value.trim();
  const instruments = $$("input[name=instrument]:checked").map((input) => input.value);
  const preserve = $$("input[name=preserve]:checked").map((input) => input.value);
  if (instruments.length && state.task !== "voice_cover") result.instruments = instruments;
  if (preserve.length && state.task !== "voice_cover") result.preserve = preserve;
  if (state.source) result.source_asset_id = state.source.id;
  if (state.voice) result.voice_asset_id = state.voice.id;
  return result;
}

function specChips(spec) {
  const chips = spec.task === "voice_cover" ? ["参考声音转换", "保留原唱音高", `${spec.vocal_gain_db || 0} dB`] : [labels[spec.style],...(spec.instruments || []).map((x) => labels[x] || x),labels[spec.vocal]];
  chips.push(`${spec.clip_start || 0}s 起 / ${spec.duration}s`);
  if (spec.task === "restyle") chips.push(`参考强度 ${spec.cover_strength ?? 0.65}`);
  return `<div class="spec-chips">${chips.map((x) => `<span>${escapeHTML(x)}</span>`).join("")}</div>`;
}

function stepsHTML(steps) {
  return `<ol class="step-list">${steps.map((step,i) => `<li class="${escapeHTML(step.status || "pending")}"><span class="step-icon">${step.status === "succeeded" ? "✓" : step.status === "failed" ? "!" : i + 1}</span><span>${escapeHTML(step.label)}</span></li>`).join("")}</ol>`;
}

function warningsHTML(warnings, blockers = []) {
  return [...blockers.map((text) => `<div class="notice blocker">${escapeHTML(text)}</div>`),...warnings.map((text) => `<div class="notice">${escapeHTML(text)}</div>`)].join("");
}

function renderPlan(plan) {
  state.currentJob = null; state.renderKey = "";
  $("#resultStatus").textContent = plan.blockers.length ? "需要补充信息" : "方案已就绪";
  $("#resultContent").innerHTML = `<div class="plan-summary">${escapeHTML(plan.spec.theme)}<br>${escapeHTML(labels[plan.spec.task])}</div><p class="plan-subtitle">${plan.planner === "llm" ? "LLM 解析" : "离线规则解析"} · ${plan.mode === "demo" ? "流程演示" : "真实模型"}${plan.parent_job_id ? " · 基于已有版本" : ""}</p>${specChips(plan.spec)}${stepsHTML(plan.steps)}${plan.spec.preserve.length ? `<p class="plan-subtitle">本次保留：${plan.spec.preserve.map((x) => escapeHTML(labels[x])).join("、")}</p>` : ""}${warningsHTML(plan.warnings, plan.blockers)}<div class="plan-actions"><button class="primary-button" id="runButton" ${plan.blockers.length ? "disabled" : ""}>${plan.mode === "demo" ? "运行演示流程" : "开始模型生成"} ↗</button></div><details class="plan-details"><summary>查看任务参数与歌词</summary><pre>${escapeHTML(JSON.stringify(plan.spec,null,2))}</pre><p>歌词来源：${escapeHTML(plan.lyrics_origin)}</p></details>`;
  $("#runButton").addEventListener("click", runPlan);
}

async function plan(event) {
  event.preventDefault();
  if (state.uploading || state.planning || state.recorder) return toast("请先完成上传或录音", true);
  const revision = state.revision;
  const button = $("#planButton");
  state.planning = true; button.disabled = true; button.textContent = "正在解析…";
  try {
    const result = await api("/api/plans", {prompt:$("#prompt").value,controls:controls(),parent_job_id:state.parent?.id || null});
    state.plan = result; state.planRevision = revision; renderPlan(result);
    if (revision !== state.revision) {const run = $("#runButton");run.disabled = true;run.textContent = "要求已修改，请重新解析";}
  } catch (error) {toast(error.message, true);}
  finally {state.planning = false;button.disabled = state.uploading > 0;button.innerHTML = "解析创作方案 <span>↗</span>";}
}

async function runPlan() {
  if (!state.plan || state.planRevision !== state.revision || state.submitting) return;
  state.submitting = true;
  $("#runButton").disabled = true;
  try {
    const job = await api("/api/jobs", {plan_id:state.plan.id});
    state.plan = null; state.currentJob = job.id; rememberJob(job.id); state.renderKey = ""; renderJob(job);
    await refreshJobs();
  } catch (error) {toast(error.message, true); if ($("#runButton")) $("#runButton").disabled = false;}
  finally {state.submitting = false;}
}

function renderJob(job) {
  const key = JSON.stringify([job.id,job.status,job.steps,job.events,job.output_asset_id]);
  if (key === state.renderKey) return;
  state.renderKey = key;
  $("#resultStatus").textContent = labels[job.status] || job.status;
  const completed = job.status === "succeeded";
  const active = ["queued","running","canceling"].includes(job.status);
  const output = completed ? `<div class="output-player"><small>${job.mode === "demo" ? "DEMO / 合成旋律占位" : "YOUR NEW VERSION"}</small><h3>${escapeHTML(job.title)}</h3><audio controls preload="metadata" src="/api/assets/${job.output_asset_id}/audio"></audio><div class="output-actions"><a href="/api/assets/${job.output_asset_id}/audio" download="${job.mode === "demo" ? "DEMO" : "MusicCraft"}-${job.id.slice(0,8)}.wav">下载音频 ↓</a><button class="text-button" data-pin="${job.id}">收藏到演示台 ☆</button><button class="text-button" data-export="${job.id}">导出记录 ↓</button><button class="text-button" data-reuse="${job.id}">基于此版本继续 ↗</button></div><div class="signal-metrics">${job.metrics?.duration_seconds ? `<span>${job.metrics.duration_seconds}s</span><span>${job.metrics.sample_rate} Hz</span><span>${job.metrics.channels} 声道</span>` : ""}</div></div>` : "";
  $("#resultContent").innerHTML = `<div class="plan-summary">${escapeHTML(job.title)}</div><p class="plan-subtitle">版本 ${job.id.slice(0,8)}${job.parent_job_id ? ` ← ${job.parent_job_id.slice(0,8)}` : ""} · ${job.mode === "demo" ? "演示模式" : "真实模型"}</p>${specChips(job.spec)}${output}${completed ? comparisonHTML(job) : ""}${active ? `<p class="progress-message">${escapeHTML(job.events.at(-1)?.message || "等待调度…")}</p>` : ""}${stepsHTML(job.steps)}${job.error ? `<div class="notice blocker">${escapeHTML(job.error)}</div>` : ""}${warningsHTML(job.warnings)}${["failed","canceled"].includes(job.status) ? `<button class="secondary-button" data-retry="${job.id}">重新检查方案 ↗</button>` : ""}${active ? `<div class="plan-actions"><button id="cancelJob" class="secondary-button" ${job.status === "canceling" ? "disabled" : ""}>${job.status === "canceling" ? "正在取消…" : "取消任务"}</button></div>` : ""}<details class="plan-details"><summary>执行记录 · ${job.events.length} 条</summary><pre>${escapeHTML(job.events.map((e) => `${new Date(e.at).toLocaleTimeString("zh-CN")}  ${e.message}`).join("\n") || "等待任务开始…")}</pre></details><details class="plan-details"><summary>任务参数</summary><pre>${escapeHTML(JSON.stringify(job.spec,null,2))}</pre></details>`;
  if (completed) bindComparison(job);
  if (active) $("#cancelJob").addEventListener("click", async () => {
    try {renderJob(await api(`/api/jobs/${job.id}/cancel`, {}));}
    catch (error) {toast(error.message, true);}
  });
}

function versionHTML(job) {
  const time = new Date(job.created_at).toLocaleString("zh-CN",{month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit"});
  return `<article class="version-card"><div class="version-card-top"><span class="version-badge">${job.mode === "demo" ? "DEMO" : "LIVE"} / ${job.id.slice(0,6)}</span><time>${escapeHTML(time)}</time></div><h3>${escapeHTML(job.title)}</h3><p>${escapeHTML(labels[job.spec.style])} · ${escapeHTML(labels[job.spec.vocal])} · ${job.spec.duration}s${job.parent_job_id ? ` · 源自 ${job.parent_job_id.slice(0,6)}` : ""}</p><div class="version-footer"><span class="job-status ${escapeHTML(job.status)}">${escapeHTML(labels[job.status] || job.status)}</span><div class="version-buttons"><button class="text-button" data-open="${job.id}">打开</button>${job.status === "succeeded" ? `<button class="text-button" data-reuse="${job.id}">继续编辑 ↗</button>` : ""}</div></div></article>`;
}

function renderLibrary() {
  const empty = '<div class="empty-library">你的第一段音乐，即将在这里开始。</div>';
  const cards = state.jobs.map(versionHTML);
  $("#recentJobs").innerHTML = cards.slice(0,3).join("") || empty;
  $("#allJobs").innerHTML = cards.join("") || empty;
  $("#versionCount").textContent = state.jobs.length;
  $("#recentCount").textContent = "/ " + String(state.jobs.length).padStart(2,"0");
}

async function refreshJobs() {
  if (state.polling) return;
  state.polling = true;
  try {
    state.jobs = (await api("/api/jobs")).jobs;
    renderLibrary();
    const current = state.jobs.find((job) => job.id === state.currentJob);
    if (current) renderJob(current);
  } finally {state.polling = false;}
}

async function reuse(jobId) {
  const job = state.jobs.find((item) => item.id === jobId);
  if (!job || job.status !== "succeeded") return;
  state.parent = job; state.plan = null;
  const assets = (await api("/api/assets")).assets;
  const asset = assets.find((item) => item.id === job.output_asset_id);
  if (!asset) throw new Error("版本输出素材不存在");
  setAsset("source", asset);
  if (job.spec.voice_asset_id && !state.voice) {
    const voice = assets.find((item) => item.id === job.spec.voice_asset_id);
    if (voice) setAsset("voice", voice);
  }
  $("#parentBanner").hidden = false;
  $("#parentText").textContent = `正在基于版本 ${job.id.slice(0,8)} 继续创作`;
  for (const name of ["style","vocal","duration"]) $(`#${name}`).value = "auto";
  for (const name of ["theme","lyrics","bpm"]) $(`#${name}`).value = "";
  $$("input[name=instrument],input[name=preserve]").forEach((input) => {input.checked = false;});
  $("#seed").value = job.spec.seed;
  $("#clip_start").value = 0;
  setTask("restyle");
  $("#prompt").value = "保留主旋律，把这一版改成木吉他流行风格。";
  $("#promptCount").textContent = `${$("#prompt").value.length} / 4000`;
  view("studio"); toast("已关联父版本。编辑要求后重新解析方案。");
  $("#prompt").focus();
}

async function toggleRecord() {
  if (state.recorder) {state.recorder.stop();return;}
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) return toast("此浏览器不支持录音，请上传音频文件", true);
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({audio:true});
    const type = ["audio/webm;codecs=opus","audio/mp4","audio/ogg;codecs=opus"].find((mime) => MediaRecorder.isTypeSupported(mime));
    const recorder = new MediaRecorder(stream, type ? {mimeType:type} : {});
    const chunks = [];
    recorder.addEventListener("dataavailable", (event) => {if (event.data.size) chunks.push(event.data);});
    recorder.addEventListener("stop", async () => {
      clearTimeout(state.recordTimer); stream.getTracks().forEach((track) => track.stop()); state.recorder = null;
      $("#recordVoice").textContent = "录制声音"; $("#recordVoice").classList.remove("recording");
      const mime = recorder.mimeType || "audio/webm";
      const ext = mime.includes("mp4") ? "m4a" : mime.includes("ogg") ? "ogg" : "webm";
      await upload("voice", new File(chunks, `我的声音.${ext}`, {type:mime}));
    });
    state.recorder = recorder; recorder.start(); $("#recordVoice").textContent = "停止录音 ■";
    $("#recordVoice").classList.add("recording"); $("#voiceStatus").textContent = "录音中，最多 20 秒…";
    state.recordTimer = setTimeout(() => {if (state.recorder?.state === "recording") state.recorder.stop();},20000);
  } catch (error) {stream?.getTracks().forEach((track) => track.stop());toast("未能开始录音，请检查麦克风权限或上传录音", true);}
}

function bindEvents() {
  $$("[data-view]").forEach((button) => button.addEventListener("click", () => view(button.dataset.view)));
  $$("[data-task]").forEach((button) => button.addEventListener("click", () => setTask(button.dataset.task)));
  $("#showLibrary").addEventListener("click", () => view("library"));
  $("#createForm").addEventListener("submit", plan);
  $("#createForm").addEventListener("input", () => {dirty();$("#promptCount").textContent = `${$("#prompt").value.length} / 4000`;});
  $("#sourceFile").addEventListener("change", (event) => upload("source",event.target.files[0]));
  $("#voiceFile").addEventListener("change", (event) => upload("voice",event.target.files[0]));
  $("#checkServices").addEventListener("click", checkServices);
  $("#cover_strength").addEventListener("input", () => {$("#strengthValue").textContent = $("#cover_strength").value;});
  $$("[data-remove]").forEach((button) => button.addEventListener("click", () => {
    const role = button.dataset.remove; state[role] = null; button.hidden = true;
    const audio = $(`#${role}Preview`); audio.pause(); audio.removeAttribute("src"); audio.hidden = true;
    $(`#${role}File`).value = ""; $(`#${role}Status`).textContent = "尚未选择"; dirty();
  }));
  document.addEventListener("play", (event) => {if (event.target.tagName === "AUDIO") $$("audio").forEach((el) => {if (el !== event.target) el.pause();});}, true);
  $("#recordVoice").addEventListener("click", toggleRecord);
  $("#clearParent").addEventListener("click", () => {state.parent = null;$("#parentBanner").hidden = true;dirty();toast("已取消版本继承；当前音频仍作为独立素材保留");});
  $("#demoAssets").addEventListener("click", async () => {
    const button = $("#demoAssets"); button.disabled = true; state.uploading++; dirty(); $("#planButton").disabled = true;
    try {const assets = await api("/api/demo-assets",{}, {method:"POST"});setAsset("source",assets.source);setAsset("voice",assets.voice);toast("已载入流程演示素材，参考音不是人声");}
    catch (error) {toast(error.message,true);}finally{button.disabled = false;state.uploading--;$("#planButton").disabled = state.uploading > 0 || state.planning;}
  });
  const presets = {
    pop:{task:"restyle",text:"保留主旋律，把原曲改成温暖的木吉他流行风格，20 秒。"},
    voice:{task:"voice_cover",text:"保留原来的伴奏和旋律，把歌声换成我上传的声音。"},
    guofeng:{task:"restyle",text:"保留主旋律，把原曲改成古风，加入古筝和弦乐。"}
  };
  $$("[data-preset]").forEach((button) => button.addEventListener("click", () => {
    const preset = presets[button.dataset.preset];setTask(preset.task);$("#prompt").value = preset.text;
    $("#promptCount").textContent = `${preset.text.length} / 4000`;dirty();
  }));
  document.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-open],[data-reuse],[data-pin],[data-export],[data-retry]");
    if (!button) return;
    try {
      if (button.dataset.pin) {
        await api(`/api/jobs/${button.dataset.pin}/pin`, {}); await refreshShowcase(); return toast("已收藏，可在演示台回放");
      }
      if (button.dataset.export) {
        const job = await api(`/api/jobs/${button.dataset.export}`);
        const url = URL.createObjectURL(new Blob([JSON.stringify(job,null,2)],{type:"application/json"}));
        const link = document.createElement("a"); link.href = url; link.download = `MusicCraft-${job.id.slice(0,8)}.json`; link.click(); setTimeout(() => URL.revokeObjectURL(url),1000); return;
      }
      if (button.dataset.retry) return await restoreRequest(button.dataset.retry);
      if (button.dataset.reuse) return await reuse(button.dataset.reuse);
      const job = await api(`/api/jobs/${button.dataset.open}`);
      state.currentJob = job.id;rememberJob(job.id);state.plan = null;state.renderKey = "";renderJob(job);view("studio");
    } catch (error) {toast(error.message,true);}
  });
  window.addEventListener("beforeunload", () => {if(state.recorder) state.recorder.stream.getTracks().forEach((track) => track.stop());});
}

async function initialize() {
  bindEvents();
  $$(".mini-bars,.hero-bars").forEach((container) => {
    const count = container.classList.contains("hero-bars") ? 13 : 25;
    for(let i=0;i<count;i++){const bar = document.createElement("i");bar.style.height = `${12 + Math.abs(Math.sin(i * 1.4)) * (count === 13 ? 62 : 20)}px`;container.appendChild(bar);}
  });
  try {
    state.config = await api("/api/config");
    $("#modeBadge").textContent = state.config.mode === "demo" ? "DEMO · 演示模式" : "LIVE · 真实模型";
    $("#modeNotice").hidden = state.config.mode !== "demo";
    $("#integrationStatus").textContent = `音频运行：${state.config.mode === "demo" ? "演示" : "真实"} / 任务解析：${state.config.planner === "rules" ? "离线规则" : "LLM"} / 生成服务：${state.config.generation_ready ? "已配置" : "未配置"} / 歌声 Worker：${state.config.voice_ready ? "已配置" : "未配置"}`;
    $('[data-task="compose"]').hidden = !state.config.enable_compose;
    setTask(state.task,false); await refreshJobs(); await refreshShowcase();
    let saved; try {saved = localStorage.getItem("musiccraft.currentJob");} catch (_) {}
    const last = state.jobs.find((job) => job.id === saved) || state.jobs.find((job) => ["queued","running","canceling"].includes(job.status));
    if (last) {state.currentJob = last.id;state.renderKey = "";renderJob(last);}
    checkServices();
  } catch (error) {$("#modeBadge").textContent = "连接失败";toast("无法连接本地服务，请确认 run.py 正在运行",true);}
  setInterval(() => {
    if (state.jobs.some((job) => ["queued","running","canceling"].includes(job.status))) refreshJobs().catch((error) => toast(error.message,true));
  },1300);
}

initialize();

function rememberJob(id) {
  try {localStorage.setItem("musiccraft.currentJob", id);} catch (_) {}
}

function comparisonHTML(job) {
  const original = job.artifacts?.source_clip || job.spec.source_asset_id;
  const stems = {original_vocals:"分离出的原唱",converted_vocals:"转换后的歌声",accompaniment:"分离出的伴奏"};
  return `<section class="comparison"><div class="compare-heading"><h3>原曲与结果</h3><span>${job.mode === "demo" ? "占位输出未转换原曲" : "A / B 试听"}</span></div>${original ? `<label>A · ${job.artifacts?.source_clip ? "已裁剪原曲" : "输入原曲"}<audio id="compareA" controls preload="metadata" src="/api/assets/${original}/audio"></audio></label>` : ""}<label>B · ${job.mode === "demo" ? "流程演示占位音" : "处理结果"}<audio id="compareB" controls preload="metadata" src="/api/assets/${job.output_asset_id}/audio"></audio></label>${original && job.mode === "live" ? '<div class="ab-buttons"><button class="secondary-button" data-ab="A">听 A · 原曲</button><button class="secondary-button" data-ab="B">听 B · 结果</button><small>按片段相对时间切换；生成式改编可能改变节奏。</small></div>' : ""}${Object.entries(stems).some(([name]) => job.artifacts?.[name]) ? `<details class="stems"><summary>逐步试听 · 人声与伴奏</summary>${Object.entries(stems).filter(([name]) => job.artifacts?.[name]).map(([name,label]) => `<label>${label}<audio controls preload="none" src="/api/assets/${job.artifacts[name]}/audio"></audio></label>`).join("")}</details>` : ""}</section>`;
}

function bindComparison(job) {
  const a = $("#compareA"), b = $("#compareB");
  if (!a || !b) return;
  const offset = job.artifacts?.source_clip ? 0 : job.spec.clip_start || 0;
  a.addEventListener("loadedmetadata", () => {a.currentTime = Math.min(offset, a.duration || offset);}, {once:true});
  if (job.mode === "live") a.addEventListener("timeupdate", () => {if (a.currentTime >= offset + job.spec.duration) a.pause();});
  let last = b;
  for (const player of [a,b]) player.addEventListener("play", () => {last = player;});
  $$("[data-ab]").forEach((button) => button.addEventListener("click", async () => {
    const target = button.dataset.ab === "A" ? a : b;
    const relative = Math.max(0, last.currentTime - (last === a ? offset : 0));
    last.pause();
    try {
      if (!target.readyState) await new Promise((resolve,reject) => {
        target.addEventListener("loadedmetadata",resolve,{once:true}); target.addEventListener("error",reject,{once:true}); target.load();
      });
      target.currentTime = Math.min(relative + (target === a ? offset : 0), Math.max(0,(target.duration || Infinity)-0.05));
      await target.play(); last = target;
    } catch (_) {toast("音频暂不可播放，请使用播放器重试", true);}
  }));
}

async function refreshShowcase() {
  state.showcases = (await api("/api/showcases")).showcases;
  $("#showcaseJobs").innerHTML = state.showcases.map((item) => {
    const job = state.jobs.find((job) => job.id === item.job_id);
    if (!job) return "";
    return `<div class="showcase-entry"><p class="showcase-origin">${escapeHTML(item.origin)} · 本地回放</p>${versionHTML(job)}</div>`;
  }).join("") || '<div class="empty-library">在已完成结果中点击「收藏到演示台」。提前跑好真实样例后，可在这里稳定回放。</div>';
}

async function checkServices() {
  const button = $("#checkServices"); button.disabled = true;
  $("#serviceStatus").textContent = "检查服务连接中…";
  try {
    const result = await api("/api/services");
    const names = {connected:"可连接",unconfigured:"未配置",needs_setup:"待安装依赖",offline:"未连接"};
    $("#serviceStatus").innerHTML = [["ACE-Step / 风格改编",result.ace],["Voice Worker / 音色翻唱",result.voice]].map(([name,item]) => `<div class="service-row"><span>${name}</span><strong class="service-${escapeHTML(item.state)}">${escapeHTML(names[item.state] || item.state)}</strong><small>${escapeHTML(item.message)}</small></div>`).join("") + `<p>本地 FFmpeg：${result.ffmpeg ? "可用" : "未安装（真实改编的压缩音频裁剪需要）"} · 作曲：${result.compose_enabled ? "实验功能已开启" : "暂缓"}</p>`;
  } catch (error) {$("#serviceStatus").textContent = error.message;}
  finally {button.disabled = false;}
}

async function restoreRequest(id) {
  const job = state.jobs.find((job) => job.id === id);
  if (!job) return;
  if (job.spec.task === "compose" && !state.config.enable_compose) return toast("作曲目前暂缓，请使用两项主功能",true);
  const assets = (await api("/api/assets")).assets;
  state.parent = null; state.plan = null; $("#parentBanner").hidden = true;
  for (const [role,field] of [["source","source_asset_id"],["voice","voice_asset_id"]]) {
    const asset = assets.find((item) => item.id === job.spec[field]);
    if (asset) setAsset(role,asset); else $(`[data-remove="${role}"]`).click();
  }
  setTask(job.spec.task); $("#prompt").value = job.prompt;
  for (const name of ["style","vocal","duration","theme","lyrics","bpm","seed","clip_start","cover_strength","vocal_gain_db"]) {
    $(`#${name}`).value = job.spec[name] ?? {clip_start:0,cover_strength:0.65,vocal_gain_db:0}[name] ?? "";
  }
  $("#strengthValue").textContent = $("#cover_strength").value;
  for (const name of ["instrument","preserve"]) $$(`input[name=${name}]`).forEach((input) => {input.checked = (job.spec[name === "instrument" ? "instruments" : "preserve"] || []).includes(input.value);});
  $("#promptCount").textContent = `${job.prompt.length} / 4000`;
  dirty(); view("studio"); toast("已恢复请求。确认素材和服务后重新解析，不会自动执行。");
}
