import io
import json
import tempfile
import time
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from musiccraft.config import Settings
from musiccraft.engine import Engine, inspect_audio
from musiccraft.models import TaskSpec, ValidationError
from musiccraft.planner import Planner
from musiccraft.providers.acestep import AceStepProvider
from musiccraft.providers.demo import synthesize
from musiccraft.providers.transport import ProviderError, ensure_audio, same_origin_url
from musiccraft.providers.voice_worker import VoiceWorkerProvider
from musiccraft.store import Store


def wait_job(store, job_id):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        job = store.get("job", job_id)
        if job["status"] in {"succeeded", "failed", "canceled"}:
            return job
        time.sleep(0.02)
    raise AssertionError("Job did not finish")


class StudioTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = Settings(data_dir=Path(self.temp.name),enable_compose=True)
        self.store = Store(self.settings.data_dir)
        self.planner = Planner(self.settings, self.store)
        self.engine = Engine(self.settings, self.store)

    def tearDown(self):
        self.engine.close()
        self.temp.cleanup()

    def create(self, prompt="写一段关于毕业的钢琴纯音乐，10秒", **kwargs):
        return self.planner.create(dict(prompt=prompt, **kwargs))

    def test_validation_rejects_bool_duration_and_unknown_fields(self):
        for data in [{"duration":True}, {"duration":41}, {"style":"unknown"}, {"task":[]}, {"language":[]}, {"path":"/tmp/x"}]:
            with self.subTest(data=data), self.assertRaises(ValidationError):
                TaskSpec.from_dict(data)

    def test_instrumental_drops_lyrics(self):
        self.assertEqual(TaskSpec.from_dict({"lyrics":"should not be sung"}).lyrics, "")

    def test_rules_extract_chinese_request(self):
        plan = self.create("写一首关于毕业的流行歌曲，温柔女声，木吉他，30秒，100 BPM")
        s = plan["spec"]
        self.assertEqual((s["style"],s["vocal"],s["instruments"],s["duration"],s["bpm"]), ("pop","female",["guitar"],30,100))
        self.assertIn("[Verse]", s["lyrics"])

    def test_form_overrides_text(self):
        plan = self.create("钢琴古风纯音乐，10秒", controls={"style":"rock","duration":20,"instruments":["guitar"]})
        self.assertEqual(plan["spec"]["style"], "rock")
        self.assertEqual(plan["spec"]["duration"], 20)

    def test_llm_cannot_inject_asset_ids_and_form_values_win(self):
        self.settings.planner = "llm"
        self.settings.llm_url = "http://localhost:9000/v1"
        self.settings.llm_model = "test-model"
        output = {"choices":[{"message":{"content":json.dumps({"style":"jazz","source_asset_id":"injected"})}}]}
        with patch("musiccraft.planner.request_json",return_value=output):
            plan = self.create("音乐",controls={"style":"rock"})
        self.assertEqual(plan["spec"]["style"],"rock")
        self.assertEqual(plan["spec"]["source_asset_id"],"")

    def test_invalid_llm_json_is_an_explicit_error(self):
        self.settings.planner = "llm"
        self.settings.llm_url = "http://localhost:9000/v1"
        self.settings.llm_model = "test-model"
        with patch("musiccraft.planner.request_json",return_value={"choices":[{"message":{"content":"not JSON"}}]}):
            with self.assertRaises(ProviderError):
                self.create("音乐")

    def test_negation_removes_instrument(self):
        plan = self.create("不要钢琴，改用吉他")
        self.assertEqual(plan["spec"]["instruments"], ["guitar"])

    def test_missing_voice_inputs_block_execution(self):
        plan = self.create("用我的声音翻唱")
        self.assertEqual(len(plan["blockers"]),2)
        with self.assertRaises(ValidationError):
            self.engine.submit(plan["id"])

    def test_demo_completes_and_plan_submission_is_idempotent(self):
        plan = self.create()
        job = self.engine.submit(plan["id"])
        second = self.engine.submit(plan["id"])
        self.assertEqual(job["id"], second["id"])
        result = wait_job(self.store,job["id"])
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["metrics"]["duration_seconds"],10)
        self.assertTrue(self.store.get("asset",result["output_asset_id"])["demo"])
        self.assertTrue(all(step["status"] == "succeeded" for step in result["steps"]))

    def test_parent_inheritance_does_not_mutate_parent(self):
        parent = wait_job(self.store,self.engine.submit(self.create()["id"])["id"])
        snapshot = self.store.get("job", parent["id"])
        plan = self.create("保留主旋律，改成木吉他爵士风格",parent_job_id=parent["id"])
        self.assertEqual(plan["spec"]["source_asset_id"],parent["output_asset_id"])
        self.assertEqual(plan["spec"]["style"],"jazz")
        self.assertEqual(plan["spec"]["theme"],"毕业")
        self.assertEqual(self.store.get("job",parent["id"]),snapshot)

    def test_live_does_not_accept_demo_inputs(self):
        asset = self.store.create_asset("demo.wav",b"x","audio/wav",demo=True)
        self.settings.mode = "live"
        self.settings.ace_url = "http://localhost:8001"
        plan = self.create("改成流行风格",controls={"source_asset_id":asset["id"]})
        self.assertTrue(any("演示素材" in x for x in plan["blockers"]))

    def test_exact_accompaniment_is_blocked_for_regeneration(self):
        plan = self.create("保留伴奏，改成摇滚风格")
        self.assertTrue(any("严格保留" in x for x in plan["blockers"]))

    def test_exact_instrument_edit_is_not_silently_restyled(self):
        plan = self.create("只把钢琴换成吉他")
        self.assertTrue(any("单一乐器" in x for x in plan["blockers"]))

    def test_no_lyric_preservation_claim_without_lyrics(self):
        plan = self.create("改成流行风格，保留歌词")
        self.assertTrue(any("粘贴原歌词" in x for x in plan["blockers"]))

    def test_restart_marks_unfinished_jobs(self):
        job = self.store.put("job",{"status":"running"})
        self.store.interrupt_old_jobs()
        self.assertEqual(self.store.get("job",job["id"])["status"],"failed")

    def test_asset_paths_cannot_escape_root(self):
        with self.assertRaises(ValueError):
            self.store.asset_path({"filename":"../../secret.wav"})

    def test_no_live_fallback_to_demo_on_provider_failure(self):
        self.settings.mode = "live"
        self.settings.ace_url = "http://localhost:8001"
        with patch.object(self.engine.ace,"generate",side_effect=ProviderError("provider down")):
            result = wait_job(self.store,self.engine.submit(self.create()["id"])["id"])
        self.assertEqual(result["status"],"failed")
        self.assertIsNone(result["output_asset_id"])

    def test_running_job_can_be_canceled(self):
        self.settings.mode = "live"
        self.settings.ace_url = "http://localhost:8001"
        def slow(spec,prompt,source,canceled,progress):
            while not canceled():
                time.sleep(0.01)
            raise InterruptedError("Canceled")
        with patch.object(self.engine.ace,"generate",side_effect=slow):
            job = self.engine.submit(self.create()["id"])
            self.engine.cancel(job["id"])
            result = wait_job(self.store,job["id"])
        self.assertEqual(result["status"],"canceled")


