"""Compose reviewed media timeline mappings for stored learner progress."""
from typing import Mapping

from .aps_media import compatible_record as aps_record
from .vtc_video_quality import compatible_record as vtc_record


def compatible_record(video_id, record, duration):
    return aps_record(video_id, vtc_record(video_id, record, duration), duration)


def compatible_progress(saved, requirements):
    result = dict(saved)
    for activity_id, videos in requirements.items():
        records = saved.get(activity_id)
        if not isinstance(records, Mapping):
            continue
        result[activity_id] = {
            vid: compatible_record(vid, state, videos[vid]) if vid in videos else state
            for vid, state in records.items()
        }
    return result
