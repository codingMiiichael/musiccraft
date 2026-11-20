import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env(path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


@dataclass
class Settings:
    data_dir: Path
    mode: str = "demo"
    host: str = "127.0.0.1"
    port: int = 8765
    workers: int = 2
    planner: str = "rules"
    llm_url: str = ""
    llm_key: str = ""
    llm_model: str = ""
    ace_url: str = ""
    ace_key: str = ""
    ace_model: str = ""
    ace_thinking: bool = False
    voice_url: str = ""
    voice_key: str = ""
    provider_timeout: int = 600
    enable_compose: bool = False
    voice_protocol: str = "async"
    ffmpeg: str = "ffmpeg"

    @classmethod
    def from_env(cls):
        load_env(ROOT / ".env")
        s = cls(
            data_dir=Path(os.getenv("MUSICCRAFT_DATA_DIR", str(ROOT / "data"))).resolve(),
            mode=os.getenv("MUSICCRAFT_MODE", "demo"),
            host=os.getenv("MUSICCRAFT_HOST", "127.0.0.1"),
            port=int(os.getenv("MUSICCRAFT_PORT", "8765")),
            workers=int(os.getenv("MUSICCRAFT_WORKERS", "2")),
            planner=os.getenv("MUSICCRAFT_PLANNER", "rules"),
            llm_url=os.getenv("LLM_BASE_URL", "").rstrip("/"),
            llm_key=os.getenv("LLM_API_KEY", ""),
            llm_model=os.getenv("LLM_MODEL", ""),
            ace_url=os.getenv("ACESTEP_BASE_URL", "").rstrip("/"),
            ace_key=os.getenv("ACESTEP_API_KEY", ""),
            ace_model=os.getenv("ACESTEP_MODEL", ""),
            ace_thinking=os.getenv("ACESTEP_THINKING", "false").lower() == "true",
            voice_url=os.getenv("VOICE_WORKER_URL", "").rstrip("/"),
            voice_key=os.getenv("VOICE_WORKER_API_KEY", ""),
            provider_timeout=int(os.getenv("MUSICCRAFT_PROVIDER_TIMEOUT", "600")),
            enable_compose=os.getenv("MUSICCRAFT_ENABLE_COMPOSE", "false").lower() == "true",
            voice_protocol=os.getenv("VOICE_WORKER_PROTOCOL", "async"),
            ffmpeg=os.getenv("MUSICCRAFT_FFMPEG", "ffmpeg"),
        )
        if s.mode not in {"demo", "live"} or s.planner not in {"rules", "llm"}:
            raise ValueError("MODE must be demo/live; PLANNER must be rules/llm")
        if s.voice_protocol not in {"sync", "async"}:
            raise ValueError("VOICE_WORKER_PROTOCOL must be sync/async")
        if s.host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("This prototype must bind to a loopback address.")
        if not 1 <= s.workers <= 4 or not 10 <= s.provider_timeout <= 3600:
            raise ValueError("workers: 1–4; provider timeout: 10–3600 seconds")
        return s

    def public(self):
        return {"mode": self.mode, "planner": self.planner,
                "generation_ready": bool(self.ace_url), "voice_ready": bool(self.voice_url),
                "enable_compose": self.enable_compose,
                "max_upload_mb": 32, "version": "0.2.0"}
