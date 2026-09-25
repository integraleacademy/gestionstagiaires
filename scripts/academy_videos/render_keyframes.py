"""Exact native artwork, 25 fps animation windows and lossless held frames.
The held artwork is decoded once per change; FFmpeg repeats it at 25 fps.
"""
from pathlib import Path
import hashlib,json,math,subprocess,sys,time
from PIL import Image
import render_series as r
import approved_style as st

def frame_times(tl):
    fps=25;n=math.ceil(tl['duration']*fps);keys={0,n}
    def window(a,b):keys.update(range(max(0,math.floor(a*fps)),min(n,math.ceil(b*fps))+1))
    for scene in tl['scenes']:
        start=scene['start'];end=scene['end'];kind=scene['kind']
        # Match every changing frame of the reference render, hold only settled art.
        settle={'hero':2.25,'rules':1.3,'case':1.0,'answer':1.1,'recap':1.75,'outro':1.0}[kind]
        window(start,min(end,start+settle))
        if kind=='hero':keys.update(range(math.ceil((start+settle)*fps),math.ceil(end*fps),2))
        keys.update([max(0,math.ceil(start*fps)),min(n,math.ceil(end*fps))])
        for cue in scene['cues']:
            keys.update([math.ceil(cue['start']*fps),min(n,math.ceil(cue['end']*fps))])
            if cue.get('pause') and kind=='case':keys.update(range(math.ceil(cue['start']*fps),math.ceil(cue['end']*fps),2))
        if kind=='rules':
            for i in range(3):
                a=scene['cues'][0]['start']+(end-scene['cues'][0]['start']-.8)*i/3;window(a,a+.65)
        if kind=='answer':
            for i in range(3):
                a=scene['cues'][min(1,len(scene['cues'])-1)]['start']+i*1.6;window(a,a+.5)
    return sorted(k for k in keys if 0<=k<=n)

def render(v):
    folder=r.WORK/v['id'];tl=json.loads((folder/'timeline.json').read_text());r.configure(v,tl)
    out=r.OUT/(v['id']+'.mp4')
    source=Path(__file__).read_bytes()+(r.ROOT/'render_series.py').read_bytes()+(r.ROOT/'approved_style.py').read_bytes()+(folder/'timeline.json').read_bytes()
    signature=hashlib.sha256(source).hexdigest()
    if out.exists() and (folder/'render.json').exists():
        if json.loads((folder/'render.json').read_text()).get('render_sha256')==signature:
            print(v['id'],'reference video cached',flush=True);return
    keydir=folder/'keyframes';keydir.mkdir(exist_ok=True)
    artwork_hash=hashlib.sha256((r.ROOT/'render_series.py').read_bytes()+(r.ROOT/'approved_style.py').read_bytes()+(folder/'timeline.json').read_bytes()).hexdigest()
    marker=keydir/'artwork.sha256'
    if not marker.exists() or marker.read_text()!=artwork_hash:
        for old in keydir.glob('*.png'):old.unlink()
        marker.write_text(artwork_hash)
    keys=frame_times(tl);entries=[];began=time.monotonic()
    original_footer=st.footer
    def fixed_footer(im,t,light=False):original_footer(im,0,light)
    st.footer=fixed_footer
    try:
        for j,(i,next_i) in enumerate(zip(keys,keys[1:])):
            target=keydir/f'{i:05}.png'
            if not target.exists():r.frame(v,tl,i/25).save(target,compress_level=1)
            entries.extend([f"file '{target}'",f'duration {(next_i-i)/25:.8f}'])
            if j%150==0:print(v['id'],f'artwork {j}/{len(keys)-1}',f'{time.monotonic()-began:.1f}s',flush=True)
    finally:st.footer=original_footer
    entries.append(f"file '{target}'")
    concat=folder/'keyframes.txt';concat.write_text('\n'.join(entries)+'\n')
    # A tiny native-resolution alpha strip animates the original progress bar.
    duration=tl['duration'];tmp=out.with_suffix('.keyframes.partial.mp4')
    filters=f"[0:v]fps=25[base];color=c=#F2C461:s=3536x6:r=25:d={duration},format=rgba,geq=r=242:g=196:b=97:a='if(lte(X,3536*T/{duration}),255,0)'[line];[base][line]overlay=x=152:y=2062:shortest=1,format=yuv420p[out]"
    cmd=['ffmpeg','-nostdin','-v','warning','-y','-threads','1','-f','concat','-safe','0','-i',str(concat),'-i',str(folder/'narration.wav'),'-filter_complex_threads','1','-filter_complex',filters,'-map','[out]','-map','1:a:0','-c:v','libx264','-preset','veryfast','-crf','17','-threads','2','-c:a','aac','-b:a','192k','-af','loudnorm=I=-16:TP=-1.5:LRA=11','-ar','48000','-movflags','+faststart','-t',str(duration),str(tmp)]
    with (folder/'keyframe-ffmpeg.log').open('w') as log:subprocess.run(cmd,stdout=log,stderr=log,check=True,timeout=900)
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(tmp)]))
    video=next(s for s in probe['streams'] if s['codec_type']=='video');audio=next(s for s in probe['streams'] if s['codec_type']=='audio')
    assert (video['width'],video['height'])==(3840,2160) and abs(float(probe['format']['duration'])-duration)<.1
    assert audio['sample_rate']=='48000'
    tmp.replace(out)
    poster=r.frame(v,tl,3);poster.thumbnail((1280,720),Image.Resampling.LANCZOS);poster.save(out.with_suffix('.jpg'),quality=94)
    cues=[c for s in tl['scenes'] for c in s['cues'] if not c.get('pause')]
    (folder/'subtitles.srt').write_text('\n\n'.join(f'{i+1}\n{r.stamp(c["start"])} --> {r.stamp(c["end"])}\n{c["text"]}' for i,c in enumerate(cues))+'\n')
    result=dict(id=v['id'],duration_seconds=float(probe['format']['duration']),bytes=out.stat().st_size,width=video['width'],height=video['height'],voice=tl['voice'],rate=tl['rate'],reference_style=tl['reference_style'],render_sha256=signature)
    (folder/'render.json').write_text(json.dumps(result,indent=2)+'\n')
    print(v['id'],f'{result["duration_seconds"]:.2f}s',out.stat().st_size,'REFERENCE VIDEO READY',flush=True)

if __name__=='__main__':
    for v in json.loads((r.ROOT/'series.json').read_text()):
        if len(sys.argv)>1 and v['id'] not in sys.argv[1:]:continue
        render(v)
