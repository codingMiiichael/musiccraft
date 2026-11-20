import array
import io
import math
import sys
import wave
from concurrent.futures import ThreadPoolExecutor

from .models import LABELS, TaskSpec, ValidationError
from .providers.acestep import AceStepProvider
from .providers.demo import synthesize
from .providers.transport import ProviderError, ensure_audio
from .providers.voice_worker import VoiceWorkerProvider
from .store import now
from .audio import clip_audio


def inspect_audio(content):
    """Signal checks only, not a claim about style, musical quality or identity."""
    try:
        with wave.open(io.BytesIO(content), "rb") as wav:
            result = {"duration_seconds": round(wav.getnframes() / wav.getframerate(), 2),
                      "sample_rate": wav.getframerate(), "channels": wav.getnchannels(),
                      "musical_quality": "尚未评价", "constraint_compliance": "需试听或接入评估模型"}
            if wav.getsampwidth() == 2:
                samples = array.array("h", wav.readframes(min(wav.getnframes(), wav.getframerate() * 40)))
                if sys.byteorder != "little":
                    samples.byteswap()
                if samples:
                    result["peak"] = round(max(abs(v) for v in samples) / 32768, 4)
                    result["rms"] = round(math.sqrt(sum(v * v for v in samples) / len(samples)) / 32768, 4)
            return result
    except (wave.Error, EOFError, ZeroDivisionError):
        return {"signal_check": "音频格式已识别；详细分析需要解码器", "musical_quality": "尚未评价"}


