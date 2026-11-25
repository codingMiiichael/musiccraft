"""Deterministic synthetic fixtures. This is deliberately NOT an AI music model."""
import io
import math
import random
import struct
import wave


def synthesize(spec, canceled=lambda: False):
    sample_rate = 16000
    duration = spec.get("duration", 20)
    rng = random.Random(spec.get("seed", 42))
    scale = [60, 62, 64, 67, 69, 72] if spec.get("style") == "guofeng" else [60, 62, 64, 65, 67, 69, 71, 72]
    notes = [rng.choice(scale) for _ in range(64)]
    guitar = "guitar" in spec.get("instruments", [])
    bpm = spec.get("bpm", 90)
    beat = 60.0 / bpm
    pcm = bytearray()
    for n in range(sample_rate * duration):
        if n % sample_rate == 0 and canceled():
            raise InterruptedError("任务已取消")
        t = n / sample_rate
        index = int(t / (beat / 2))
        local = t % (beat / 2)
        frequency = 440 * 2 ** ((notes[index % len(notes)] - 69) / 12)
        env = min(1.0, local / 0.015) * math.exp(-local * (10 if guitar else 5))
        tone = math.sin(2 * math.pi * frequency * t)
        tone += (0.28 if guitar else 0.12) * math.sin(4 * math.pi * frequency * t)
        root = [130.81, 110, 87.31, 98][int(t / (beat * 4)) % 4]
        pad = sum(math.sin(2 * math.pi * root * ratio * t) for ratio in (1, 1.25, 1.5)) / 3
        fade = min(1.0, t / 0.15, (duration - t) / 0.4)
        value = (0.36 * tone * env + 0.12 * pad) * fade
        pcm.extend(struct.pack("<h", max(-32767, min(32767, int(value * 32767)))))
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return out.getvalue()
