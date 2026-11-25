import argparse
import json
import mimetypes
import re
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import ROOT, Settings
from .engine import Engine
from .models import ValidationError
from .planner import Planner
from .providers.demo import synthesize
from .providers.transport import ProviderError
from .store import Store
from .services import service_status

MAX_UPLOAD = 32 * 1024 * 1024


class Application:
    def __init__(self, settings):
        self.settings = settings
        self.store = Store(settings.data_dir)
        self.store.interrupt_old_jobs()
        self.planner = Planner(settings, self.store)
        self.engine = Engine(settings, self.store)

    def demo_assets(self):
        if self.settings.mode != "demo":
            raise ValidationError("真实模式不提供演示素材")
        source = self.store.create_asset("演示旋律.wav", synthesize({"duration": 20, "seed": 17}), "audio/wav", demo=True)
        voice = self.store.create_asset("参考占位音-非真人.wav", synthesize({"duration": 3, "seed": 5}), "audio/wav", role="voice", demo=True)
        return {"source": source, "voice": voice}

    def pin(self,job_id):
        job=self.store.get("job",job_id)
        if not job or job["status"]!="succeeded":raise ValidationError("只能收藏已完成结果")
        # Pinning does not change provenance or generate audio.
        return self.store.put("showcase",{"id":"showcase-"+job["id"],"job_id":job["id"],"title":job["title"],
                          "mode":job["mode"],"origin":"历史真实结果" if job["mode"]=="live" else "流程演示占位"})


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        server_version = "MusicCraft/0.2"

        def end_headers(self):
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "same-origin")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'")
            super().end_headers()

        def json_response(self, value, status=200):
            data = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def body(self, limit=64 * 1024):
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                raise ValidationError("无效的请求长度") from None
            if length < 1 or length > limit:
                raise ValidationError("请求为空或超过大小限制")
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValidationError("上传未完成")
            return raw

        def json_body(self):
            try:
                value = json.loads(self.body())
            except (ValueError, UnicodeError):
                raise ValidationError("无效的 JSON 请求") from None
            if not isinstance(value, dict):
                raise ValidationError("请求必须是对象")
            return value

        def local_request(self):
            host = self.headers.get("Host", "")
            hostname = urllib.parse.urlsplit("http://" + host).hostname
            if hostname not in {"127.0.0.1", "localhost", "::1"}:
                return False
            origin = self.headers.get("Origin")
            return not origin or origin in {"http://" + host, "https://" + host}

        def do_GET(self):
            if not self.local_request():
                return self.json_response({"error": "仅允许本地同源访问"}, 403)
            path = urllib.parse.urlsplit(self.path).path
            try:
                if path == "/api/config":
                    return self.json_response(app.settings.public())
                if path == "/api/services":
                    return self.json_response(service_status(app.settings))
                if path == "/api/showcases":
                    return self.json_response({"showcases":app.store.list("showcase")})
                if path == "/api/jobs":
                    return self.json_response({"jobs": app.store.list("job")})
                if path == "/api/assets":
                    return self.json_response({"assets": app.store.list("asset")})
                match = re.fullmatch(r"/api/jobs/([a-f0-9]{32})", path)
                if match:
                    job = app.store.get("job", match[1])
                    return self.json_response(job if job else {"error": "任务不存在"}, 200 if job else 404)
                match = re.fullmatch(r"/api/assets/([a-f0-9]{32})/audio", path)
                if match:
                    asset = app.store.get("asset", match[1])
                    if not asset:
                        return self.json_response({"error": "素材不存在"}, 404)
                    return self.serve_file(app.store.asset_path(asset), asset["mime"], audio=True)
                static = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css", "/favicon.svg": "favicon.svg"}
                if path in static:
                    return self.serve_file(ROOT / "web" / static[path], mimetypes.guess_type(static[path])[0] or "application/octet-stream")
                return self.json_response({"error": "Not found"}, 404)
            except (BrokenPipeError, ConnectionResetError):
                return
            except OSError:
                return self.json_response({"error": "文件暂不可用"}, 404)

        def serve_file(self, path, mime, audio=False):
            size = path.stat().st_size
            start, end, status = 0, size - 1, 200
            range_header = self.headers.get("Range") if audio else None
            if range_header:
                match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header)
                if not match or not any(match.groups()):
                    return self.range_error(size)
                if match[1]:
                    start = int(match[1])
                    end = min(int(match[2]), end) if match[2] else end
                else:
                    start = max(0, size - int(match[2]))
                if start >= size or start > end:
                    return self.range_error(size)
                status = 206
            self.send_response(status)
            self.send_header("Content-Type", mime + ("; charset=utf-8" if mime.startswith("text/") or mime in {"application/javascript"} else ""))
            self.send_header("Content-Length", str(end - start + 1))
            if audio:
                self.send_header("Accept-Ranges", "bytes")
                if status == 206:
                    self.send_header("Content-Range", "bytes %s-%s/%s" % (start, end, size))
            self.end_headers()
            with path.open("rb") as f:
                f.seek(start)
                remaining = end - start + 1
                while remaining:
                    chunk = f.read(min(65536, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)

        def range_error(self, size):
            self.send_response(416)
            self.send_header("Content-Range", "bytes */" + str(size))
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_POST(self):
            if not self.local_request() or self.headers.get("X-MusicCraft") != "1":
                return self.json_response({"error": "请从本地工作台发起请求，或设置 X-MusicCraft: 1"}, 403)
            path = urllib.parse.urlsplit(self.path).path
            try:
                if path == "/api/assets":
                    raw = self.body(MAX_UPLOAD)
                    filename = urllib.parse.unquote(self.headers.get("X-Filename", "upload.wav"))
                    role = self.headers.get("X-Asset-Role", "source")
                    if role not in {"source", "voice"}:
                        raise ValidationError("不支持的素材类型")
                    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
                    if not mime.startswith("audio/") and Path(filename).suffix.lower() != ".webm":
                        raise ValidationError("请上传音频文件")
                    asset = app.store.create_asset(filename, raw, mime, role=role)
                    return self.json_response(asset, 201)
                if path == "/api/demo-assets":
                    return self.json_response(app.demo_assets(), 201)
                if path == "/api/plans":
                    return self.json_response(app.planner.create(self.json_body()), 201)
                if path == "/api/jobs":
                    body = self.json_body()
                    if not isinstance(body.get("plan_id"), str):
                        raise ValidationError("缺少 plan_id")
                    return self.json_response(app.engine.submit(body["plan_id"]), 202)
                match = re.fullmatch(r"/api/jobs/([a-f0-9]{32})/cancel", path)
                if match:
                    return self.json_response(app.engine.cancel(match[1]))
                match=re.fullmatch(r"/api/jobs/([a-f0-9]{32})/pin",path)
                if match:return self.json_response(app.pin(match[1]),201)
                return self.json_response({"error": "Not found"}, 404)
            except (ValidationError, ValueError) as exc:
                return self.json_response({"error": str(exc)}, 400)
            except ProviderError as exc:
                return self.json_response({"error": str(exc)}, 502)
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception as exc:
                print("Request failed:", type(exc).__name__)
                return self.json_response({"error": "服务内部错误，请查看控制台"}, 500)

        def log_message(self, fmt, *args):
            # No body, asset name or provider credentials are logged.
            pass

    return Handler


def create_server(settings):
    app = Application(settings)
    server = ThreadingHTTPServer((settings.host, settings.port), make_handler(app))
    server.daemon_threads = True
    return app, server


def main():
    settings = Settings.from_env()
    parser = argparse.ArgumentParser(description="MusicCraft local studio")
    parser.add_argument("--port", type=int, default=settings.port)
    args = parser.parse_args()
    settings.port = args.port
    app, server = create_server(settings)
    print("MusicCraft: http://%s:%s  | audio=%s | planner=%s" % (settings.host, server.server_port, settings.mode, settings.planner), flush=True)
    print("Ctrl+C to stop. Audio files and SQLite are stored in:", settings.data_dir, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping; remote requests may still be running.", flush=True)
    finally:
        server.server_close()
        for job in app.store.list("job", 10000):
            if job["status"] in {"queued", "running"}:
                app.engine.cancel(job["id"])
        app.engine.close()


if __name__ == "__main__":
    main()
