"""Persistent sampled capacity guard: bounded memory, no log or sample-count limit."""
import threading
import time
from memory_reader import NativeReader, checked_host_sample, checked_sample, host_memory, MIB


class MemoryMonitor:
    def __init__(self,path,sha):
        self.path,self.sha=path,sha; self.reader=None
        self.done=threading.Event(); self.ready=threading.Event(); self.thread=None
        self.error=None; self.last=None; self.samples=0; self.minimum={}; self.latest={}; self.policy_reading=None

    def sample(self):
        begin=time.monotonic(); gpu=checked_sample(self.reader.read()); host=checked_host_sample(host_memory())
        if time.monotonic()-begin>2: raise RuntimeError('Memory query exceeded two seconds')
        row={'vram_free_mib':gpu['free_bytes']/MIB,'ram_free_gib':host['available_ram_gib'],
             'commit_free_gib':host['available_commit_gib']}
        self.policy_reading={'sampled_at':host['sampled_at'], 'ram_total':host['total_ram_gib']*2**30,
                             'ram_used':(host['total_ram_gib']-host['available_ram_gib'])*2**30,
                             'ram_commit_required':True, 'ram_commit_available':host['available_commit_gib']*2**30,
                             'gpu_mem_total':gpu['total_bytes'], 'gpu_mem_used':gpu['used_bytes']}
        self.latest=row; self.last=time.monotonic(); self.samples+=1
        for name,value in row.items(): self.minimum[name]=min(value,self.minimum.get(name,value))
        if row['vram_free_mib']<250 or min(row['ram_free_gib'],row['commit_free_gib'])<3:
            raise RuntimeError('Memory headroom below 250 MiB VRAM or 3 GiB RAM/commit')
        return row

    def start(self):
        def loop():
            try:
                self.reader=NativeReader(self.path,self.sha); self.sample()
            except BaseException as exc:
                self.error=str(exc); self.ready.set(); return
            self.ready.set()
            while not self.done.wait(.1):
                try: self.sample()
                except BaseException as exc: self.error=str(exc); return
        self.thread=threading.Thread(target=loop,name='independent-memory',daemon=True); self.thread.start()
        if not self.ready.wait(2):
            self.error='Independent memory initialization exceeded two seconds'
            raise RuntimeError(self.error)
        self.check()
        return self

    def check(self):
        if self.error or self.last is None or time.monotonic()-self.last>2 or not self.thread.is_alive():
            raise RuntimeError(self.error or 'Independent memory observation unavailable')

    def snapshot(self):
        return {'samples':self.samples,'latest':dict(self.latest),'minimum':dict(self.minimum),
                'error':self.error,'scope':'100 ms sampled driver/host capacity; not continuous residency proof'}

    def startup_reading(self):
        self.check()
        return dict(self.policy_reading)

    def close(self):
        self.done.set()
        if self.thread: self.thread.join(2)
        if self.thread and self.thread.is_alive(): self.error=self.error or 'Memory monitor did not stop'
        elif self.reader:
            try: self.reader.close()
            except BaseException as exc: self.error=self.error or str(exc)
        return self.snapshot()
