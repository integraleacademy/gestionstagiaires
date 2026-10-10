"""Word-preserving pacing and exact visual landmarks for APS video revision 9.

Pauses are added only at authored chapter/correction boundaries, never inside a
phrase to satisfy a subtitle metric. Caption speeds are reported honestly.
"""
from bisect import bisect_right
import re
import wave

from scripts.aps62_v5.captions import align_words, canonical, wrap_caption

TEMPO = 0.87
TRANSITION_PAUSE = 2.5
CORRECTION_PAUSE = 4.0
FINAL_DEFINITION_HOLD = 8.0
CAPTION_TARGET_CPS = 18.0
CAPTION_REVIEW_CPS = 20.0


def source_layout(row, boundaries):
    """Return exact word indices for scenes and authored visual landmarks."""
    words = align_words(row['transcript'], boundaries)
    positions, cursor = {0: 0}, 0
    for index, item in enumerate(boundaries):
        cursor += len(canonical(item['text']))
        positions[cursor] = index + 1
    assert cursor == len(canonical(row['transcript']))
    scenes, cursor = [], 0
    for scene in row['scenes']:
        text = canonical(scene['text'])
        start_index, end_index = positions[cursor], positions[cursor + len(text)]
        landmarks = {}
        def locate(key, phrase, search_from=0):
            found = text.find(canonical(phrase), search_from)
            if found < 0 or cursor + found not in positions:
                raise ValueError('Cannot align authored landmark: ' + phrase[:100])
            landmarks[key] = positions[cursor + found]
            return found + len(canonical(phrase))
        kind = scene['kind']
        if kind == 'glossary':
            after = 0
            for index, term in enumerate(row['glossary']):
                after = locate('term_' + str(index), term['term'] + ': ' + term['definition'], after)
        elif kind == 'field_dialogue':
            after = 0
            for index, turn in enumerate(scene['dialogue']):
                after = locate('turn_' + str(index), turn['speaker'] + ': ' + turn['text'], after)
        elif kind == 'field_observation':
            locate('fact', 'Le point établi, à distinguer des suppositions, est le suivant.')
        elif kind == 'field_documents':
            locate('verified', 'Le repère à utiliser est le suivant')
        elif kind == 'field_consequence':
            locate('decision', 'La décision adaptée est la suivante')
            locate('reason', 'Voici pourquoi ces choix ne sont pas équivalents')
        elif kind == 'field_evolution':
            locate('decision', 'La décision doit être réévaluée')
            locate('reason', 'Le point de vigilance est le suivant')
        if 'danscecaslareponseadapteeestlasuivante' in text:
            locate('example_correction', 'Dans ce cas, la réponse adaptée est la suivante')
        scenes.append(dict(start_word=start_index, end_word=end_index, landmarks=landmarks))
        cursor += len(text)
    assert scenes[-1]['end_word'] == len(words)
    return words, scenes


def make_plan(row, boundaries, source_seconds, tempo=TEMPO):
    """Compute insertions in slowed source time, then map all words/landmarks."""
    source_words, scenes = source_layout(row, boundaries)
    slow_words = [dict(w, start=w['start']/tempo, end=w['end']/tempo) for w in source_words]
    requests = {}
    def request(index, target, reason):
        assert 0 < index < len(slow_words)
        item = requests.setdefault(index, dict(target_gap_seconds=0, reasons=[]))
        item['target_gap_seconds'] = max(item['target_gap_seconds'], target)
        if reason not in item['reasons']:
            item['reasons'].append(reason)
    for layout in scenes[1:]:
        request(layout['start_word'], TRANSITION_PAUSE, 'chapter_transition')
    for scene, layout in zip(row['scenes'], scenes):
        for key, index in layout['landmarks'].items():
            if key in ('verified', 'decision', 'example_correction'):
                request(index, CORRECTION_PAUSE, 'before_correction')
        if scene['kind'] == 'glossary':
            final_start = slow_words[layout['landmarks']['term_2']]['start']
            next_index = layout['end_word']
            if next_index < len(slow_words):
                # The visual chapter changes .08 s before the next spoken word.
                extra = max(0, FINAL_DEFINITION_HOLD + .08 -
                            (slow_words[next_index]['start'] - final_start))
                current_gap = slow_words[next_index]['start'] - slow_words[next_index-1]['end']
                request(next_index, current_gap + extra, 'final_definition_hold')
    insertions = []
    for index, request_data in sorted(requests.items()):
        previous, following = slow_words[index-1], slow_words[index]
        gap = following['start'] - previous['end']
        # Authored chapter and correction boundaries are punctuation gaps. A
        # cut in continuous voiced speech would need a new narration, not padding.
        if gap < .15:
            raise ValueError(f'Authored pause {index} has no safe gap ({gap:.3f}s)')
        added = max(0, request_data['target_gap_seconds'] - gap)
        if added > .001:
            insertions.append(dict(before_word=index,
                                   source_cut_seconds=(previous['end']+following['start'])/2,
                                   added_seconds=added, existing_gap_seconds=gap,
                                   **request_data))
    cuts = [p['source_cut_seconds'] for p in insertions]
    cumulative, total = [0.0], 0.0
    for pause in insertions:
        total += pause['added_seconds']
        cumulative.append(total)
    def mapped(t):
        return t + cumulative[bisect_right(cuts, t)]
    words = [dict(w, start=mapped(w['start']), end=mapped(w['end'])) for w in slow_words]
    for pause in insertions:
        before = sum(p['added_seconds'] for p in insertions
                     if p['source_cut_seconds'] < pause['source_cut_seconds'])
        pause['start_seconds'] = pause['source_cut_seconds'] + before
        pause['end_seconds'] = pause['start_seconds'] + pause['added_seconds']
    duration = source_seconds/tempo + total + .35
    mapped_scenes = []
    for index, layout in enumerate(scenes):
        start = 0 if index == 0 else max(0, words[layout['start_word']]['start']-.08)
        end = max(0, words[scenes[index+1]['start_word']]['start']-.08) if index+1 < len(scenes) else duration
        landmarks = {key: words[value]['start'] for key, value in layout['landmarks'].items()}
        mapped_scenes.append(dict(**layout, start_seconds=start, end_seconds=end,
                                  reveal_seconds=landmarks))
    return dict(tempo=tempo, source_seconds=source_seconds,
                planned_seconds=duration, added_pause_seconds=total,
                insertions=insertions, words=words, scenes=mapped_scenes,
                transition_target_seconds=TRANSITION_PAUSE,
                correction_target_seconds=CORRECTION_PAUSE,
                final_definition_minimum_seconds=FINAL_DEFINITION_HOLD)


