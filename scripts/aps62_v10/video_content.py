"""One demonstrated case, concrete dialogue and corrected rules for APS v10."""
from scripts.aps62_v9.field_videos import courses as previous_courses
from scripts.aps62_v10.content_fixes import apply_video_scripts
from scripts.aps62_v10.radio_demonstrations import RADIO_DEMONSTRATIONS


def courses():
    rows = apply_video_scripts(previous_courses())
    assert set(rows) == set(RADIO_DEMONSTRATIONS)
    for sid, row in rows.items():
        demonstration = RADIO_DEMONSTRATIONS[sid]
        # These two scenes fully retold the same field case before its visual
        # demonstration. Keep the demonstration and its own evolving chronology.
        row['scenes'] = [scene for scene in row['scenes']
                         if scene['title'] != 'Comparer deux moments de la décision']
        for scene in row['scenes']:
            if scene['kind'] == 'field_dialogue':
                scene['dialogue'] = demonstration['turns']
                scene['radio'] = demonstration['type'] == 'radio'
                scene['title'] = demonstration.get('title', 'Transmission au poste')
                scene['text'] = demonstration.get('context', '') + ' ' + ' '.join(
                    turn['speaker'] + ' : ' + turn['text'] for turn in scene['dialogue'])
                assert len(scene['dialogue']) == 3
        row['transcript'] = '\n\n'.join(scene['text'] for scene in row['scenes'])
        row['revision'] = '20261010-aps62-v10'
    return rows
