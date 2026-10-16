"""End-to-end publication gates for the reviewed APS v10 edition."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import unittest
from elearning_native.academy import ROOT, curriculum_manifest, load_bundled_course
from scripts.aps62_v10.video_content import courses
from scripts.aps62_v10.practical_cases import PRODUCTIONS

VERSION='20261010-aps62-v10'
PREVIOUS='20261007-aps62-v9'
V9_HASH='bd7a3298b56527328abf33ba71ff9462938034dbf99f62aae253213f8d82d2d5'


def read(path):
    return json.loads(path.read_text())


def seconds(text):
    h,m,s=text.split(':')
    return int(h)*3600+int(m)*60+float(s)


class APS62V10ReleaseTests(unittest.TestCase):
    def test_assigned_v9_content_is_preserved_byte_for_byte(self):
        files=sorted((ROOT/'courses').glob(f'*/{PREVIOUS}.json'))+sorted((ROOT/'exams'/PREVIOUS).glob('*.json'))
        self.assertEqual(len(files),31)
        h=hashlib.sha256()
        for p in files:
            h.update(p.relative_to(ROOT).as_posix().encode()+b'\0'+p.read_bytes()+b'\0')
        self.assertEqual(h.hexdigest(),V9_HASH)

    def test_all_62_scripts_have_one_demonstration_and_specific_spoken_dialogues(self):
        scripts=courses()
        self.assertEqual(len(scripts),62)
        dialogues=[]
        for sid,row in scripts.items():
            self.assertEqual(row['transcript'],'\n\n'.join(s['text'] for s in row['scenes']))
            self.assertGreaterEqual(len(row['transcript'].split()),1000)
            self.assertNotIn('Comparer deux moments de la décision',[s['title'] for s in row['scenes']])
            dialogue=[s for s in row['scenes'] if s['kind']=='field_dialogue']
            self.assertEqual(len(dialogue),1)
            dialogues.append(dialogue[0]['text'])
            for turn in dialogue[0]['dialogue']:
                self.assertLessEqual(len(turn['display_text']),180)
                self.assertIn(turn['text'],row['transcript'])
        self.assertEqual(len(set(dialogues)),62)

    def test_complete_publication_keeps_navigation_budgets_and_practical_work(self):
        manifest=curriculum_manifest()
        if manifest['version'] not in (VERSION, '20261010-aps62-v11'):
            self.assertEqual(manifest['version'],PREVIOUS)
            self.skipTest('v10 media and courses not yet published')
        self.assertEqual(manifest['production_count'],10)
        self.assertEqual(manifest['interactive_workshop_count'],132)
        videos=read(ROOT/'video_manifest_v8.json')
        scripts=courses();self.assertEqual(set(videos),set(scripts))
        self.assertEqual(read(ROOT/'video_scripts_v8.json'),scripts)
        productions=[];minutes=practices=activities=0
        for module in manifest['modules']:
            new=load_bundled_course(module['id'], VERSION);old=load_bundled_course(module['id'],PREVIOUS)
            self.assertEqual(new['version'],VERSION)
            self.assertEqual(new['activity_order'],old['activity_order'])
            self.assertEqual(new['required_minutes'],old['required_minutes'])
            for section,previous in zip(new['sections'],old['sections']):
                total=sum(a['planned_minutes'] for a in section['activities']);minutes+=total
                self.assertEqual(total,sum(a['planned_minutes'] for a in previous['activities']))
                for activity in section['activities']:
                    activities+=1;self.assertGreater(activity['planned_minutes'],0)
                    practices+=bool(activity.get('practice'))
                    if activity.get('production'):
                        productions.append(section['id']);self.assertNotIn('practice',activity)
                        self.assertFalse(activity['scored'])
                        self.assertEqual(activity['production'],PRODUCTIONS[section['id']])
                    for block in activity.get('blocks',[]):
                        if block.get('video'):
                            self.assertEqual(block['video']['src'],videos[section['id']]['src'])
                            self.assertEqual(block['video']['transcript'],scripts[section['id']]['transcript'])
            for asset in new['assets']:
                self.assertTrue((ROOT/'assets'/asset).is_file(),asset)
        self.assertEqual(set(productions),set(PRODUCTIONS))
        self.assertEqual((len(productions),practices,activities,minutes),(10,132,452,3720))

    def test_new_media_have_real_sound_picture_faithful_captions_and_valid_chapters(self):
        path=ROOT/'video_manifest_v8.json'
        if not path.exists(): self.skipTest('No v8 videos have completed rendering yet')
        videos=read(path);scripts=courses()
        self.assertIsNotNone(shutil.which('ffprobe'))
        if curriculum_manifest()['version']==VERSION:
            self.assertEqual(len(videos),62)
        for sid,video in videos.items():
            with self.subTest(sid=sid):
                self.assertEqual(video['transcript'],scripts[sid]['transcript'])
                self.assertEqual(video['render_revision'],8)
                self.assertGreaterEqual(video['narration_seconds'],300)
                for key,ext in [('src','mp4'),('poster','jpg'),('captions','vtt')]:
                    self.assertEqual(video[key],f'media/aps62/v8/{sid}.{ext}')
                    self.assertGreater((ROOT/'assets'/video[key]).stat().st_size,0)
                media=ROOT/'assets'/video['src']
                info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(media)],timeout=30))
                streams={s['codec_type']:s for s in info['streams']}
                self.assertTrue({'audio','video'}.issubset(streams))
                for kind in ('audio','video'):
                    self.assertGreaterEqual(float(streams[kind]['duration']),300)
                    self.assertAlmostEqual(float(streams[kind]['duration']),video['duration_seconds'],delta=.75)
                words=[];last=0
                for cue in (ROOT/'assets'/video['captions']).read_text().split('\n\n')[1:]:
                    timing,*lines=cue.strip().splitlines();start,end=map(seconds,timing.split(' --> '))
                    self.assertGreaterEqual(start,last);self.assertGreater(end,start);self.assertLessEqual(end,video['duration_seconds'])
                    self.assertTrue(1<=len(lines)<=2);self.assertTrue(all(len(line)<=44 for line in lines))
                    words.extend(lines);last=end
                self.assertEqual(re.sub(r'\s+','',''.join(words)),re.sub(r'\s+','',video['transcript']))
                self.assertEqual(len(video['chapters']),len(scripts[sid]['scenes']))
                if os.environ.get('APS62_VERIFY_FULL_DECODE')=='1':
                    subprocess.run(['ffmpeg','-nostdin','-v','error','-threads','1','-i',str(media),'-f','null','-'],capture_output=True,check=True,timeout=180)
