"""Audio clipping for a reproducible before/after comparison."""
import io
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

from .models import ValidationError


def clip_audio(source, start, duration, ffmpeg="ffmpeg"):
    name, content, mime = source
    try:
        with wave.open(io.BytesIO(content), "rb") as original:
            if original.getcomptype() != "NONE":
                raise wave.Error("compressed")
            if start >= original.getnframes() / original.getframerate():
                raise ValidationError("片段起点超出原曲时长")
            original.setpos(int(start * original.getframerate()))
            data = original.readframes(int(duration * original.getframerate()))
            out = io.BytesIO()
            with wave.open(out, "wb") as clipped:
                clipped.setparams(original.getparams())
                clipped.writeframes(data)
            return ("source-clip.wav", out.getvalue(), "audio/wav")
    except (wave.Error, EOFError):
        pass
    executable = shutil.which(ffmpeg)
    if not executable:
        raise ValidationError("此音频需要 FFmpeg 解码。请安装 FFmpeg，或先上传 PCM WAV 格式的短片段。")
    with tempfile.TemporaryDirectory(prefix="musiccraft-clip-") as folder:
        path = Path(folder)
        source_file = path / ("input" + Path(name).suffix)
        source_file.write_bytes(content)
        target = path / "clip.wav"
        try:
            subprocess.run([executable,"-nostdin","-v","error","-y","-ss",str(start),"-i",str(source_file),
                            "-t",str(duration),"-vn","-ar","44100","-ac","2","-c:a","pcm_s16le",str(target)],
                           capture_output=True, timeout=60, check=True)
            if not target.exists() or target.stat().st_size < 100:
                raise ValidationError("无法提取音频片段，请检查起点和原曲格式")
            return ("source-clip.wav", target.read_bytes(), "audio/wav")
        except (subprocess.SubprocessError, OSError):
            raise ValidationError("音频解码失败，请检查文件或上传 PCM WAV") from None
