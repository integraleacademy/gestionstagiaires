"""Reading steps derived from the same lesson fragments as the browser.

No learner data, signed URLs or earned time are cached. The small HTML tree
also follows the VTC paragraph grouping used by aps62-lesson.js, so the policy
does not depend on a client-supplied page count or duration.
"""
from __future__ import annotations

from functools import lru_cache
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATES = {'macaps': '_macaps_lesson.html', 'a3p': '_a3p_lesson.html', 'vtc': '_vtc_activity.html'}
_ENV = Environment(loader=FileSystemLoader(Path(__file__).resolve().parents[1] / 'templates'),
                   autoescape=select_autoescape(['html']))
_VOID = set('area base br col embed hr img input link meta param source track wbr'.split())


class _Node:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def text(self):
        return ''.join(child.text() if isinstance(child, _Node) else child for child in self.children)

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, _Node):
                yield from child.walk()


class _Fragment(HTMLParser):
    def __init__(self, markup):
        super().__init__(convert_charrefs=True)
        self.root = _Node()
        self.stack = [self.root]
        self.feed(markup)
        self.close()

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, value):
        self.stack[-1].children.append(value)


def _group_text(root):
    for container in list(root.walk()):
        if 'data-native-lesson-split' not in container.attrs:
            continue
        chunks, chunk, words, has_body = [], [], 0, False
        for child in [c for c in container.children if isinstance(c, _Node)]:
            heading = bool(re.fullmatch(r'h[1-6]', child.tag))
            size = len(child.text().split())
            if has_body and (heading or words + size > 260):
                chunks.append(chunk)
                chunk, words, has_body = [], 0, False
            chunk.append(child)
            words += size
            if not heading and not set((child.attrs.get('class') or '').split()) & {'vtc-eyebrow', 'aps-label'}:
                has_body = True
        if chunk:
            chunks.append(chunk)
        container.children = []
        for chunk in chunks:
            page = _Node('div', [('data-aps-lesson-page', '')])
            page.children = chunk
            container.children.append(page)


@lru_cache(maxsize=512)
def _pages(family, payload):
    lesson = json.loads(payload)
    # A3P changed presentation, not the content of its reading steps. Retain
    # the issued page IDs and time requirements for sessions already in progress.
    template = '_a3p_reading_identity.html' if family == 'a3p' else TEMPLATES[family]
    root = _Fragment(_ENV.get_template(template).render(activity={family: lesson})).root
    _group_text(root)
    pages, occurrences = [], {}
    for node in root.walk():
        if 'data-aps-lesson-page' not in node.attrs:
            continue
        text = ' '.join(node.text().split())
        digest = sha256(text.encode()).hexdigest()[:20]
        occurrences[digest] = occurrences.get(digest, 0) + 1
        title = next((' '.join(n.text().split()) for n in node.walk() if n.tag in {'h2', 'h3'}),
                     'Repères du cours')
        words = len(text.split())
        # The same tiers as APS: a short recap, a reading step, a dense document.
        seconds = 300 if words >= 500 else 120 if words > 100 else 60
        pages.append({'id': f'{family}-{digest}-{occurrences[digest]}',
                      'title': title, 'required_seconds': seconds, 'word_count': words})
    return tuple(pages)


def reading_pages(activity):
    family = next((key for key in TEMPLATES if activity.get(key, {}).get('kind') == 'lesson'), None)
    if activity.get('type') != 'content' or family is None:
        return []
    pages = []
    for index, block in enumerate(activity.get('blocks', [])):
        video = block.get('video') or {}
        # Video viewing has its own server-controlled ledger. Do not add a
        # second 1/2/5-minute wait to a required video or double its duration.
        pages.append({'id': f'block-{block.get("id") or index}',
                      'title': video.get('title') or 'Ressource du cours',
                      'required_seconds': 0 if video else 60, 'word_count': 0,
                      'video_id': video.get('id') if video.get('required') else None,
                      'media': bool(video)})
    pages.extend(dict(page) for page in _pages(family, json.dumps(activity[family], ensure_ascii=False, sort_keys=True)))
    return pages