class ProviderTest(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(data_dir=Path("unused"),mode="live",ace_url="http://localhost:8001")
        self.provider = AceStepProvider(self.settings)

    def test_ace_async_success_downloads_audio(self):
        spec = TaskSpec().to_dict()
        replies = [{"data":{"task_id":"remote-123"}}, {"data":[{"status":1,"result":json.dumps([{"file":"/v1/audio?path=result.wav"}])}]}]
        wav = synthesize({"duration":1})
        with patch("musiccraft.providers.acestep.request_json",side_effect=replies) as send, patch("musiccraft.providers.acestep.request_bytes",return_value=(wav,"audio/wav")):
            content, _ = self.provider.generate(spec,"test")
        self.assertEqual(content,wav)
        self.assertEqual(send.call_args_list[0].args[1]["batch_size"],1)
        self.assertEqual(send.call_args_list[1].args[1],{"task_id_list":["remote-123"]})

    def test_ace_cover_uploads_audio_instead_of_local_path(self):
        spec = TaskSpec(task="restyle").to_dict()
        replies = [(b'{"data":{"task_id":"r"}}',"application/json"),(synthesize({"duration":1}),"audio/wav")]
        with patch("musiccraft.providers.acestep.request_bytes",side_effect=replies) as send, patch("musiccraft.providers.acestep.request_json",return_value={"data":[{"status":1,"result":[{"file":"/v1/audio?path=x"}]}]}):
            self.provider.generate(spec,"cover",("song.wav",b"SOURCE_AUDIO_BYTES","audio/wav"))
        submitted = send.call_args_list[0].args[1]
        self.assertIn(b'name="src_audio"',submitted)
        self.assertIn(b"SOURCE_AUDIO_BYTES",submitted)
        self.assertNotIn(b"src_audio_path",submitted)

    def test_ace_failed_remote_job_is_error(self):
        with patch("musiccraft.providers.acestep.request_json",side_effect=[{"data":{"task_id":"r"}},{"data":[{"status":2}]}]):
            with self.assertRaises(ProviderError):
                self.provider.generate(TaskSpec().to_dict(),"test")

    def test_cross_origin_audio_is_rejected(self):
        with self.assertRaises(ProviderError):
            same_origin_url("http://localhost:8001","https://untrusted.example/audio")

    def test_voice_worker_upload_contract(self):
        self.settings.voice_url = "http://localhost:8010"
        self.settings.voice_key = "test-key"
        worker = VoiceWorkerProvider(self.settings)
        with patch("musiccraft.providers.voice_worker.request_bytes",return_value=(b"wav","audio/wav")) as send:
            worker.convert(TaskSpec(task="voice_cover").to_dict(),("song.wav",b"SOURCE","audio/wav"),("voice.wav",b"REFERENCE","audio/wav"))
        url,body,h = send.call_args.args
        self.assertEqual(url,"http://localhost:8010/v1/voice-cover")
        self.assertIn(b'name="source"',body)
        self.assertIn(b'name="reference"',body)
        self.assertEqual(h["Authorization"],"Bearer test-key")

    def test_error_page_is_not_accepted_as_music(self):
        with self.assertRaises(ProviderError):
            ensure_audio(b"<html>Error</html>","audio/wav")

    def test_fixture_is_playable_wav_not_fake_extension(self):
        content = synthesize({"duration":1})
        with wave.open(io.BytesIO(content),"rb") as wav:
            self.assertEqual(wav.getnframes(),16000)
        self.assertGreater(inspect_audio(content)["rms"],0)


if __name__ == "__main__":
    unittest.main()
