import copy
import json
import re

from .models import LABELS, TaskSpec, ValidationError
from .providers.transport import ProviderError, request_json

STYLE_WORDS = {"pop": ["流行", "pop"], "guofeng": ["古风", "国风"], "classical": ["古典", "classical"],
               "rock": ["摇滚", "rock"], "jazz": ["爵士", "jazz"], "electronic": ["电子", "electronic"]}
INSTRUMENT_WORDS = {"piano": ["钢琴", "piano"], "guitar": ["吉他", "guitar"], "strings": ["弦乐", "strings"],
                    "drums": ["鼓", "drums"], "bass": ["贝斯", "bass"], "guzheng": ["古筝"],
                    "violin": ["小提琴", "violin"], "flute": ["笛", "flute"]}
TASK_FIELDS = set(TaskSpec.__dataclass_fields__)


def extract_rules(prompt, parent=None):
    p = prompt.lower()
    values = {}
    if any(w in p for w in ["翻唱", "我的声音", "这个声音", "换人声", "换音色", "音色转换", "换成我的"]):
        values["task"] = "voice_cover"
    elif any(w in p for w in ["改编", "改成", "改为", "转换风格", "换风格", "保留旋律"]):
        values["task"] = "restyle"
    else:
        values["task"] = "compose"
    # The last mentioned style generally follows "改成" / "改为".
    positions = [(p.rfind(word), style) for style, words in STYLE_WORDS.items() for word in words if word in p]
    if positions:
        values["style"] = max(positions)[1]
    instruments = list((parent or {}).get("instruments", []))
    added, removed = [], []
    for instrument, words in INSTRUMENT_WORDS.items():
        if any(word in p for word in words):
            if any(re.search(r"(?:不要|去掉|移除|不用|去除)\s*" + re.escape(word), p) for word in words):
                removed.append(instrument)
            else:
                added.append(instrument)
    if added:
        instruments = added
    if added or removed:
        values["instruments"] = [x for x in instruments if x not in removed]
    if any(w in p for w in ["纯音乐", "无人声", "不要人声", "instrumental"]):
        values["vocal"] = "instrumental"
    elif "女声" in p:
        values["vocal"] = "female"
    elif "男声" in p:
        values["vocal"] = "male"
    elif any(w in p for w in ["唱", "填词", "歌词", "有词"]):
        values["vocal"] = "any"
    for word in ["毕业", "爱情", "离别", "夏天", "旅行", "思乡", "治愈", "友情", "梦想"]:
        if word in p:
            values["theme"] = word
            break
    duration = re.search(r"(\d+)\s*(?:秒|seconds?\b)", p)
    bpm = re.search(r"(?:bpm\s*[:：]?\s*(\d+)|(\d+)\s*bpm)", p)
    if duration:
        values["duration"] = int(duration.group(1))
    if bpm:
        values["bpm"] = int(bpm.group(1) or bpm.group(2))
    preserve = [key for key, word in [("melody", "旋律"), ("lyrics", "歌词"), ("accompaniment", "伴奏")]
                if re.search(r"保留(?:原|原有|原来的|原曲的|主)?" + word, p)]
    if preserve:
        values["preserve"] = preserve
    return values


