"""Validate the complete reviewed sequence map and its shipped assets."""
import copy
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from elearning_native.videos import ACADEMY_VIDEOS, activity_videos, bundled_asset_path, enrich_course


def test_exactly_one_bundled_video_in_every_reviewed_sequence():
    maps = json.loads((Path(__file__).parents[1] / "scripts/academy_videos/course_map.json").read_text())
    assert len(ACADEMY_VIDEOS) == len({v["id"] for v in ACADEMY_VIDEOS}) == 17
    for mapping, count in zip(maps, (8, 9)):
        first = urlparse(mapping["sections"][0]["activities"][0]["url"])
        course = {"id": first.path.split("/")[-2], "version": parse_qs(first.query)["version"][0], "sections": []}
        for section in mapping["sections"]:
            activities = [{"id": parse_qs(urlparse(a["url"]).query)["activity"][0],
                           "type": "content" if i < 3 else "question", "blocks": []}
                          for i, a in enumerate(section["activities"])]
            course["sections"].append({"activities": activities})
        original = copy.deepcopy(course)
        result = enrich_course(course)
        assert course == original
        assert enrich_course(result) == result
        assert result["counts"]["required_videos"] == count
        assert len(result["sections"]) == count
        for section in result["sections"]:
            assert [len(activity_videos(a)) for a in section["activities"]] == [0, 0, 1, 0]
        course["version"] = "another-version"
        assert enrich_course(course) == course


def test_all_declared_media_exist_and_are_version_scoped():
    for entry in ACADEMY_VIDEOS:
        assert 30 < entry["duration_seconds"] < 180
        for filename in (entry["filename"], entry["poster"]):
            asset = "media/academy/" + filename
            path = bundled_asset_path(entry["course_id"], entry["course_version"], asset)
            assert path and path.stat().st_size > 1000
            assert bundled_asset_path("other-course", entry["course_version"], asset) is None
            assert bundled_asset_path(entry["course_id"], "other-version", asset) is None
