"""Lossless captions selected against the real spoken word timeline.

The comfort targets are measured at the player's default 0.85 rate: at least
one second, at most twenty visible characters per second, and two 44-character
lines. A shortest-path segmentation avoids greedy one-word sentence fragments.
"""
import re

from scripts.aps62_v5.captions import align_words, wrap_caption

PLAYBACK_RATE = .85
MAX_CPS = 20.
MIN_NATIVE_SECONDS = .85


def make_cues(source, boundaries, scene_end=None, *, playback_rate=PLAYBACK_RATE):
    if playback_rate not in (.85, 1):
        raise ValueError('Unsupported caption playback rate')
    words = align_words(source, boundaries)
    if not words:
        raise ValueError('No narrated words')
    # Assess the millisecond precision actually written to VTT/HTML, so later
    # timestamp rounding cannot turn a passing density into a failing cue.
    edges = [round(max(0., word['start']-.06),3) for word in words]
    edges.append(round(max(words[-1]['end']+.35, scene_end-.1 if scene_end else 0),3))
    # Paths contain groups of complete provider words, never inferred timing.
    best = [None]*(len(words)+1)
    best[-1] = (0., [])
    for start in range(len(words)-1, -1, -1):
        candidates = []
        for end in range(start+1, len(words)+1):
            text = ' '.join(word['text'] for word in words[start:end])
            wrapped = wrap_caption(text)
            if wrapped is None:
                break
            seconds = edges[end]-edges[start]
            if seconds > 7.5:
                break
            if best[end] is None or seconds < playback_rate-.0001:
                continue
            count = len(wrapped.replace('\n', ' '))
            if count*playback_rate/seconds > MAX_CPS-.005:
                continue
            punctuation = re.search(r'[.!?;:,][»”\"\']?$', text)
            dangling = words[end-1]['text'].lower() in {'de','du','des','le','la','les','un','une','à','et','en','pour','ne'}
            penalty = 1.+(0 if punctuation else 3.)+(6. if dangling else 0.)
            penalty += abs(seconds-3.8)*.10
            candidates.append((penalty+best[end][0], [(start,end,wrapped)]+best[end][1]))
        if candidates:
            best[start] = min(candidates, key=lambda value:value[0])
    if best[0] is None:
        if playback_rate == 1:
            return flexible_cues(source, words, edges)
        raise ValueError('Narration needs a natural reading break: '+source[:120])
    cues = [dict(start=round(edges[start],3),end=round(edges[end],3),text=text)
            for start,end,text in best[0][1]]
    assert re.sub(r'\s+','', ''.join(cue['text'] for cue in cues)) == re.sub(r'\s+','',source)
    return cues


def flexible_cues(source, words, edges):
    """Allow a small display lag without changing the narration or word timings.

    Long French words can require an extra fraction of a second on screen. A
    boundary may lead the next word by at most .16s or lag it by at most .39s;
    the original strict segmentation remains the preferred/default path.
    """
    positions = [sorted({round(max(0., edge+shift),3) for shift in (-.10,0,.15,.30,.45)})
                 for edge in edges[:-1]] + [[edges[-1]]]
    positions[0] = [edges[0]]
    best = {(len(words), edges[-1]): (0., [])}
    for start in range(len(words)-1,-1,-1):
        for at in positions[start]:
            candidates = []
            for end in range(start+1,len(words)+1):
                text = ' '.join(word['text'] for word in words[start:end])
                wrapped = wrap_caption(text)
                if wrapped is None:
                    break
                for until in positions[end]:
                    following = best.get((end,until))
                    seconds = until-at
                    if following is None or not 1 <= seconds <= 7.5:
                        continue
                    if len(wrapped.replace('\n',' '))/seconds > MAX_CPS-.005:
                        continue
                    punctuation = re.search(r'[.!?;:,][»”"\']?$',text)
                    penalty = 1+(0 if punctuation else 3)+abs(until-edges[end])*8
                    candidates.append((penalty+following[0], [dict(start=at,end=until,text=wrapped)]+following[1]))
            if candidates:
                best[(start,at)] = min(candidates,key=lambda value:value[0])
    result = best.get((0,edges[0]))
    if result is None:
        raise ValueError('Narration needs a natural reading break: '+source[:120])
    cues = result[1]
    assert re.sub(r'\s+','', ''.join(cue['text'] for cue in cues)) == re.sub(r'\s+','',source)
    return cues
