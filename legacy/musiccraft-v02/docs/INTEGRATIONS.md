# 模型接入协议 · v0.2

默认 demo 不访问音频模型。真实执行代码已经实现，GPU 部署与听测未完成；步骤见 [GPU_DEPLOYMENT.md](GPU_DEPLOYMENT.md)。

## ACE-Step：整体风格改编

`restyle → task_type=cover`。Engine 先依据 `clip_start / duration` 解码裁剪源音频；PCM WAV 用标准库，其余格式需要本机 FFmpeg。

1. multipart `POST /release_task`，上传 `src_audio`；不传本机文件路径。
2. 读取 `data.task_id`，`POST /query_result` 传 `task_id_list`。
3. `status=1` 后解析 result，下载同来源 `file` 音频。
4. 保存裁剪原曲与输出，供 A/B 试听；失败不回退 demo。

`cover_strength` 直接映射 `audio_cover_strength`，范围 0–1，默认 0.65，需真实听测校准。乐器、风格、人声选择、主题与自然语言形成 prompt。提供歌词时传 lyrics；纯音乐传 `[Instrumental]`。旋律保持是软约束，不提供原伴奏严格锁定或单乐器精确替换。

ACE-Step 本地取消只停止等待，远端推理可能继续。compose 适配器仍保留，默认由功能开关阻止使用。

依据：[官方 API](https://github.com/ace-step/ACE-Step-1.5/blob/main/docs/en/API.md)。

## 自定义异步 Voice Worker

这不是 Seed-VC 原生接口。已实现于 `workers/voice_server.py`。默认监听本机 8010，支持 `Authorization: Bearer <key>`。

| 方法 | 路径 | 结果 |
| --- | --- | --- |
| GET | `/health` | 部分程序和依赖检查；不证明模型效果 |
| POST | `/v1/jobs` | multipart 提交，HTTP 202 返回 id/status |
| GET | `/v1/jobs/{id}` | status、stage、message、error、artifacts |
| POST | `/v1/jobs/{id}/cancel` | 请求协作式取消 |
| GET | `/v1/jobs/{id}/audio/{name}` | 已完成任务的 WAV 音轨 |

上传字段：`spec`（完整 TaskSpec JSON）、`source`（原曲文件）、`reference`（目标录音文件）。仅接受 voice_cover，文件每个最多 32 MiB，整体最多 66 MiB。排队与运行合计最多 4 个任务，GPU 一次运行一个。

执行阶段：normalize → separate → convert → mix → done。

- FFmpeg 裁剪原曲 10–40 秒；实际输入不足时取剩余长度，至少 3 秒。参考录音取前 20 秒，至少 3 秒。
- Demucs `htdemucs --two-stems=vocals` 分离。
- Seed-VC `inference.py` 使用 F0 条件、length-adjust 1.0、auto-f0-adjust False、移调 0。
- FFmpeg 对转换歌声补齐尾部、调节增益，与分离伴奏混合并限制峰值；按实际源片段长度导出。
- 返回 result、source_clip、original_vocals、converted_vocals、accompaniment。原始参考录音及解码参考在任务结束后清理；本地工作台上传素材仍保存在 data 中。

成功状态示例：

```json
{"id":"32位任务ID","status":"succeeded","stage":"done","artifacts":{"result":"/v1/jobs/ID/audio/result","source_clip":"/v1/jobs/ID/audio/source_clip","original_vocals":"/v1/jobs/ID/audio/original_vocals","converted_vocals":"/v1/jobs/ID/audio/converted_vocals","accompaniment":"/v1/jobs/ID/audio/accompaniment"}}
```

Provider 轮询并下载这些音轨，Engine 验证后保存为本地资产。取消或超时会请求 Worker 取消，Worker 停止正在执行的子进程组。网络中断时不能保证取消已到达。Worker 重启丢失内存任务，但本地已保存结果不受影响。

旧同步协议仅保留在客户端 `VOICE_WORKER_PROTOCOL=sync` 中兼容外部服务 `/v1/voice-cover`；本项目新 Worker 只实现 async，请保持默认配置。

依据：[Seed-VC CLI](https://github.com/Plachtaa/seed-vc/blob/main/inference.py)、[Demucs](https://github.com/facebookresearch/demucs)。真实音色相似、对齐及音质需实际验证。

## LLM 规划

`MUSICCRAFT_PLANNER=llm` 时，向 `LLM_BASE_URL + /chat/completions` 发送 messages，解析 `choices[0].message.content` 的 JSON。模型只提取本轮修改，表单覆盖模型值，素材 ID 不允许由模型提供。

没有自由对话或自动听感评价。缺失素材、保留约束冲突通过 blockers 呈现；需重新解析确认，不自动执行或重试。
