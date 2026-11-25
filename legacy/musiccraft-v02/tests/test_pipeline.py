"""Contract tests use generated WAV fixtures and mocked GPU commands, not real models."""
import io
import json
import shutil
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import wave
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer

from musiccraft.audio import clip_audio
from musiccraft.config import Settings
from musiccraft.engine import Engine
from musiccraft.models import TaskSpec, ValidationError
from musiccraft.planner import Planner
from musiccraft.providers.transport import ProviderError,multipart
from musiccraft.providers.voice_worker import VoiceWorkerProvider
from musiccraft.server import Application
from musiccraft.services import service_status
from musiccraft.store import Store
from workers.pipeline import PipelineConfig,PipelineError,run_pipeline,run_command
from workers.voice_server import VoiceService,make_handler,parse_upload
from tests.test_core import wait_job


def wav_bytes(seconds=4,rate=8000):
    out=io.BytesIO()
    with wave.open(out,'wb') as f:
        f.setnchannels(1);f.setsampwidth(2);f.setframerate(rate)
        f.writeframes(b'\x01\x00'*int(seconds*rate))
    return out.getvalue()


class AudioTest(unittest.TestCase):
    def test_clip_is_actual_pcm_slice(self):
        data=wav_bytes(4)
        _,audio,_=clip_audio(('s.wav',data,'audio/wav'),1,2)
        with wave.open(io.BytesIO(audio),'rb') as f:
            self.assertEqual(f.getnframes(),16000)
            self.assertEqual(f.readframes(2),b'\x01\x00'*2)

    def test_invalid_start_and_missing_decoder(self):
        with self.assertRaises(ValidationError):clip_audio(('s.wav',wav_bytes(),'audio/wav'),8,10)
        with self.assertRaises(ValidationError):clip_audio(('s.mp3',b'ID3xxx','audio/mpeg'),0,10,'missing-musiccraft-ffmpeg')

    def test_numeric_options_reject_nan_bool_and_range(self):
        for field,value in [('clip_start',-1),('clip_start',float('nan')),('cover_strength',True),('cover_strength',2),('vocal_gain_db',7)]:
            with self.subTest(field=field,value=value),self.assertRaises(ValidationError):TaskSpec.from_dict({field:value})

    def test_composition_is_deferred_by_default(self):
        with tempfile.TemporaryDirectory() as root:
            settings=Settings(data_dir=Path(root));plan=Planner(settings,Store(root)).create({'prompt':'创作音乐'})
            self.assertTrue(any('暂缓' in x for x in plan['blockers']))
            self.assertFalse(settings.public()['generation_ready'])

    def test_voice_route_has_vocals_and_preserves_backing(self):
        with tempfile.TemporaryDirectory() as root:
            settings=Settings(data_dir=Path(root));plan=Planner(settings,Store(root)).create({'prompt':'用我的声音翻唱，保留原伴奏'})
            self.assertEqual(plan['spec']['vocal'],'any')
            self.assertIn('accompaniment',plan['spec']['preserve'])

    def test_service_checks_do_not_claim_ready_in_demo(self):
        result=service_status(Settings(data_dir=Path('unused')))
        self.assertEqual(result['ace']['state'],'unconfigured')
        self.assertEqual(result['voice']['state'],'unconfigured')

    def test_live_restyle_sends_trimmed_source_and_saves_comparison(self):
        with tempfile.TemporaryDirectory() as root:
            settings=Settings(data_dir=Path(root),mode="live",ace_url="http://localhost:8001")
            app=Application(settings)
            try:
                source=app.store.create_asset("song.wav",wav_bytes(15),"audio/wav")
                plan=app.planner.create({"prompt":"改成流行", "controls":{"source_asset_id":source["id"],"clip_start":8,"duration":10}})
                def generate(spec,prompt,source,canceled,progress):
                    with wave.open(io.BytesIO(source[1]),"rb") as f:self.assertEqual(f.getnframes()/f.getframerate(),7)
                    return source[1],source[2]
                with patch.object(app.engine.ace,"generate",side_effect=generate):
                    job=wait_job(app.store,app.engine.submit(plan["id"])["id"])
                self.assertEqual(job["status"],"succeeded")
                self.assertIn("source_clip",job["artifacts"])
                self.assertEqual(job["metrics"]["duration_seconds"],7)
            finally:app.engine.close()


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.repo=self.root/'seed';self.repo.mkdir();(self.repo/'inference.py').write_text('#fixture')
        self.config=PipelineConfig(self.repo,ffmpeg='python3');self.calls=[]

    def tearDown(self):self.temp.cleanup()

    def fake_command(self,args,log,**kwargs):
        self.calls.append(args)
        if '-m' in args:
            path=Path(args[args.index('-o')+1])/'htdemucs'/'source';path.mkdir(parents=True)
            for name in ['vocals.wav','no_vocals.wav']:(path/name).write_bytes(wav_bytes())
        elif '--output' in args:
            (Path(args[args.index('--output')+1])/'converted.wav').write_bytes(wav_bytes())
        else:Path(args[-1]).write_bytes(wav_bytes())

    def test_pipeline_order_svc_pitch_and_exact_clip_length(self):
        stages=[]
        result=run_pipeline(self.config,self.root/'job',self.root/'s.mp3',self.root/'v.webm',{'duration':10,'clip_start':12,'vocal_gain_db':-2},lambda k,m:stages.append(k),runner=self.fake_command)
        self.assertEqual(stages,['normalize','separate','convert','mix'])
        self.assertEqual(set(result),{'result','source_clip','original_vocals','converted_vocals','accompaniment'})
        self.assertEqual(self.calls[0][self.calls[0].index('-ss')+1],'12')
        seed=self.calls[3]
        self.assertEqual(seed[seed.index('--f0-condition')+1],'True')
        self.assertEqual(seed[seed.index('--auto-f0-adjust')+1],'False')
        self.assertEqual(self.calls[4][self.calls[4].index('-t')+1],'4.0')
        self.assertIn('volume=-2dB',self.calls[4][self.calls[4].index('-filter_complex')+1])
        self.assertTrue(all(path.is_file() for path in result.values()))

    def test_missing_separated_stems_fails(self):
        def fake(args,log,**kwargs):
            if '-m' not in args:self.fake_command(args,log,**kwargs)
        with self.assertRaisesRegex(PipelineError,'Demucs'):run_pipeline(self.config,self.root/'job','s','v',{},runner=fake)

    def test_cancel_before_subprocess(self):
        with self.assertRaises(InterruptedError):run_pipeline(self.config,self.root/'job','s','v',{},canceled=lambda:True,runner=self.fake_command)
        self.assertEqual(self.calls,[])

    def test_command_failure_and_cancellation(self):
        import sys
        with self.assertRaises(PipelineError):run_command([sys.executable,'-c','raise SystemExit(3)'],self.root/'log',timeout=5)
        with self.assertRaises(InterruptedError):run_command([sys.executable,'-c','import time;time.sleep(30)'],self.root/'log',canceled=lambda:True)


class WorkerHTTPTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.service=VoiceService(self.root/'worker',PipelineConfig(self.root/'seed'))
        self.server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(self.service,'test-secret'))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.settings=Settings(data_dir=self.root/'studio',mode='live',voice_url='http://127.0.0.1:'+str(self.server.server_port),voice_key='test-secret',provider_timeout=10)
        self.worker=VoiceWorkerProvider(self.settings)
        self.spec=TaskSpec(task='voice_cover').to_dict()
        self.audio=('input.wav',wav_bytes(),'audio/wav')

    def tearDown(self):
        with self.service.lock:
            for job in self.service.jobs.values():
                if job['status'] in {'running','queued'}:job['status']='canceling'
        self.server.shutdown();self.server.server_close();self.thread.join();self.service.pool.shutdown(wait=True);self.temp.cleanup()

    def fake_pipeline(self,config,folder,source,reference,spec,stage,canceled):
        self.assertEqual(source.read_bytes(),self.audio[1]);self.assertEqual(reference.read_bytes(),self.audio[1])
        stage('separate','分离中');stage('convert','转换中')
        result=folder/'result.wav';result.write_bytes(wav_bytes())
        return {'result':result,'source_clip':result,'converted_vocals':result,'original_vocals':result,'accompaniment':result}

    def test_real_http_adapter_downloads_artifacts_and_cleans_reference(self):
        with patch('workers.voice_server.run_pipeline',side_effect=self.fake_pipeline):
            result=self.worker.run_job(self.spec,self.audio,self.audio)
        self.assertEqual(result['result'][0],wav_bytes())
        self.assertEqual(len(result),5)
        job_id=next(iter(self.service.jobs));folder=self.service.root/job_id
        self.assertFalse((folder/'ref.audio').exists());self.assertFalse((folder/'input.audio').exists())
        self.assertNotIn(str(self.root),json.dumps(self.service.public(job_id)))

    def test_worker_requires_auth(self):
        with self.assertRaises(urllib.error.HTTPError) as err:urllib.request.urlopen(self.settings.voice_url+'/health')
        self.assertEqual(err.exception.code,401)

    def test_invalid_multipart_is_rejected(self):
        body,ctype=multipart({'spec':self.spec},{'source':self.audio})
        with self.assertRaises(ValidationError):parse_upload(body,ctype)
        body,ctype=multipart({'spec':dict(self.spec,task='restyle')},{'source':self.audio,'reference':self.audio})
        with self.assertRaises(ValidationError):parse_upload(body,ctype)

    def test_cancellation_reaches_remote_worker(self):
        called=threading.Event();finished=threading.Event()
        def slow(config,folder,source,ref,spec,stage,canceled):
            called.set()
            while not canceled():time.sleep(.01)
            finished.set();raise InterruptedError()
        with patch('workers.voice_server.run_pipeline',side_effect=slow):
            with self.assertRaises(InterruptedError):self.worker.run_job(self.spec,self.audio,self.audio,canceled=called.is_set)
            self.assertTrue(finished.wait(2))

    def test_worker_failure_does_not_become_demo_audio(self):
        with patch('workers.voice_server.run_pipeline',side_effect=PipelineError('fixture failure')):
            with self.assertRaises(ProviderError):self.worker.run_job(self.spec,self.audio,self.audio)

    def test_engine_saves_voice_stems_and_pins_true_provenance(self):
        app=Application(self.settings)
        try:
            source=app.store.create_asset('song.wav',self.audio[1],'audio/wav')
            voice=app.store.create_asset('voice.wav',self.audio[1],'audio/wav',role='voice')
            plan=app.planner.create({'prompt':'用我的声音翻唱','controls':{'source_asset_id':source['id'],'voice_asset_id':voice['id']}})
            with patch('workers.voice_server.run_pipeline',side_effect=self.fake_pipeline):
                job=wait_job(app.store,app.engine.submit(plan['id'])['id'])
            self.assertEqual(job['status'],'succeeded');self.assertEqual(len(job['artifacts']),4)
            self.assertEqual(app.pin(job['id'])['mode'],'live')
            self.assertEqual(app.store.get("job",job["id"])["status"],"succeeded")
            app.pin(job["id"])
            self.assertEqual(len(app.store.list("showcase")),1)
        finally:app.engine.close()

    def test_pinning_demo_keeps_demo_label(self):
        app=Application(Settings(data_dir=self.root/'other'))
        try:
            assets=app.demo_assets();plan=app.planner.create({'prompt':'改成流行','controls':{'source_asset_id':assets['source']['id']}})
            job=wait_job(app.store,app.engine.submit(plan['id'])['id'])
            self.assertEqual(app.pin(job['id'])['origin'],'流程演示占位')
        finally:app.engine.close()


if __name__=='__main__':unittest.main()