class Engine:
    def __init__(self, settings, store):
        self.settings, self.store = settings, store
        self.pool = ThreadPoolExecutor(max_workers=settings.workers, thread_name_prefix="musiccraft")
        self.ace = AceStepProvider(settings)
        self.voice = VoiceWorkerProvider(settings)

    def submit(self, plan_id):
        with self.store.lock:
            plan = self.store.get("plan", plan_id)
            if not plan:
                raise ValidationError("创作方案不存在，请重新解析")
            if plan["blockers"]:
                raise ValidationError("；".join(plan["blockers"]))
            if plan["mode"] != self.settings.mode:
                raise ValidationError("运行模式已变化，请重新解析方案")
            if plan.get("job_id"):
                return self.store.get("job", plan["job_id"])
            TaskSpec.from_dict(plan["spec"])
            if plan["spec"]["task"] == "compose" and not self.settings.enable_compose:
                raise ValidationError("作曲已暂缓，请重新解析方案")
            job = self.store.put("job", {"plan_id": plan_id, "parent_job_id": plan.get("parent_job_id"),
                "title": plan["spec"]["theme"] + " · " + LABELS[plan["spec"]["task"]],
                "prompt": plan["prompt"], "spec": plan["spec"], "mode": plan["mode"], "planner": plan["planner"],
                "status": "queued", "steps": [dict(step, status="pending") for step in plan["steps"]],
                "events": [], "warnings": plan["warnings"], "output_asset_id": None, "error": None})
            self.store.update("plan", plan_id, job_id=job["id"])
            self.pool.submit(self.run, job["id"])
            return job

    def event(self, job_id, message):
        with self.store.lock:
            job = self.store.get("job", job_id)
            self.store.update("job", job_id, events=(job["events"] + [{"at": now(), "message": message}])[-200:])

    def canceled(self, job_id):
        return self.store.get("job", job_id)["status"] in {"canceling", "canceled"}

    def check_cancel(self, job_id):
        if self.canceled(job_id):
            raise InterruptedError("任务已取消；正在执行的远端请求可能继续运行")

    def step(self, job_id, key, status):
        with self.store.lock:
            job = self.store.get("job", job_id)
            for item in job["steps"]:
                if item["key"] == key:
                    item["status"] = status
            self.store.update("job", job_id, steps=job["steps"])

    def file_tuple(self, asset_id):
        asset = self.store.get("asset", asset_id)
        if not asset:
            raise ValidationError("输入素材不存在")
        return (asset["name"], self.store.asset_path(asset).read_bytes(), asset["mime"])

    def cancel(self, job_id):
        with self.store.lock:
            job = self.store.get("job", job_id)
            if not job:
                raise ValidationError("任务不存在")
            if job["status"] in {"queued", "running"}:
                job = self.store.update("job", job_id, status="canceling")
            return job

    def run(self, job_id):
        active_step = "prepare"
        try:
            with self.store.lock:
                self.check_cancel(job_id)
                self.store.update("job", job_id, status="running")
            job = self.store.get("job", job_id)
            spec = job["spec"]
            self.step(job_id, active_step, "running")
            source = self.file_tuple(spec["source_asset_id"]) if spec["task"] != "compose" else None
            reference = self.file_tuple(spec["voice_asset_id"]) if spec["task"] == "voice_cover" else None
            artifacts={}
            if job["mode"]=="live" and spec["task"]=="restyle":
                source=clip_audio(source,spec.get("clip_start",0),spec["duration"],self.settings.ffmpeg)
                artifacts["source_clip"]=(source[1],source[2])
            self.event(job_id, "已验证任务参数及输入素材。" + ("演示运行，不执行真实音频转换。" if job["mode"] == "demo" else ""))
            self.step(job_id, active_step, "succeeded")
            active_step = {"compose": "generate", "restyle": "restyle", "voice_cover": "voice"}[spec["task"]]
            self.check_cancel(job_id)
            self.step(job_id, active_step, "running")
            if job["mode"] == "demo":
                self.event(job_id, "生成程序合成的流程占位音频；不含真实歌声，未处理输入原曲或参考声音。")
                content, mime = synthesize(spec, lambda: self.canceled(job_id)), "audio/wav"
            elif spec["task"] in {"compose", "restyle"}:
                content, mime = self.ace.generate(spec, job["prompt"], source, lambda: self.canceled(job_id), lambda msg: self.event(job_id, msg))
            else:
                self.event(job_id, "已调用歌声转换 Worker，等待分离、转换与混音结果。")
                bundle=self.voice.run_job(spec,source,reference,lambda:self.canceled(job_id),lambda key,msg:self.event(job_id,msg))
                content,mime=bundle.pop("result")
                artifacts.update(bundle)
            self.check_cancel(job_id)
            self.step(job_id, active_step, "succeeded")
            active_step = "validate"
            self.step(job_id, active_step, "running")
            mime, extension = ensure_audio(content, mime)
            metrics = inspect_audio(content)
            self.step(job_id, active_step, "succeeded")
            active_step = "save"
            self.step(job_id, active_step, "running")
            # Cancellation and final publication are atomic relative to the API.
            with self.store.lock:
                self.check_cancel(job_id)
                name = ("DEMO-" if job["mode"] == "demo" else "MusicCraft-") + job_id[:8] + extension
                asset = self.store.create_asset(name, content, mime, role="output", demo=job["mode"] == "demo")
                artifact_ids={}
                for key,(audio,audio_mime) in artifacts.items():
                    checked_mime,ext=ensure_audio(audio,audio_mime)
                    saved=self.store.create_asset(key+"-"+job_id[:8]+ext,audio,checked_mime,role=key)
                    artifact_ids[key]=saved["id"]
                self.step(job_id, active_step, "succeeded")
                self.event(job_id, "已保存独立版本，输入文件与父版本未修改。")
                self.store.update("job", job_id, status="succeeded", output_asset_id=asset["id"], artifacts=artifact_ids,metrics=metrics, finished_at=now())
        except InterruptedError as exc:
            self.step(job_id, active_step, "canceled")
            self.store.update("job", job_id, status="canceled", error=str(exc), finished_at=now())
        except Exception as exc:
            self.step(job_id, active_step, "failed")
            message = str(exc) if isinstance(exc, (ProviderError, ValidationError)) else "任务执行失败，请检查本地控制台或服务日志。"
            self.store.update("job", job_id, status="canceled" if self.canceled(job_id) else "failed", error=message, finished_at=now())
            if not isinstance(exc, (ProviderError, ValidationError)):
                print("Job failed:", type(exc).__name__, file=sys.stderr)

    def close(self):
        self.pool.shutdown(wait=True)
