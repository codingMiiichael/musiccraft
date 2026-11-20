import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from musiccraft.config import Settings
from musiccraft.server import create_server
from tests.test_core import wait_job


class HTTPTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.app, cls.server = create_server(Settings(data_dir=Path(cls.temp.name),port=0,enable_compose=True))
        cls.thread = threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.base = "http://127.0.0.1:" + str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.app.engine.close()
        cls.thread.join()
        cls.temp.cleanup()

    def call(self,path,payload=None,headers=None,raw=None):
        h = {"X-MusicCraft":"1"}
        h.update(headers or {})
        data = raw if raw is not None else json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(self.base+path,data=data,headers=h)
        with urllib.request.urlopen(req,timeout=10) as response:
            return response.status,response.headers,response.read()

    def test_full_plan_job_audio_and_range_flow(self):
        status,_,body = self.call("/api/plans",{"prompt":"写一段10秒的钢琴纯音乐"})
        self.assertEqual(status,201)
        plan = json.loads(body)
        status,_,body = self.call("/api/jobs",{"plan_id":plan["id"]})
        self.assertEqual(status,202)
        job = wait_job(self.app.store,json.loads(body)["id"])
        status,headers,audio = self.call("/api/assets/"+job["output_asset_id"]+"/audio")
        self.assertEqual(status,200)
        self.assertTrue(audio.startswith(b"RIFF"))
        self.assertEqual(headers["Content-Type"],"audio/wav")
        status,headers,chunk = self.call("/api/assets/"+job["output_asset_id"]+"/audio",headers={"Range":"bytes=0-43"})
        self.assertEqual(status,206)
        self.assertEqual(len(chunk),44)

    def test_config_does_not_expose_credentials(self):
        _,_,body = self.call("/api/config")
        self.assertNotIn("key",body.decode().lower())

    def test_mutations_require_custom_header(self):
        req = urllib.request.Request(self.base+"/api/plans",data=b'{}')
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(req)
        self.assertEqual(error.exception.code,403)

    def test_foreign_origin_is_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.call("/api/plans",{"prompt":"music"},headers={"Origin":"https://other.example"})
        self.assertEqual(error.exception.code,403)

    def test_static_traversal_not_served(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.call("/../../.env")
        self.assertEqual(error.exception.code,404)

    def test_audio_upload_and_voice_plan(self):
        _,_,body = self.call("/api/assets",raw=b"audio fixture",headers={"X-Filename":"voice.wav","X-Asset-Role":"voice"})
        asset = json.loads(body)
        _,_,body = self.call("/api/demo-assets",{})
        source = json.loads(body)["source"]
        _,_,body = self.call("/api/plans",{"prompt":"用我的声音翻唱","controls":{"voice_asset_id":asset["id"],"source_asset_id":source["id"]}})
        plan = json.loads(body)
        self.assertEqual(plan["spec"]["task"],"voice_cover")
        self.assertEqual(plan["blockers"],[])

    def test_oversized_and_invalid_json_requests_fail_cleanly(self):
        for raw in [b"not-json",b"[]",b"x"*65537]:
            with self.subTest(size=len(raw)), self.assertRaises(urllib.error.HTTPError) as error:
                self.call("/api/plans",raw=raw)
            self.assertEqual(error.exception.code,400)


if __name__ == "__main__":
    unittest.main()
