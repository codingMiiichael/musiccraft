import json
import mimetypes
import urllib.error
import urllib.parse
import urllib.request
import uuid

MAX_AUDIO = 64 * 1024 * 1024


class ProviderError(RuntimeError):
    pass


def headers(key=""):
    return {"Authorization": "Bearer " + key} if key else {}


class SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, response_headers, new_url):
        old = urllib.parse.urlsplit(req.full_url)
        new = urllib.parse.urlsplit(new_url)
        if (old.scheme, old.netloc) != (new.scheme, new.netloc):
            raise ProviderError("模型服务尝试跨来源重定向，已阻止")
        return super().redirect_request(req, fp, code, msg, response_headers, new_url)


def request_bytes(url, data=None, request_headers=None, timeout=60, limit=MAX_AUDIO):
    if urllib.parse.urlsplit(url).scheme not in {"http", "https"}:
        raise ProviderError("服务地址必须使用 http 或 https")
    req = urllib.request.Request(url, data=data, headers=request_headers or {})
    try:
        opener = urllib.request.build_opener(SameOriginRedirectHandler())
        with opener.open(req, timeout=timeout) as response:
            body = response.read(limit + 1)
            if len(body) > limit:
                raise ProviderError("服务返回文件超过大小限制")
            return body, response.headers.get("Content-Type", "application/octet-stream")
    except urllib.error.HTTPError as exc:
        # Never expose provider response bodies: they may contain credentials or paths.
        raise ProviderError("模型服务返回 HTTP %s，请检查服务端日志" % exc.code) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ProviderError("无法连接模型服务或请求超时，请检查地址、网络和服务日志") from None


def request_json(url, payload, key="", timeout=60):
    h = headers(key)
    h["Content-Type"] = "application/json"
    body, _ = request_bytes(url, json.dumps(payload).encode(), h, timeout, limit=2 * 1024 * 1024)
    try:
        result = json.loads(body)
    except (ValueError, UnicodeError):
        raise ProviderError("模型服务未返回有效 JSON") from None
    if not isinstance(result, dict):
        raise ProviderError("模型服务返回格式错误")
    return result


def multipart(fields, files):
    """files: field -> (safe filename, bytes, MIME). No filesystem paths on the wire."""
    boundary = "MusicCraft" + uuid.uuid4().hex
    body = bytearray()
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, (dict, list, bool)):
            value = json.dumps(value, ensure_ascii=False)
        body.extend(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (boundary, key, value)).encode())
    for key, (name, content, mime) in files.items():
        safe = "audio" + ("." + name.rsplit(".", 1)[-1] if "." in name else ".wav")
        body.extend(("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\nContent-Type: %s\r\n\r\n" % (boundary, key, safe, mime)).encode())
        body.extend(content)
        body.extend(b"\r\n")
    body.extend(("--%s--\r\n" % boundary).encode())
    return bytes(body), "multipart/form-data; boundary=" + boundary


def same_origin_url(base, reference):
    url = urllib.parse.urljoin(base.rstrip("/") + "/", reference)
    a, b = urllib.parse.urlsplit(base), urllib.parse.urlsplit(url)
    if (a.scheme, a.netloc) != (b.scheme, b.netloc):
        raise ProviderError("拒绝下载不同来源的音频地址")
    return url


def ensure_audio(content, mime):
    """Reject HTML/JSON error pages masquerading as an output audio file."""
    sniffed = (content.startswith(b"RIFF") and content[8:12] == b"WAVE") or content.startswith((b"fLaC", b"OggS", b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"))
    if not content or not sniffed:
        raise ProviderError("模型服务未返回可识别的 WAV / FLAC / OGG / MP3 音频")
    if content.startswith(b"RIFF"):
        return "audio/wav", ".wav"
    if content.startswith(b"fLaC"):
        return "audio/flac", ".flac"
    if content.startswith(b"OggS"):
        return "audio/ogg", ".ogg"
    return "audio/mpeg", ".mp3"
