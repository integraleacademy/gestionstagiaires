"""Audit existing media without changing audio, video timelines or learner data.

Checks every caption, scene and reveal. Independently decodes every AAC track,
verifies published packet hashes and quiet cuts, then recognizes an eight-second
sample in EACH of the 104 videos. ASR checks are samples, not a complete listening
review. Low-confidence recognition is reported, never represented as a media bug.
"""
import concurrent.futures, difflib, hashlib, json, os, re, subprocess, unicodedata
from pathlib import Path
import av
import numpy as np
ROOT=Path('elearning_native/vtc');OUT=Path('/tmp/vtc-final-audit');OUT.mkdir(exist_ok=True)
manifest=json.loads((ROOT/'video_quality_v11.json').read_text())
rows=[(ref,r) for k in ('lessons','modules') for ref,r in manifest[k].items()]
def canonical(s):return ''.join(c for c in unicodedata.normalize('NFKD',s).lower() if c.isalnum())
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def check(item):
 ref,r=item;path=ROOT/'assets'/r['src'];cues=r['presentation']['captions'];errors=[]
 def require(v,label):
  if not v:errors.append(label)
 for key,h in [('src','media_sha256'),('poster','poster_sha256'),('captions','captions_sha256')]:require(sha(ROOT/'assets'/r[key])==r[h],key+' hash')
 require(canonical(''.join(c['text'] for c in cues))==canonical(r['transcript']),'caption transcript')
 vtt=(ROOT/'assets'/r['captions']).read_text();vtttexts=['\n'.join(x.splitlines()[1:]) for x in vtt.strip().split('\n\n')[1:]]
 require([c['text'] for c in cues]==vtttexts,'VTT parity')
 anchors=0
 for scene,view,chapter in zip(r['scenes'],r['presentation']['scenes'],r['chapters']):
  start,end=scene['start_seconds'],scene['end_seconds'];selected=[c for c in cues if start-.002<=c['start']<end-.002]
  text=''.join(x['text'] for x in scene['language_segments']);timeline=[c for c in selected for _ in canonical(c['text'])]
  require(canonical(text)==canonical(''.join(c['text'] for c in selected)),'scene transcript')
  require(start==view['start']==chapter['start_seconds'] and end==view['end']==chapter['end_seconds'],'scene times')
  for p,reveal,point in zip(scene['points'],scene['reveals'],view['points']):
   anchors+=1;pos=len(canonical(text[:text.index(p['anchor_text'])]));cue=timeline[pos];at=reveal['at_seconds']
   require(at==point['at_seconds'] and cue['start']-.08<=at<=cue['end']+.08,'reveal-caption sync')
 with av.open(str(path)) as c:
  a=c.streams.audio[0];digest=hashlib.sha256();packets=0
  for p in c.demux(a):
   if p.size:digest.update(bytes(p));packets+=1
 require(digest.hexdigest()==r['audio_provenance']['sha256'],'audio packet hash')
 require(packets==r['audio_provenance']['packets'],'audio packet count')
 pcm=subprocess.run(['ffmpeg','-v','error','-threads','1','-i',str(path),'-vn','-ar','16000','-ac','1','-f','s16le','-'],capture_output=True,check=True).stdout
 samples=np.frombuffer(pcm,np.int16).astype(np.float32)/32768
 for scene in r['scenes']:
  quiet=scene['verified_silence'];window=samples[int((quiet['start']+.04)*16000):int((quiet['end']-.04)*16000)]
  require(len(window)>6000 and float(np.max(np.abs(window)))<.002,'scene quiet tail')
 for pause in r['learning_pauses']:
  at=pause['at_seconds'];window=samples[int((at-.025)*16000):int((at+.08)*16000)]
  require(len(window)>1000 and float(np.max(np.abs(window)))<.002,'pause intersects speech')
 middle=r['scenes'][len(r['scenes'])//2]
 seg=max(middle['spoken_segments'],key=lambda x:x['end_seconds']-x['start_seconds'])
 start=seg['start_seconds']+max(0,(seg['end_seconds']-seg['start_seconds']-8)/2)
 if ref=='A.02':start=60.0
 clip=samples[int(start*16000):int((start+8)*16000)]
 return {'ref':ref,'errors':errors,'scenes':len(r['scenes']),'anchors':anchors,'captions':len(cues),'duration':r['duration_seconds'],'sha256':r['media_sha256'],'sample_start':round(start,3),'sample_language':seg['lang']},clip,r
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:checked=list(pool.map(check,rows))
technical=[x[0] for x in checked];(OUT/'technical.json').write_text(json.dumps(technical,ensure_ascii=False,indent=2))
summary={'videos':len(technical),'seconds':sum(x['duration'] for x in technical),'scenes':sum(x['scenes'] for x in technical),'caption_cues':sum(x['captions'] for x in technical),'visual_anchors':sum(x['anchors'] for x in technical),'technical_errors':sum(len(x['errors']) for x in technical)}
print('TECHNICAL',json.dumps(summary),flush=True)
if summary['technical_errors']:raise SystemExit('Technical media audit failed; inspect technical.json')
from faster_whisper import WhisperModel
model=WhisperModel(os.getenv('VTC_ASR_MODEL','base'),device='cpu',compute_type='int8',cpu_threads=4,num_workers=1)
recognition=[]
for report,clip,row in checked:
 if os.getenv('VTC_RECHECK_ONLY') and report['ref'] not in os.environ['VTC_RECHECK_ONLY'].split(','):continue
 start=report['sample_start'];segments,_=model.transcribe(clip,language=report['sample_language'],beam_size=5,word_timestamps=True,condition_on_previous_text=False,temperature=0)
 words=[w for s in segments for w in (s.words or []) if canonical(w.word)];heard=[canonical(w.word) for w in words]
 expected=[(canonical(w),c) for c in row['presentation']['captions'] if c['end']>start and c['start']<start+8 for w in c['text'].split() if canonical(w)]
 matches=[]
 for block in difflib.SequenceMatcher(None,heard,[w for w,c in expected],autojunk=False).get_matching_blocks():
  for i in range(block.size):
   w=words[block.a+i];cue=expected[block.b+i][1];when=float(start+w.start)
   if .4<=w.start<7.6:matches.append({'word':w.word,'voice_start':round(when,3),'caption_start':cue['start'],'caption_end':cue['end'],'outside_seconds':round(max(cue['start']-when,when-cue['end'],0),3)})
 coverage=sum(b.size for b in difflib.SequenceMatcher(None,heard,[w for w,c in expected],autojunk=False).get_matching_blocks())/max(1,len(heard))
 maxgap=max((m['outside_seconds'] for m in matches),default=None)
 record={'ref':report['ref'],'start':start,'seconds':len(clip)/16000,'text':' '.join(w.word.strip() for w in words),'recognized_word_match':round(coverage,3),'matched_words':len(matches),'max_caption_gap':maxgap,'needs_inspection':bool(coverage<.55 or len(matches)<5 or maxgap is None or maxgap>.65),'matches':matches}
 recognition.append(record);print('ACOUSTIC',record['ref'],'coverage',round(coverage,2),'gap',maxgap,'review',record['needs_inspection'],flush=True)
 (OUT/'acoustic.json').write_text(json.dumps(recognition,ensure_ascii=False,indent=2,default=lambda value:value.item()))
summary.update(acoustic_samples=len(recognition),acoustic_sample_seconds=sum(x['seconds'] for x in recognition),acoustic_samples_for_inspection=[x['ref'] for x in recognition if x['needs_inspection']])
(OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
print('FINAL',json.dumps(summary),flush=True)
