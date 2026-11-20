import json
import shutil
from concurrent.futures import ThreadPoolExecutor

from .providers.transport import ProviderError, headers, request_bytes


def service_status(settings):
    def probe(kind, base, key):
        if not base:
            return {"state":"unconfigured", "message":"尚未配置模型服务"}
        try:
            body, _ = request_bytes(base + "/health", request_headers=headers(key), timeout=3, limit=65536)
            health = json.loads(body)
            if not isinstance(health,dict):
                raise ValueError()
            if kind == "voice" and health.get("ready") is False:
                return {"state":"needs_setup","message":"Worker 可连接，推理依赖尚未就绪", "checks":health.get("checks",{})}
            if kind == "ace" and health.get("data",health).get("status") not in {"ok","healthy"}:
                return {"state":"needs_setup","message":"服务响应正常，但健康状态未通过"}
            return {"state":"connected","message":"服务可连接；实际效果仍需运行样例验证"}
        except (ProviderError, ValueError, TypeError, AttributeError):
            return {"state":"offline","message":"无法确认服务状态，请检查地址、密钥及远端进程"}
    with ThreadPoolExecutor(max_workers=2) as pool:
        ace = pool.submit(probe,"ace",settings.ace_url,settings.ace_key)
        voice = pool.submit(probe,"voice",settings.voice_url,settings.voice_key)
        return {"mode":settings.mode,"ace":ace.result(),"voice":voice.result(),
                "ffmpeg":bool(shutil.which(settings.ffmpeg)),"compose_enabled":settings.enable_compose}
