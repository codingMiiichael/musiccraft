# MusicCraft · v0.2

**[在线演示网页](https://musiccraft-agent-demo.spicypony68.chatgpt.site)** · **[GitHub 项目](https://github.com/codingMiiichael/musiccraft)**

在线演示已公开，任何拿到链接的人都可打开，无需启动本地服务。点击「开始演示」即可体验完整流程。在线版使用浏览器内规则规划和合成占位音频；素材与版本仅保存在当前浏览器。源码位于 [online-demo/](online-demo/README.md)。

音乐多模态 Agent 课程项目。当前聚焦两项主功能：**歌曲整体风格改编**、**上传参考声音的歌声转换**。从零作曲默认暂缓，可通过配置开启实验入口。

**当前没有接入 GPU/API：本机默认运行的是明确标注的流程演示，输出为程序合成旋律，不会转换上传歌曲或克隆声音。真实模型执行代码已实现，尚未在 GPU 上验证效果。**

## 立即运行

本地仅需 Python 3.9+，无需安装第三方包：

```bash
python3 -B run.py
```

打开 [本地工作台](http://127.0.0.1:8765)。端口占用时加 `--port 8766`。结束时 Ctrl+C；素材和版本保存在 `data/`。

1. 默认「风格改编」→「载入演示素材」→「流行木吉他」。
2. 「解析创作方案」→ 核对参数 →「运行演示流程」。
3. 试听、下载、导出执行记录，或「收藏到演示台」。
4. 切换「音色翻唱」→「用我的声音唱」→ 解析并运行。
5. 在「演示台」打开已收藏版本，回放输入与输出；不重复调用模型。

上传音频与浏览器录音可用，单文件最多 32 MiB，录音最长 20 秒。演示模式中的上传只验证工作流程。

## 这一版的实现

| 能力 | 状态与边界 |
| --- | --- |
| 风格改编 | ACE-Step Cover 上传、异步轮询、下载；先按起点和时长裁剪源音频。真实效果待验证 |
| 歌声音色转换 | GPU Worker 执行 Demucs → Seed-VC F0 条件转换 → FFmpeg 混音；真实效果待验证 |
| 中间音轨 | 真实 Worker 返回裁剪原曲、原唱、转换歌声、伴奏，支持逐步试听 |
| 展示与回放 | A/B 切换、历史版本、收藏演示台、JSON 记录导出、刷新后恢复当前任务 |
| 任务控制 | 方案确认、异步队列、阶段日志、取消、失败后恢复请求，无自动付费重试 |
| Agent | 离线规则解析可用；可配置 LLM JSON 解析适配器，待真实供应商联调 |
| 作曲 | 默认关闭；`MUSICCRAFT_ENABLE_COMPOSE=true` 开启实验入口，不作为本期必交能力 |

音频格式与信号检查已经实现，**不等于音乐质量、风格或身份相似度评价**。真实服务失败直接报错，不退回合成音频。

## 接入 GPU

从 [GPU 部署说明](docs/GPU_DEPLOYMENT.md) 开始。已提供四个脚本，分别安装与启动歌声 Worker、ACE-Step，模型采用独立虚拟环境。脚本需在租用的 Ubuntu NVIDIA GPU 服务器运行；本机没有执行安装或下载模型。

```bash
cp .env.example .env
```

在 `.env` 中配置真实服务地址后重启本地服务。Key 只由后端读取，前端不显示。

- 风格改编：`MUSICCRAFT_MODE=live` + `ACESTEP_BASE_URL`。
- 音色翻唱：同为 live，配置 `VOICE_WORKER_URL`；这是本项目 Worker 的地址，不是 Seed-VC 网页地址。
- LLM 解析：`MUSICCRAFT_PLANNER=llm`，配置 `LLM_BASE_URL`、`LLM_MODEL`、`LLM_API_KEY`。默认 rules 不依赖外部 LLM。

点击执行真实任务后，歌曲与参考录音会上传至你配置的模型服务器。LLM 模式解析时会发送文字与继承参数（可能含歌词）。优先使用组员本人或已获授权的素材。

## 目录与检查

```text
musiccraft/        任务参数、规划器、执行器、SQLite、本地 API、模型适配器
workers/          异步歌声服务与真实音频处理命令
web/              原生 HTML / CSS / JavaScript 工作台
Deploy: deploy/   GPU 安装与启动脚本
scripts/          打包脚本（排除密钥、音频与模型）
tests/            参数、流程、HTTP、GPU 命令与取消契约测试
docs/             部署、接口、架构、proposal、演示讲稿
```

```bash
python3 -B -m unittest discover -s tests -v
python3 scripts/package.py
```

自动测试使用临时 WAV、模拟模型响应和模拟 GPU 命令，不调用付费服务，不证明真实模型效果。前端另经过本地浏览器流程验收。

## 项目边界

- 风格改编是整段重新生成；主旋律保留为软约束，不能严格替换复杂歌曲中的某一个乐器。
- 保留歌词需要显式粘贴原歌词；尚无自动歌词转写。原唱音色应使用专门的歌声路线处理。
- 歌声转换保留原唱的音高与时间结构，不保证目标音色完全一致。分离伪影、对齐与混音需真实听测。
- 分轨已经保存用于试听；尚未实现跳过分离的自动分轨缓存复用。
- Voice Worker 支持请求取消并终止自身子进程；ACE-Step 取消主要停止本地等待，远端任务可能继续。
- Worker 队列在内存中，重启不恢复；已下载到本地工作台的结果可回放。工作台启动时把中断任务标记失败。
- 这是本机开发原型，使用显式 Python 工作流与线程池；不需要先引入 LangGraph、Redis 或训练基础模型。

继续阅读：[演示讲稿](docs/DEMO_RUNBOOK.md) · [模型协议](docs/INTEGRATIONS.md) · [项目提案](docs/PROPOSAL.md) · [架构](docs/ARCHITECTURE.md) · [本地 API](docs/API.md)。