def caption_text(words, start, end):
    # align_words retains authored punctuation. Internal whitespace is the only
    # freedom used by the two-line display and no character is discarded.
    return ' '.join(word['text'] for word in words[start:end])


def make_paced_cues(source, words, duration):
    """Find readable two-line groups without inserting pauses inside phrases.

    A dynamic program selects cuts by reading speed and grammatical boundaries.
    Existing silence is used to hold captions. Rare >20 CPS cues are measured,
    never made artificially compliant by clipping text or chopping the voice.
    """
    count = len(words)
    costs, choices = [float('inf')] * (count+1), {}
    costs[count] = 0
    function_words = {'de','du','des','le','la','les','un','une','à','et','en','pour','ne'}
    for index in range(count-1, -1, -1):
        start = max(0, words[index]['start']-.08)
        for end in range(index+1, min(count, index+30)+1):
            text = caption_text(words, index, end)
            wrapped = wrap_caption(text, width=44)
            if wrapped is None or len(text) > 88:
                break
            if words[end-1]['end'] - start > 7.5:
                break
            available_end = words[end]['start']-.14 if end < count else duration-.12
            finish = min(available_end, start+8.0)
            if finish <= start:
                continue
            length = len(wrapped.replace('\n', ' '))
            cps = length/(finish-start)
            punctuation = bool(re.search(r'[.!?;:,]$', text))
            sentence = bool(re.search(r'[.!?]$', text))
            penalty = 2 + max(0, cps-CAPTION_TARGET_CPS)**2 * 3
            penalty += max(0, cps-CAPTION_REVIEW_CPS)**2 * 30
            penalty += 3 if not punctuation else 0
            penalty += 3 if text.split()[-1].lower() in function_words else 0
            penalty += max(0, 1.2-(finish-start))*20
            penalty += max(0, 24-length)*.08 if not sentence else 0
            candidate = penalty + costs[end]
            if candidate < costs[index]:
                costs[index] = candidate
                choices[index] = (end, dict(start=round(start,3), end=round(finish,3), text=wrapped,
                                           first_word=index, end_word=end))
            # Never hide a new sentence in a previous caption. Semicolons and
            # colons may remain within one two-line grammatical group.
            if sentence:
                break
    if 0 not in choices:
        raise ValueError('No complete readable caption partition')
    cues, index = [], 0
    while index < count:
        index, cue = choices[index]
        cues.append(cue)
    lend_caption_margins(cues, words)
    reconstructed = ''.join(c['text'].replace('\n',' ') for c in cues)
    assert re.sub(r'\s+', '', reconstructed) == re.sub(r'\s+', '', source)
    assert all(c['end'] > c['start'] for c in cues)
    assert all(a['end'] <= b['start'] for a,b in zip(cues,cues[1:]))
    return cues


