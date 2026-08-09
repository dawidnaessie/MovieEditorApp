"""Unit tests for Project model validating layering, intervals, duration, and JSON persistence."""

import json
import pytest
from models.clip import Clip
from models.project import Project
from models.track import Track


def test_project_initialization_defaults():
    """Validates default project parameters and track collection."""
    proj = Project(name="Test Short Film")
    assert proj.name == "Test Short Film"
    assert proj.resolution == (1920, 1080)
    assert proj.fps == 30.0
    assert len(proj.tracks) == 0


def test_project_add_tracks():
    """Validates dynamic track creation."""
    proj = Project(name="Layered Project")
    t1 = proj.add_track("Video 1")
    t2 = proj.add_track("Video 2")
    t3 = proj.add_track("Audio 1")

    assert len(proj.tracks) == 3
    assert t1.track_type == "video"
    assert t2.track_type == "video"
    assert t3.track_type == "audio"


def test_project_get_total_duration():
    """Validates total project duration calculation across multiple tracks."""
    proj = Project(name="Duration Test")
    v1 = proj.add_track("Video 1")
    v2 = proj.add_track("Video 2")

    # Clip on V1: 0 to 10s
    v1.clips.append(Clip(file_path="a.mp4", name="A", source_start=0.0, source_end=10.0, timeline_position=0.0))
    # Clip on V2: 8 to 22s
    v2.clips.append(Clip(file_path="b.mp4", name="B", source_start=0.0, source_end=14.0, timeline_position=8.0))

    assert proj.get_total_duration() == 22.0


def test_project_find_clip_at_top_down_layering_and_half_open_intervals():
    """Validates top-down visual precedence (Video 2 > Video 1) and half-open boundary transitions."""
    proj = Project(name="Layering Project")
    v1 = proj.add_track("Video 1")
    v2 = proj.add_track("Video 2")

    # Video 1: 0s to 30s
    v1.clips.append(Clip(file_path="base.mp4", name="Base Layer", source_start=0.0, source_end=30.0, timeline_position=0.0))
    # Video 2: 10s to 20s (overlaps Video 1)
    v2.clips.append(Clip(file_path="overlay.mp4", name="Overlay Layer", source_start=0.0, source_end=10.0, timeline_position=10.0))

    # At 5.0s: Only Video 1 is active
    match_5 = proj.find_clip_at(5.0)
    assert match_5 is not None
    track_5, clip_5, local_5 = match_5
    assert track_5.name == "Video 1"
    assert clip_5.name == "Base Layer"
    assert local_5 == 5.0

    # At 15.0s: Video 2 is on top and takes precedence over Video 1
    match_15 = proj.find_clip_at(15.0)
    assert match_15 is not None
    track_15, clip_15, local_15 = match_15
    assert track_15.name == "Video 2"
    assert clip_15.name == "Overlay Layer"
    assert local_15 == 5.0

    # At 20.0s exact boundary: Video 2 has ended ([10, 20)), cleanly falls back to Video 1 underneath
    match_20 = proj.find_clip_at(20.0)
    assert match_20 is not None
    track_20, clip_20, local_20 = match_20
    assert track_20.name == "Video 1"
    assert clip_20.name == "Base Layer"
    assert local_20 == 20.0

    # At 30.0s (exact project total duration boundary): renders final frame cleanly
    match_30 = proj.find_clip_at(30.0)
    assert match_30 is not None
    track_30, clip_30, local_30 = match_30
    assert track_30.name == "Video 1"
    assert local_30 == 30.0

    # Past total duration (35.0s): returns None (black frame gap)
    assert proj.find_clip_at(35.0) is None


def test_project_find_all_audio_clips_at():
    """Validates multi-track audio interval detection for mixing."""
    proj = Project(name="Audio Project")
    v1 = proj.add_track("Video 1")
    a1 = proj.add_track("Audio 1")

    v1.clips.append(Clip(file_path="dialogue.mp4", name="Dialogue", source_start=0.0, source_end=10.0, timeline_position=0.0))
    a1.clips.append(Clip(file_path="score.mp3", name="Score", source_start=0.0, source_end=20.0, timeline_position=5.0))

    # Overlap window [4.0, 7.0] -> both dialogue (0-10s) and score (5-25s) intersect
    active = proj.find_all_audio_clips_at(start_time=4.0, duration=3.0)
    assert len(active) == 2


def test_project_split_clip_and_lookups():
    """Validates project-level clip lookup and splitting."""
    proj = Project(name="Split Project")
    v1 = proj.add_track("Video 1")
    clip = Clip(file_path="cam.mp4", name="Action", source_start=0.0, source_end=20.0, timeline_position=0.0)
    v1.clips.append(clip)

    track = proj.find_track_for_clip(clip.id)
    assert track is v1

    match = proj.find_clip_by_id(clip.id)
    assert match is not None
    assert match[0] is v1
    assert match[1] is clip

    split_res = proj.split_clip(clip.id, global_time=8.0)
    assert split_res is not None
    left, right = split_res
    assert left.duration == 8.0
    assert right.duration == 12.0
    assert len(v1.clips) == 2


def test_project_json_round_trip():
    """Validates full JSON serialization and deserialization."""
    proj = Project(name="JSON RoundTrip", resolution=(3840, 2160), fps=60.0)
    v1 = proj.add_track("Video 1")
    v1.clips.append(Clip(file_path="shot1.mp4", name="Shot 1", source_start=1.0, source_end=6.0, timeline_position=0.0))

    json_str = proj.to_json()
    assert isinstance(json_str, str)

    restored = Project.from_json(json_str)
    assert restored.name == "JSON RoundTrip"
    assert restored.resolution == (3840, 2160)
    assert restored.fps == 60.0
    assert restored.id == proj.id
    assert len(restored.tracks) == 1
    assert len(restored.tracks[0].clips) == 1
    assert restored.tracks[0].clips[0].name == "Shot 1"
