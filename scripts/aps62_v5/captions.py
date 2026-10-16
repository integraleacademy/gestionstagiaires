"""Align TTS word timings to authored punctuation; never invent a transcript."""
import re
import unicodedata


def canonical(text):
    return ''.join(c for c in unicodedata.normalize('NFD', text.lower())
                   if c.isalnum())


def align_words(source, boundaries):
    positions = []
    normalized = ''
    for index, character in enumerate(source):
        chars = canonical(character)
        normalized += chars
        positions.extend([index] * len(chars))
    observed = ''.join(canonical(w['text']) for w in boundaries)
    if observed != normalized:
        raise ValueError('Speech boundaries do not match the authored text: ' + source[:90])
    starts, cursor = [], 0
    for word in boundaries:
        starts.append(positions[cursor])
        cursor += len(canonical(word['text']))
    aligned = []
    for i, word in enumerate(boundaries):
        start = 0 if i == 0 else starts[i]
        end = starts[i + 1] if i + 1 < len(starts) else len(source)
        aligned.append(dict(text=source[start:end].strip(),
            start=word['offset'] / 1e7,
            end=(word['offset'] + word['duration']) / 1e7))
    return aligned


def wrap_caption(text, width=44):
    if len(text) <= width:
        return text
    words = text.split()
    candidates = []
    for n in range(1, len(words)):
        left, right = ' '.join(words[:n]), ' '.join(words[n:])
        if max(len(left), len(right)) > width:
            continue
        # Avoid separating short grammatical groups where another break fits.
        dangling = words[n-1].lower() in {'de', 'du', 'des', 'le', 'la', 'les', 'un', 'une', 'à', 'et', 'en', 'pour', 'ne'}
        score = abs(len(left) - len(right)) + (18 if dangling else 0)
        if re.search(r'[,;:]$', left):
            score -= 8
        candidates.append((score, left + '\n' + right))
    return min(candidates)[1] if candidates else None


def make_cues(source, boundaries):
    words = align_words(source, boundaries)
    cues, index = [], 0
    while index < len(words):
        candidates = []
        for end in range(index + 1, len(words) + 1):
            group = words[index:end]
            text = ' '.join(w['text'] for w in group)
            wrapped = wrap_caption(text)
            if wrapped is None or group[-1]['end'] - group[0]['start'] > 6.2:
                break
            candidates.append((end, wrapped))
            if re.search(r'[.!?]$', text):
                break
        if not candidates:
            raise ValueError('Caption cannot fit: ' + words[index]['text'])
        end, wrapped = candidates[-1]
        # Prefer an earlier clause boundary over a split in the middle of a clause.
        for candidate_end, candidate_text in reversed(candidates):
            if len(candidate_text) >= 32 and re.search(r'[,;:.!?]$', candidate_text):
                end, wrapped = candidate_end, candidate_text
                break
        start = max(0, words[index]['start'] - .06)
        next_start = words[end]['start'] - .07 if end < len(words) else words[end-1]['end'] + .35
        finish = min(next_start, max(words[end-1]['end'] + .22, start + 1.2))
        cues.append(dict(start=round(start, 3), end=round(finish, 3), text=wrapped))
        index = end
    reconstructed = ' '.join(c['text'].replace('\n', ' ') for c in cues)
    # Apostrophes can be separate word boundaries. Compare spacing-insensitive text,
    # including all punctuation, so nothing disappears from the captions.
    assert re.sub(r'\s+', '', reconstructed) == re.sub(r'\s+', '', source)
    return cues


def timestamp(seconds, separator='.'):
    ms = round(seconds * 1000)
    return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02}{separator}{ms%1000:03}'