class Planner:
    def __init__(self, settings, store):
        self.settings, self.store = settings, store

    def llm_extract(self, prompt, parent):
        if not self.settings.llm_url or not self.settings.llm_model:
            raise ValidationError("LLM 模式需要配置 LLM_BASE_URL 和 LLM_MODEL")
        schema = TaskSpec().to_dict()
        system = ("你是音乐编辑的任务解析器。只返回 JSON 对象，提取用户本轮明确要求修改的字段，不要补全未指定的字段。"
                  "task只能是compose/restyle/voice_cover；style只能是pop/guofeng/classical/rock/jazz/electronic；"
                  "instruments只能包含piano/guitar/strings/drums/bass/guzheng/violin/flute；"
                  "vocal只能是instrumental/female/male/any；preserve只能包含melody/lyrics/accompaniment。"
                  "duration为10–40整数秒，bpm为40–200整数。可以为用户需要的歌曲撰写lyrics，使用[Verse]/[Chorus]结构。"
                  "不得生成资产ID、文件路径、URL或代码。以下为字段示例，并非默认要求：" + json.dumps(schema, ensure_ascii=False))
        result = request_json(self.settings.llm_url + "/chat/completions", {
            "model": self.settings.llm_model, "temperature": 0.2,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": json.dumps({"previous_spec": parent, "request": prompt}, ensure_ascii=False)}]
        }, self.settings.llm_key, timeout=60)
        try:
            text = result["choices"][0]["message"]["content"].strip()
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
            data = json.loads(text)
            if not isinstance(data, dict):
                raise ValueError()
            return {k: v for k, v in data.items() if k in TASK_FIELDS and k not in {"source_asset_id", "voice_asset_id"}}
        except (KeyError, IndexError, TypeError, ValueError, AttributeError):
            raise ProviderError("LLM 未返回有效任务 JSON，请调整提示词或切换 rules 模式") from None

    def create(self, payload):
        if not isinstance(payload, dict):
            raise ValidationError("请求必须是对象")
        prompt = payload.get("prompt", "")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 4000:
            raise ValidationError("请填写 1–4000 字的创作要求")
        controls = payload.get("controls", {})
        if not isinstance(controls, dict) or set(controls) - TASK_FIELDS:
            raise ValidationError("不支持的表单参数")
        parent = None
        parent_id = payload.get("parent_job_id")
        if parent_id:
            parent = self.store.get("job", parent_id) if isinstance(parent_id, str) else None
            if not parent or parent["status"] != "succeeded":
                raise ValidationError("只能基于已完成版本继续编辑")
        prior = parent["spec"] if parent else None
        values = copy.deepcopy(prior or TaskSpec().to_dict())
        # Preserve constraints describe this operation, not an eternal edit lock.
        values["preserve"] = []
        extracted = self.llm_extract(prompt, prior) if self.settings.planner == "llm" else extract_rules(prompt, prior)
        values.update(extracted)
        values.update({k: v for k, v in controls.items() if v is not None and v != "auto"})
        if values["task"] != "compose" and not parent and "vocal" not in extracted and "vocal" not in controls:
            values["vocal"] = "any"
        if parent and values["task"] != "compose":
            values["source_asset_id"] = controls.get("source_asset_id") or parent["output_asset_id"]
        if values["task"] == "restyle" and not values["preserve"]:
            values["preserve"] = ["melody"]
        if values["task"] == "voice_cover":
            values["preserve"] = ["melody", "lyrics", "accompaniment"]
        lyrics_origin = "用户输入或继承"
        if values["vocal"] != "instrumental" and not values["lyrics"] and values["task"] == "compose":
            if values.get("language", "zh") == "zh":
                theme = values["theme"]
                values["lyrics"] = "[Verse]\n把%s写进晚风里\n沿着灯光慢慢走向你\n[Chorus]\n让这一刻停在旋律里\n把心里的故事唱给你" % theme
            else:
                values["lyrics"] = "[Verse]\nA story carried by the breeze\nA little light among the trees\n[Chorus]\nKeep this moment in a song\nAnd let the melody go on"
            lyrics_origin = "离线示例模板，可在表单中改写"
        spec = TaskSpec.from_dict(values)
        blockers, warnings = [], []
        if spec.task == "compose" and not self.settings.enable_compose:
            blockers.append("作曲当前为暂缓的实验功能，请先使用风格改编或音色翻唱。")
        for field, label in [("source_asset_id", "原曲"), ("voice_asset_id", "音色参考")]:
            asset_id = getattr(spec, field)
            required = (field == "source_asset_id" and spec.task != "compose") or (field == "voice_asset_id" and spec.task == "voice_cover")
            asset = self.store.get("asset", asset_id) if asset_id else None
            if required and not asset:
                blockers.append("请上传或选择" + label)
            elif asset_id and not asset:
                blockers.append(label + "素材不存在")
            elif required and asset and self.settings.mode == "live" and asset.get("demo"):
                blockers.append(label + "是演示素材，请替换为真实录音后使用真实模型")
        if self.settings.mode == "demo":
            warnings.append("演示模式：输出为程序合成的短旋律，不处理原曲、不克隆声音、不包含真实歌声。")
        elif spec.task in {"compose", "restyle"} and not self.settings.ace_url:
            blockers.append("请配置 ACESTEP_BASE_URL")
        elif spec.task == "voice_cover" and not self.settings.voice_url:
            blockers.append("歌声转换 Worker 尚未接入，请配置 VOICE_WORKER_URL")
        if spec.task == "restyle":
            warnings.append("改编属于整段重新生成；旋律保留是软约束，不保证逐音符一致。")
            if "lyrics" in spec.preserve and not spec.lyrics:
                blockers.append("保留歌词需要在更多选项中粘贴原歌词；当前未接入自动歌词转写。")
            warnings.append("将先按起点和时长截取原曲，再执行整段风格改编。旋律约束强度可调。")
        if spec.task != "voice_cover" and "accompaniment" in spec.preserve:
            blockers.append("当前生成路线不能严格保留伴奏音轨；请取消保留伴奏，或选择音色翻唱。")
        if re.search(r"(?:只|仅).*(?:钢琴|吉他).*(?:换成|替换|改成)", prompt) and spec.task != "voice_cover":
            blockers.append("精确替换单一乐器尚未实现；可改为整体风格改编。")
        if spec.task == "voice_cover":
            warnings.append("使用参考音色；演唱旋律与节奏来自原唱，目标音色及音质需实际试听。")
        steps = [{"key": "prepare", "label": "检查素材与任务约束"}]
        if spec.task == "compose":
            steps.append({"key": "generate", "label": "音乐生成"})
        elif spec.task == "restyle":
            steps.append({"key": "restyle", "label": "参考音频风格改编"})
        else:
            steps.append({"key": "voice", "label": "歌声管线：分离 → 音色转换 → 混音"})
        steps.extend([{"key": "validate", "label": "检查输出音频"}, {"key": "save", "label": "保存新版本"}])
        return self.store.put("plan", {"prompt": prompt.strip(), "spec": spec.to_dict(), "parent_job_id": parent_id,
            "mode": self.settings.mode, "planner": self.settings.planner, "steps": steps, "warnings": warnings,
            "blockers": blockers, "lyrics_origin": lyrics_origin,
            "summary": "%s · %s · %s · %s 秒" % (LABELS[spec.task], LABELS[spec.style], LABELS[spec.vocal], spec.duration)})
