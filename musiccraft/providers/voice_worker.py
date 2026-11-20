"""Project-owned contract; a GPU worker must implement separation + SVC + mix."""
import json
import time

from .transport import ProviderError, headers, multipart, request_bytes, request_json, same_origin_url


class VoiceWorkerProvider:
    def __init__(self, settings):
        self.settings = settings

    def convert(self, spec, source, reference):
        if not self.settings.voice_url:
            raise ProviderError("歌声转换 Worker 尚未接入")
        body, content_type = multipart({"spec": json.dumps(spec, ensure_ascii=False)},
                                       {"source": source, "reference": reference})
        h = headers(self.settings.voice_key)
        h["Content-Type"] = content_type
        return request_bytes(self.settings.voice_url + "/v1/voice-cover", body, h,
                             timeout=self.settings.provider_timeout)

    def run_job(self,spec,source,reference,canceled=lambda:False,progress=lambda key,message:None):
        if self.settings.voice_protocol=="sync":
            content,mime=self.convert(spec,source,reference)
            return {"result":(content,mime)}
        base=self.settings.voice_url
        body,content_type=multipart({"spec":spec},{"source":source,"reference":reference})
        h=headers(self.settings.voice_key);h["Content-Type"]=content_type
        raw,_=request_bytes(base+"/v1/jobs",body,h,timeout=60,limit=65536)
        try:
            job_id=json.loads(raw)["id"]
            if not isinstance(job_id,str) or len(job_id)!=32 or any(x not in "0123456789abcdef" for x in job_id):raise ValueError()
        except (ValueError,KeyError,TypeError):raise ProviderError("歌声 Worker 没有返回有效任务 ID") from None
        deadline=time.monotonic()+self.settings.provider_timeout
        previous=None
        def cancel_remote():
            try:request_json(base+"/v1/jobs/"+job_id+"/cancel",{},self.settings.voice_key,timeout=5)
            except ProviderError:pass
        while time.monotonic()<deadline:
            if canceled():
                cancel_remote();raise InterruptedError("已请求取消远端歌声转换")
            raw,_=request_bytes(base+"/v1/jobs/"+job_id,request_headers=headers(self.settings.voice_key),timeout=15,limit=65536)
            try:
                job=json.loads(raw)
                if not isinstance(job,dict):raise ValueError()
            except (ValueError,TypeError):raise ProviderError("歌声 Worker 状态响应无效") from None
            if job.get("stage")!=previous:
                previous=job.get("stage");progress(previous,job.get("message","正在转换歌声"))
            if job.get("status")=="succeeded":
                artifacts=job.get("artifacts",{})
                if not isinstance(artifacts,dict) or "result" not in artifacts:
                    raise ProviderError("歌声 Worker 缺少最终混音结果")
                output={}
                for name,path in artifacts.items():
                    if name not in {"result","source_clip","original_vocals","converted_vocals","accompaniment"}:continue
                    if canceled():raise InterruptedError("任务已取消")
                    output[name]=request_bytes(same_origin_url(base,path),request_headers=headers(self.settings.voice_key),timeout=60)
                return output
            if job.get("status") in {"failed","canceled"}:
                raise ProviderError("歌声转换失败或已取消，请查看 Worker 的任务日志")
            for _ in range(5):
                if canceled():break
                time.sleep(0.2)
        cancel_remote()
        raise ProviderError("歌声转换超时，已请求远端取消；请检查 Worker 状态")
