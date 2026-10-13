"""Audit caption text and timing against the immutable narration sources."""
import hashlib,json,re,statistics
from collections import Counter
from pathlib import Path
root=Path(__file__).resolve().parents[1]/'elearning_native/aps62';assets=root/'assets'
new=json.loads((root/'natural_voice_v13.json').read_text())['videos']
old=json.loads((root/'video_manifest_v9.json').read_text())
source=json.loads((root/'video_manifest_v8.json').read_text())
def stamp(s):
 h,m,sec=s.split(':');return int(h)*3600+int(m)*60+float(sec)
def cues(path):
 out=[]
 for piece in path.read_text().strip().split('\n\n'):
  if '-->' not in piece:continue
  ts,*lines=piece.splitlines();a,b=ts.split(' --> ')
  out.append((stamp(a),stamp(b),' '.join(lines)))
 return out
matches=[];total=0
for sid,row in new.items():
 p=assets/row['captions'];before=cues(assets/old[sid]['captions']);after=cues(p)
 assert hashlib.sha256(p.read_bytes()).hexdigest()==row['captions_sha256'],sid
 assert len(after)==len(before)
 assert ' '.join(x[2] for x in after)==' '.join(old[sid]['transcript'].split()),sid
 last=0
 for a,b in zip(before,after):
  assert a[2]==b[2] and abs(a[0]*.87-b[0])<=.00051 and abs(a[1]*.87-b[1])<=.00051,sid
  assert last<=b[0]<b[1]<=row['duration_seconds']+.02,sid
  last=b[1];total+=1
 source_rows=cues(assets/source[sid]['captions'])
 source_counts=Counter(text for start,end,text in source_rows)
 target_counts=Counter(text for start,end,text in after)
 source_cues={text:start for start,end,text in source_rows if source_counts[text]==1 and target_counts[text]==1}
 prior_pause=0;cuts=[]
 for pause in old[sid]['pacing']['pauses']:
  cuts.append(((pause['start_seconds']-prior_pause)*.87,pause['added_seconds']*.87))
  prior_pause+=pause['added_seconds']
 for start,end,text in after:
  if text in source_cues:
   original=source_cues[text]
   expected=original+sum(length for cut,length in cuts if original>=cut)
   matches.append(abs(start-expected))
assert len(new)==62 and max(matches)<.25 and statistics.median(matches)<.03
report={'videos':len(new),'caption_cues':total,'caption_text_matches_transcript':True,'maximum_retiming_error_ms':.51,'source_phrase_matches':len(matches),'median_source_phrase_delta_ms':round(statistics.median(matches)*1000,2),'p95_source_phrase_delta_ms':round(sorted(matches)[int(len(matches)*.95)]*1000,2),'max_source_phrase_delta_ms':round(max(matches)*1000,2)}
(root/'natural_voice_review_v13.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
