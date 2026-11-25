# GPU 部署与第一次真实验收

本机尚无 GPU/API，以下脚本已经编写并检查语法，未在 GPU 服务器执行。部署后必须跑真实样例，才能宣称功能效果已验证。

## 1. 服务器准备

将项目上传到可使用 NVIDIA GPU 的 Ubuntu 服务器。需要 Git、FFmpeg、Python 3.10 + venv、NVIDIA 驱动；ACE-Step 另用 uv 管理自己的 Python 和环境。不要在本地 Mac 执行 GPU 安装脚本。

```bash
nvidia-smi
ffmpeg -version
python3.10 --version
```

先选一台可短期租用的机器跑 10–20 秒样例，再按实测显存、耗时决定配置。当前没有显存或性能基准，不承诺某张卡能同时运行所有模型。可以分时运行两个服务，并将成功结果收藏用于展示。

## 2. 歌声转换服务

在远端项目根目录：

```bash
bash deploy/setup_gpu.sh
bash deploy/start_voice.sh
```

安装脚本：从官方仓库下载 Seed-VC，分别创建 `.venvs/seed` 与 `.venvs/demucs`，安装推理依赖和 CUDA 12.1 版 PyTorch 2.4，记录 Seed-VC revision。需要驱动支持对应 CUDA 运行时。上游 requirements 同时包含 nightly/stable Torch，因此脚本使用明确版本并排除 GUI 依赖。依赖兼容性仍需在目标机器验证。

Worker 默认监听 `127.0.0.1:8010`。健康检查：

```bash
curl http://127.0.0.1:8010/health
```

`ready` 只检查推理程序与部分依赖是否存在；不证明 CUDA 推理、模型下载或音质。首次真实任务会下载权重。每个任务的模型输出和错误位于 `voice-data/<任务ID>/pipeline.log`。

可选环境变量：`VOICE_WORKER_API_KEY`、`VOICE_DEVICE`（默认 cuda）、`VOICE_PIPELINE_TIMEOUT`（每步默认 1200 秒）。`deploy/start_voice.sh` 自动设置 Seed-VC 与 Demucs 的 Python 路径。不需要训练个人模型，目标音色来自本次参考录音。

Seed-VC CLI 自行选择可用设备；`VOICE_DEVICE` 主要用于 Demucs 与精度参数。本项目主要面向 CUDA 路线。初次验证只使用单人独唱、伴奏简单的片段。

## 3. 风格改编服务

另一个远端终端，在项目根目录：

```bash
bash deploy/setup_acestep.sh
bash deploy/start_acestep.sh
```

需要预先安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)。脚本从 [ACE-Step 官方仓库](https://github.com/ace-step/ACE-Step-1.5) 获取代码，执行 `uv sync`；具体 Python、PyTorch、驱动要求由其 `pyproject.toml` 决定，与 Seed-VC 环境独立。当前上游要求 Python 3.11–3.12，部署时再次核对。

默认监听 `127.0.0.1:8001`。等待服务完成模型加载后再检查：

```bash
curl http://127.0.0.1:8001/health
```

可用 `ACESTEP_API_KEY` 配置密钥。默认不启用额外 LM。安装会记录 `modelsrc/acestep-revision.txt`，真实联调通过后保留 revision，避免演示前升级依赖。

## 4. 连回本地工作台

在本机新终端建立隧道，保持终端运行：

```bash
ssh -L 8001:127.0.0.1:8001 -L 8010:127.0.0.1:8010 your-user@your-server
```

本机项目根目录创建 `.env`，设置：

```dotenv
MUSICCRAFT_MODE=live
MUSICCRAFT_PLANNER=rules
MUSICCRAFT_ENABLE_COMPOSE=false
MUSICCRAFT_PROVIDER_TIMEOUT=1800
ACESTEP_BASE_URL=http://127.0.0.1:8001
VOICE_WORKER_URL=http://127.0.0.1:8010
VOICE_WORKER_PROTOCOL=async
```

如果远端设置了密钥，在本机 `.env` 填入相同的 `ACESTEP_API_KEY` / `VOICE_WORKER_API_KEY`。随后重启 `python3 -B run.py`。无需开放公网模型端口。

本机真实改编：PCM WAV 可以用标准库裁剪；MP3/M4A/WebM 等需要本机也安装 FFmpeg。音色翻唱在远端解码，不依赖本机 FFmpeg。

## 5. 两项真实验收

### 风格改编

上传 10–20 秒清晰原曲；选择起点、目标风格与乐器；从参考强度 0.65 开始，随后比较 0.35 / 0.65 / 0.85。解析方案并生成，试听原曲与结果。记录：目标风格是否变化、旋律是否可辨、歌词是否改变、音质与耗时。至少准备一段原曲对应两个风格。

### 参考音色翻唱

上传包含原唱的 10–20 秒片段；上传组员本人 10–20 秒干净录音（至少 3 秒）。生成后分别听原曲、原唱分轨、转换歌声、伴奏、最终混音。确认没有把参考录音内容混入歌曲，音高节奏基本一致，目标音色可辨，混音没有明显截断、错位或爆音。

每项至少 3 个样例，失败案例也记录。先预热、听测、收藏，再作为课堂展示素材；健康检查通过不能代替这一步。

## 常见问题

- 服务未连接：检查 SSH 隧道、远端进程、端口与密钥。
- `needs_setup`：检查 Worker `/health` 中的检查项，重新核对虚拟环境路径。
- 首次超时：检查权重下载与网络；确认远端任务已结束后再手动重跑，避免重复任务。
- OOM：停止另一模型服务、缩短片段；按实际日志调整配置。
- 音色不明显：换干净参考录音，先验证独唱；分离串音会影响转换，不能仅修改 prompt 解决。
- 只有合成旋律：检查顶栏是否 DEMO。demo 结果不能充当真实模型效果证据。

上游依据：[Seed-VC](https://github.com/Plachtaa/seed-vc)、[Demucs](https://github.com/facebookresearch/demucs)、[ACE-Step API](https://github.com/ace-step/ACE-Step-1.5/blob/main/docs/en/API.md)。前两者当前仓库已归档，务必保留验证通过的环境和 revision。
