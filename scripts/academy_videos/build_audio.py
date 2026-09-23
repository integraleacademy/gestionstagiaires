"""Local speech only. Network syscalls denied before importing inference libraries."""
from offline_guard import lock_network
lock_network()
import os
os.environ['OMP_NUM_THREADS']='4'
from pathlib import Path
import json, math, sys
import numpy as np
import soundfile as sf
import onnxruntime as rt
rt.disable_telemetry_events()
from kokoro_onnx import Kokoro
ROOT=Path(__file__).resolve().parent
WORK=Path(os.environ['ACADEMY_WORK']); WORK.mkdir(parents=True,exist_ok=True)
MODEL=Path(os.environ['ACADEMY_MODEL'])
opts=rt.SessionOptions(); opts.intra_op_num_threads=4; opts.inter_op_num_threads=1
session=rt.InferenceSession(str(MODEL/'kokoro-v1.0.onnx'),sess_options=opts,providers=['CPUExecutionProvider'])
speech=Kokoro.from_session(session,str(MODEL/'voices-v1.0.bin'))
RATE=24000

def build(v):
    folder=WORK/v['id']; folder.mkdir(exist_ok=True)
    if (folder/'timeline.json').exists() and (folder/'narration.wav').exists():
        print(v['id'],'audio cached',flush=True);return
    parts=[];scenes=[];cursor=0
    def silence(n):
        nonlocal cursor
        n=round(n*RATE);parts.append(np.zeros(n,dtype=np.float32));cursor+=n/RATE
    for si,scene in enumerate(v['scenes']):
        start=cursor;cues=[];silence(.65)
        for j,words in enumerate(scene['lines']):
            path=folder/f'voice-{si}-{j}.wav'
            if path.exists():samples,rate=sf.read(path,dtype='float32')
            else:
                # Expand an acronym for clearer delivery, preserving the displayed text.
                spoken=words.replace('CNAPS','Cnaps').replace('USB','U S B')
                samples,rate=speech.create(spoken,voice='ff_siwis',speed=1.015,lang='fr-fr')
                nz=np.flatnonzero(np.abs(samples)>.006)
                if len(nz):samples=samples[max(0,nz[0]-round(.07*rate)):min(len(samples),nz[-1]+round(.16*rate))]
                sf.write(path,samples,rate)
            assert rate==RATE
            cues.append(dict(text=words,start=cursor,end=cursor+len(samples)/rate))
            parts.append(samples);cursor+=len(samples)/rate;silence(.28)
        silence(scene.get('pause',.7))
        silence(math.ceil(cursor*25)/25-cursor)
        scenes.append(dict(**scene,start=start,end=cursor,cues=cues))
    sf.write(folder/'narration.wav',np.concatenate(parts),RATE)
    (folder/'timeline.json').write_text(json.dumps(dict(id=v['id'],duration=cursor,scenes=scenes),ensure_ascii=False,indent=2))
    print(v['id'],f'{cursor:.2f}s AUDIO READY',flush=True)

if __name__=='__main__':
    series=json.loads((ROOT/'series.json').read_text())
    for v in series:
        if len(sys.argv)>1 and v['id'] not in sys.argv[1:]:continue
        build(v)