def lend_caption_margins(cues, words):
    """Use <=200 ms of a neighbour's spare reading time without changing audio.

    A caption may anticipate its first spoken word by at most .30 s or start at
    most .15 s after it. The previous cue stays through its last word (with the
    existing .12 s timing allowance). Neighbours never become >20 CPS to lend.
    """
    original = [(c['start'],c['end']) for c in cues]
    def required(cue):
        return len(cue['text'].replace('\n',' '))/20.0 + .001
    for _ in range(3):
        for index, cue in enumerate(cues):
            missing = required(cue)-(cue['end']-cue['start'])
            if missing <= 0:
                continue
            if index:
                previous = cues[index-1]
                available = min(.2-(original[index][0]-cue['start']),
                                previous['end']-previous['start']-required(previous),
                                previous['end']-(words[previous['end_word']-1]['end']-.12),
                                cue['start']-(words[cue['first_word']]['start']-.30))
                borrowed = max(0,min(missing,available))
                cue['start'] -= borrowed
                previous['end'] -= borrowed
                missing -= borrowed
            if missing > 0 and index+1 < len(cues):
                following = cues[index+1]
                available = min(.2-(cue['end']-original[index][1]),
                                following['end']-following['start']-required(following),
                                words[following['first_word']]['start']+.15-following['start'])
                borrowed = max(0,min(missing,available))
                cue['end'] += borrowed
                following['start'] += borrowed
    for cue in cues:
        cue['start'], cue['end'] = round(cue['start'],3),round(cue['end'],3)


def caption_metrics(cues):
    values = sorted(len(c['text'].replace('\n',' '))/(c['end']-c['start']) for c in cues)
    return dict(count=len(values), target_cps=CAPTION_TARGET_CPS, review_cps=CAPTION_REVIEW_CPS,
                maximum_cps=max(values), p95_cps=values[round((len(values)-1)*.95)],
                over_18_count=sum(v>18 for v in values), over_20_count=sum(v>20 for v in values),
                over_22_count=sum(v>22 for v in values),
                reviewed_fast_cues=[dict(start_seconds=c['start'],end_seconds=c['end'],
                                        cps=len(c['text'].replace('\n',' '))/(c['end']-c['start']),
                                        text=c['text']) for c in cues
                                   if len(c['text'].replace('\n',' '))/(c['end']-c['start'])>20])


def insert_pcm_pauses(slow_audio, output, insertions, tail_seconds=.35):
    """Insert exact zero samples into a slowed PCM wave; no voice samples lost."""
    with wave.open(str(slow_audio), 'rb') as source:
        params = source.getparams()
        assert params.sampwidth == 2 and params.comptype == 'NONE'
        frame_bytes = params.nchannels * params.sampwidth
        total_source_frames = params.nframes
        written_source_frames, inserted_frames = 0, 0
        with wave.open(str(output), 'wb') as target:
            target.setparams(params)
            for pause in insertions:
                cut_frame = round(pause['source_cut_seconds'] * params.framerate)
                assert written_source_frames <= cut_frame <= total_source_frames
                target.writeframesraw(source.readframes(cut_frame-written_source_frames))
                written_source_frames = cut_frame
                count = round(pause['added_seconds'] * params.framerate)
                target.writeframesraw(b'\0' * count * frame_bytes)
                inserted_frames += count
            target.writeframesraw(source.readframes(total_source_frames-written_source_frames))
            tail_frames = round(tail_seconds * params.framerate)
            target.writeframesraw(b'\0' * tail_frames * frame_bytes)
    return dict(source_frames=total_source_frames, inserted_frames=inserted_frames,
                tail_frames=tail_frames, sample_rate=params.framerate,
                duration_seconds=(total_source_frames+inserted_frames+tail_frames)/params.framerate)


def visual_frames(scene, layout):
    """Exact phase changes understood by the existing, immutable visual artist."""
    start, end = layout['start_seconds'], layout['end_seconds']
    reveals = layout['reveal_seconds']
    events = [(start, -1.0 if scene['kind']=='field_dialogue' else .001)]
    if scene['kind']=='field_dialogue':
        events += [(reveals['turn_'+str(i)], phase) for i,phase in enumerate((.001,.301,.561))]
    elif scene['kind']=='field_observation':
        events += [(reveals['fact'], .351)]
    elif scene['kind']=='field_documents':
        events += [(reveals['verified'], .361)]
    elif scene['kind']=='field_consequence':
        events += [(reveals['decision'], .301),(reveals['reason'], .571)]
    elif scene['kind']=='field_evolution':
        events += [(reveals['decision'], .301),(reveals['reason'], .571)]
    events = sorted(events)
    return [dict(start_seconds=t, end_seconds=events[i+1][0] if i+1<len(events) else end,
                 phase=phase) for i,(t,phase) in enumerate(events)
            if (events[i+1][0] if i+1<len(events) else end)>t]
