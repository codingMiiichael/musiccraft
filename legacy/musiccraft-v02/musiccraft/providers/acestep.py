"""ACE-Step async API adapter. Contract reference: docs/en/API.md upstream."""
import json
import time

from .transport import ProviderError, headers, multipart, request_bytes, request_json, same_origin_url


class AceStepProvider:
    def __init__(self, settings):
        self.settings = settings

    def generate(self, spec, prompt, source=None, canceled=lambda: False, progress=lambda message: None):
        s = self.settings
        if not s.ace_url:
            raise ProviderError("未配置 ACESTEP_BASE_URL")
        caption = ", ".join([spec["style"], *spec["instruments"], spec["vocal"], spec["theme"], prompt])
        payload = {"prompt": caption, "lyrics": "[Instrumental]" if spec["vocal"] == "instrumental" else spec["lyrics"],
                   "task_type": "cover" if spec["task"] == "restyle" else "text2music",
                   "audio_duration": spec["duration"], "bpm": spec["bpm"], "vocal_language": spec["language"],
                   "seed": spec["seed"], "use_random_seed": False, "batch_size": 1, "audio_format": "wav",
                   "thinking": s.ace_thinking, "use_cot_caption": False, "use_cot_language": False,
                   "audio_cover_strength": spec.get("cover_strength",0.65)}
        if s.ace_model:
            payload["model"] = s.ace_model
        if source:
            body, content_type = multipart(payload, {"src_audio": source})
            h = headers(s.ace_key)
            h["Content-Type"] = content_type
            raw, _ = request_bytes(s.ace_url + "/release_task", body, h, timeout=60, limit=2 * 1024 * 1024)
            try:
                response = json.loads(raw)
            except ValueError:
                raise ProviderError("ACE-Step 返回无效提交结果") from None
        else:
            response = request_json(s.ace_url + "/release_task", payload, s.ace_key)
        try:
            task_id = response["data"]["task_id"]
            if response.get("error") or not isinstance(task_id, str):
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise ProviderError("ACE-Step 未返回 task_id，请检查模型是否加载成功") from None
        progress("ACE-Step 任务已提交，等待模型返回。远端任务可能在本地取消后继续运行。")
        deadline = time.monotonic() + s.provider_timeout
        while time.monotonic() < deadline:
            if canceled():
                raise InterruptedError("本地任务已取消；远端生成可能继续运行")
            result = request_json(s.ace_url + "/query_result", {"task_id_list": [task_id]}, s.ace_key)
            rows = result.get("data")
            if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
                raise ProviderError("ACE-Step 状态响应格式错误")
            row = rows[0]
            if row.get("status") in {2, "2"}:
                raise ProviderError("ACE-Step 生成失败，请查看远端日志")
            if row.get("status") in {1, "1"}:
                try:
                    outputs = json.loads(row["result"]) if isinstance(row["result"], str) else row["result"]
                    reference = outputs[0]["file"]
                    url = same_origin_url(s.ace_url, reference)
                except (KeyError, IndexError, TypeError, ValueError):
                    raise ProviderError("ACE-Step 输出缺少音频地址") from None
                return request_bytes(url, request_headers=headers(s.ace_key), timeout=60)
            # Short slices allow cancellation to be noticed without waiting for a poll.
            for _ in range(10):
                if canceled():
                    raise InterruptedError("本地任务已取消；远端生成可能继续运行")
                time.sleep(0.2)
        raise ProviderError("ACE-Step 等待超时；请检查远端任务，避免重复提交付费任务")
