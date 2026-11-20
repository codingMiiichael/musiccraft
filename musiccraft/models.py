from dataclasses import asdict, dataclass, field, fields
import math

TASKS = {"compose", "restyle", "voice_cover"}
STYLES = {"pop", "guofeng", "classical", "rock", "jazz", "electronic"}
INSTRUMENTS = {"piano", "guitar", "strings", "drums", "bass", "guzheng", "violin", "flute"}
VOCALS = {"instrumental", "female", "male", "any"}
PRESERVE = {"melody", "lyrics", "accompaniment"}
LABELS = {"compose": "灵感作曲", "restyle": "风格改编", "voice_cover": "音色翻唱",
          "pop": "流行", "guofeng": "古风", "classical": "古典", "rock": "摇滚", "jazz": "爵士", "electronic": "电子",
          "piano": "钢琴", "guitar": "木吉他", "strings": "弦乐", "drums": "鼓", "bass": "贝斯",
          "guzheng": "古筝", "violin": "小提琴", "flute": "笛子",
          "instrumental": "纯音乐", "female": "女声", "male": "男声", "any": "不限人声",
          "melody": "主旋律", "lyrics": "歌词", "accompaniment": "伴奏"}


class ValidationError(ValueError):
    pass


@dataclass
class TaskSpec:
    task: str = "compose"
    style: str = "pop"
    instruments: list = field(default_factory=lambda: ["piano"])
    vocal: str = "instrumental"
    theme: str = "自由创作"
    lyrics: str = ""
    duration: int = 20
    bpm: int = 90
    seed: int = 42
    language: str = "zh"
    preserve: list = field(default_factory=list)
    source_asset_id: str = ""
    voice_asset_id: str = ""
    clip_start: float = 0
    cover_strength: float = 0.65
    vocal_gain_db: float = 0

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise ValidationError("任务参数必须是对象")
        known = {f.name for f in fields(cls)}
        unknown = set(value) - known
        if unknown:
            raise ValidationError("未知参数：" + ", ".join(sorted(unknown)))
        spec = cls(**value)
        for name, choices in [("task", TASKS), ("style", STYLES), ("vocal", VOCALS)]:
            if not isinstance(getattr(spec, name), str) or getattr(spec, name) not in choices:
                raise ValidationError("不支持的 " + name)
        for name, lo, hi in [("duration", 10, 40), ("bpm", 40, 200), ("seed", 0, 2147483647)]:
            v = getattr(spec, name)
            if type(v) is not int or not lo <= v <= hi:
                raise ValidationError("%s 必须是 %s–%s 的整数" % (name, lo, hi))
        for name, lo, hi in [("clip_start", 0, 3600), ("cover_strength", 0, 1), ("vocal_gain_db", -12, 6)]:
            v = getattr(spec, name)
            if type(v) not in {int, float} or not math.isfinite(v) or not lo <= v <= hi:
                raise ValidationError("%s 必须介于 %s 和 %s" % (name, lo, hi))
        for name, choices, maximum in [("instruments", INSTRUMENTS, 8), ("preserve", PRESERVE, 3)]:
            v = getattr(spec, name)
            if not isinstance(v, list) or len(v) > maximum or any(not isinstance(x, str) or x not in choices for x in v):
                raise ValidationError("无效的 " + name)
            setattr(spec, name, list(dict.fromkeys(v)))
        for name, limit in [("theme", 100), ("lyrics", 5000), ("source_asset_id", 64), ("voice_asset_id", 64)]:
            if not isinstance(getattr(spec, name), str) or len(getattr(spec, name)) > limit:
                raise ValidationError("无效的 " + name)
        if not isinstance(spec.language, str) or spec.language not in {"zh", "en", "ja"}:
            raise ValidationError("语言仅支持 zh/en/ja")
        if spec.vocal == "instrumental":
            spec.lyrics = ""
        return spec

    def to_dict(self):
        return asdict(self)
