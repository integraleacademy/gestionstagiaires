"""Versioned Academy videos and mandatory-viewing rules.

The imported course remains untouched on disk. Enrichments are explicitly
bound to a reviewed course version and activity, and ship with the application.
"""
from __future__ import annotations

import copy
import math
from pathlib import Path
from typing import Any, Mapping


ACADEMY_VIDEOS = ({
    "course_id": "eg-3c985ae8a9fe4dd6a5842605f952cb39",
    "course_version": "20260907-141439-975",
    "activity_id": "91d2d66063374f0f9ea3cb268859b3a6",
    "id": "aps-missions-limites-20260920-graphic",
    "filename": "aps-missions-limites-20260920.mp4",
    "poster": "aps-missions-limites-20260920.jpg",
    "duration_seconds": 99.44,
    "title": "Missions et limites de l’agent de sécurité",
},)


def enrich_course(course: dict) -> dict:
    applicable = [video for video in ACADEMY_VIDEOS
                  if (video["course_id"], video["course_version"]) == (course.get("id"), course.get("version"))]
    if not applicable:
        return course
    enriched = copy.deepcopy(course)
    for entry in applicable:
        for section in enriched.get("sections") or []:
            for activity in section.get("activities") or []:
                if activity.get("id") != entry["activity_id"] or activity.get("type") != "content":
                    continue
                blocks = activity.setdefault("blocks", [])
                if any(block.get("id") == entry["id"] for block in blocks):
                    continue
                blocks.insert(0, {"id": entry["id"], "type": "video", "html": "", "children": [], "video": {
                    "id": entry["id"], "title": entry["title"], "required": True,
                    "src": "media/academy/" + entry["filename"],
                    "poster": "media/academy/" + entry["poster"],
                    "duration_seconds": entry["duration_seconds"],
                }})
    return enriched


def bundled_asset_path(course_id: str, version: str, asset_name: str) -> Path | None:
    for video in ACADEMY_VIDEOS:
        if (course_id, version) != (video["course_id"], video["course_version"]):
            continue
        for name in (video["filename"], video["poster"]):
            if asset_name == "media/academy/" + name:
                path = Path(__file__).parent / "media" / name
                return path if path.is_file() else None
    return None


def activity_videos(activity: Mapping[str, Any]) -> dict[str, float]:
    result = {}
    pending = list(activity.get("blocks") or [])
    while pending:
        block = pending.pop()
        if not isinstance(block, Mapping):
            continue
        pending.extend(block.get("children") or [])
        video = block.get("video")
        if not isinstance(video, Mapping) or not video.get("required"):
            continue
        video_id = str(video.get("id") or block.get("id") or "")
        duration = float(video.get("duration_seconds") or 0)
        if not video_id or not math.isfinite(duration) or duration <= 0:
            raise ValueError("Métadonnées de vidéo obligatoire invalides.")
        result[video_id] = duration
    return result


def course_videos(course: Mapping[str, Any]) -> dict[str, dict[str, float]]:
    return {str(activity["id"]): videos
            for section in course.get("sections") or []
            for activity in section.get("activities") or []
            if (videos := activity_videos(activity))}


def videos_complete(saved: Mapping[str, Any], requirements: Mapping[str, float]) -> bool:
    return all(isinstance((state := saved.get(video_id)), Mapping)
               and state.get("completed") is True
               and state.get("duration_seconds") == duration
               and float(state.get("watched_seconds") or 0) >= duration - .25
               for video_id, duration in requirements.items())


def video_blocker(course: Mapping[str, Any], progress: Mapping[str, Any], activity_id: str) -> str:
    """Mandatory videos block every later activity, including direct URLs."""
    requirements = course_videos(course)
    saved = progress.get("video_progress") or {}
    for prior in course.get("activity_order") or []:
        if prior == activity_id:
            break
        if prior in requirements and not videos_complete(saved.get(prior, {}), requirements[prior]):
            return prior
    return ""
