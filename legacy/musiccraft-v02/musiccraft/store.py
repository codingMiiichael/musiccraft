import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


def new_id():
    return uuid.uuid4().hex


class Store:
    """Small JSON record store. Lock covers read/modify/write across job threads."""
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.assets_dir = self.root / "assets"
        self.assets_dir.mkdir(exist_ok=True)
        self.db = self.root / "studio.sqlite3"
        self.lock = threading.RLock()
        with self.connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, kind TEXT NOT NULL, created TEXT NOT NULL, payload TEXT NOT NULL)")
            conn.execute("CREATE INDEX IF NOT EXISTS records_kind ON records(kind, created)")

    def connect(self):
        return sqlite3.connect(str(self.db), timeout=30)

    def put(self, kind, record):
        record = dict(record)
        record.setdefault("id", new_id())
        record.setdefault("created_at", now())
        with self.lock, self.connect() as conn:
            conn.execute("INSERT OR REPLACE INTO records VALUES (?, ?, ?, ?)",
                         (record["id"], kind, record["created_at"], json.dumps(record, ensure_ascii=False)))
        return record

    def get(self, kind, record_id):
        with self.connect() as conn:
            row = conn.execute("SELECT payload FROM records WHERE id=? AND kind=?", (record_id, kind)).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, kind, limit=100):
        with self.connect() as conn:
            rows = conn.execute("SELECT payload FROM records WHERE kind=? ORDER BY created DESC LIMIT ?", (kind, limit)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def update(self, kind, record_id, **changes):
        with self.lock:
            record = self.get(kind, record_id)
            if record is None:
                raise KeyError(record_id)
            record.update(changes)
            record["updated_at"] = now()
            return self.put(kind, record)

    def create_asset(self, name, content, mime, role="source", demo=False):
        asset_id = new_id()
        name = Path(name).name[:180]
        suffix = Path(name).suffix.lower()
        if suffix not in {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".webm"}:
            raise ValueError("支持 WAV / MP3 / FLAC / OGG / M4A / WebM")
        filename = asset_id + suffix
        (self.assets_dir / filename).write_bytes(content)
        return self.put("asset", {"id": asset_id, "name": name, "filename": filename,
                    "mime": mime, "role": role, "demo": demo, "size": len(content), "url": "/api/assets/" + asset_id + "/audio"})

    def asset_path(self, asset):
        path = (self.assets_dir / asset["filename"]).resolve()
        if path.parent != self.assets_dir.resolve():
            raise ValueError("Invalid asset path")
        return path

    def interrupt_old_jobs(self):
        # A local restart cannot safely resume a remote paid request automatically.
        with self.connect() as conn:
            rows = conn.execute("SELECT payload FROM records WHERE kind='job'").fetchall()
        for row in rows:
            job = json.loads(row[0])
            if job["status"] in {"queued", "running", "canceling"}:
                self.update("job", job["id"], status="failed", error="服务已重启，任务中断；请检查远端任务后手动重试。")
