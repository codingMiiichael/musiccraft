# 本地 API

默认地址：`http://127.0.0.1:8765`。所有写请求需要 `X-MusicCraft: 1`，不开放跨来源访问。Key 仅在后端配置，不通过这些接口传入。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/config` | 公开运行模式、解析器、服务配置状态 |
| POST | `/api/assets` | 上传二进制音频 |
| GET | `/api/assets` | 最近 100 个素材 |
| GET | `/api/assets/{id}/audio` | 播放或下载，支持单区间 Range |
| POST | `/api/demo-assets` | 生成演示源音频和非人声参考占位音；仅 demo |
| POST | `/api/plans` | 解析并保存方案，不执行音频生成 |
| POST | `/api/jobs` | 根据方案 ID 提交异步任务 |
| GET | `/api/jobs` | 最近 100 个任务 |
| GET | `/api/jobs/{id}` | 单个任务及步骤、事件、指标 |
| POST | `/api/jobs/{id}/cancel` | 请求取消；Voice Worker 会收到远端取消请求 |
| POST | `/api/jobs/{id}/pin` | 收藏已完成结果，保留来源 |
| GET | `/api/showcases` | 演示台收藏记录 |
| GET | `/api/services` | 检查模型连接，不证明推理效果 |

## 上传

body 是原始文件字节，不是 multipart。`X-Filename` 为 URL 编码后的原文件名；`X-Asset-Role` 为 `source` 或 `voice`。最大 32 MiB。

```bash
curl -X POST http://127.0.0.1:8765/api/assets \
  -H 'X-MusicCraft: 1' \
  -H 'X-Filename: source.wav' \
  -H 'X-Asset-Role: source' \
  --data-binary @source.wav
```

返回包含 `id`、`name`、`url`、`demo`、`role` 的资产对象。素材目录与本地绝对路径不提供给前端。

## 创作方案

```json
{
  "prompt": "保留主旋律，改成木吉他流行风格，20秒",
  "controls": {
    "task": "restyle",
    "source_asset_id": "已上传的原曲ID",
    "seed": 42
  },
  "parent_job_id": null
}
```

表单 controls 为可选覆盖字段。允许的 TaskSpec：

```json
{
  "task": "compose",
  "style": "pop",
  "instruments": ["piano"],
  "vocal": "instrumental",
  "theme": "自由创作",
  "lyrics": "",
  "duration": 20,
  "bpm": 90,
  "seed": 42,
  "language": "zh",
  "preserve": [],
  "source_asset_id": "",
  "voice_asset_id": "",
  "clip_start": 0,
  "cover_strength": 0.65,
  "vocal_gain_db": 0
}
```

- task：compose / restyle / voice_cover。
- style：pop / guofeng / classical / rock / jazz / electronic。
- instruments：piano / guitar / strings / drums / bass / guzheng / violin / flute。
- vocal：instrumental / female / male / any。
- preserve：melody / lyrics / accompaniment。
- duration：10–40 整数；bpm：40–200 整数；seed：0–2147483647 整数。
- language：zh / en / ja。
- clip_start：0–3600 秒；cover_strength：0–1；vocal_gain_db：-12–6 dB。
- compose 默认暂缓，需启用 MUSICCRAFT_ENABLE_COMPOSE=true 才可执行。

返回含 `id`、`spec`、`steps`、`warnings`、`blockers`、`mode`、`planner` 的方案。blockers 非空时禁止执行。

## 执行

```json
{"plan_id":"返回的方案ID"}
```

POST `/api/jobs` 返回 HTTP 202 和 job 对象。同一个 plan_id 重复提交不会重复生成。需要重跑时重新创建方案。

job 包含 `status`、`steps`、`events`、`parent_job_id`、`spec`、`output_asset_id`、`artifacts`（音轨名到资产 ID 的映射）和 `error`。成功后通过输出资产的 audio 路径试听。

## 错误与检查

错误返回 `{"error":"说明"}`。参数及素材问题使用 HTTP 400；找不到记录 404；跨来源写入 403；方案解析供应商故障 502。异步音频任务故障写入 job.status / job.error。

音频成功只代表输出文件已保存。`metrics` 中的 RMS、峰值、时长属于信号检查，音乐质量与指令遵循未自动评分。
