"""Unit tests for Track model validating clip sequencing, typing, and serialization."""

import pytest
from models.clip import Clip
from models.track import Track


def test_track_initialization():
    """Validates Track creation with video and audio types."""
    video_track = Track(name="Video 1", track_type="video")
    assert video_track.name == "Video 1"
    assert video_track.track_type == "video"
    assert len(video_track.clips) == 0

    audio_track = Track(name="Audio 1", track_type="audio")
    assert audio_track.name == "Audio 1"
    assert audio_track.track_type == "audio"


def test_track_with_clips():
    """Validates adding clips to a track."""
    track = Track(name="Video Layer")
    clip1 = Clip(file_path="clip1.mp4", name="C1", source_start=0.0, source_end=5.0, timeline_position=0.0)
    clip2 = Clip(file_path="clip2.mp4", name="C2", source_start=0.0, source_end=8.0, timeline_position=6.0)

    track.clips.append(clip1)
    track.clips.append(clip2)

    assert len(track.clips) == 2
    assert track.clips[0].name == "C1"
    assert track.clips[1].name == "C2"


def test_track_split_video_clip():
    """Validates scissors/razor splitting on a video clip."""
    track = Track(name="Video 1")
    clip = Clip(
        file_path="movie.mp4",
        name="Main Scene",
        source_start=10.0,
        source_end=30.0,
        timeline_position=5.0,
    )
    track.clips.append(clip)

    # Split at global timeline 15.0s (offset 10s from clip start 5s)
    res = track.split_clip(clip.id, global_time=15.0)
    assert res is not None
    left, right = res

    # Left clip: starts at 5s, duration 10s, cuts: 10s to 20s
    assert left.timeline_position == 5.0
    assert left.duration == 10.0
    assert left.source_start == 10.0
    assert left.source_end == 20.0

    # Right clip: starts at 15s, duration 10s, cuts: 20s to 30s
    assert right.timeline_position == 15.0
    assert right.duration == 10.0
    assert right.source_start == 20.0
    assert right.source_end == 30.0

    assert len(track.clips) == 2
    assert track.clips[0] is left
    assert track.clips[1] is right


def test_track_split_image_clip():
    """Validates scissors/razor splitting on a static image clip."""
    track = Track(name="Video 1")
    img_clip = Clip(
        file_path="photo.png",
        name="Graphic",
        timeline_position=2.0,
        image_duration=10.0,
    )
    track.clips.append(img_clip)

    res = track.split_clip(img_clip.id, global_time=6.0)
    assert res is not None
    left, right = res

    # Left: starts at 2s, duration 4s
    assert left.timeline_position == 2.0
    assert left.duration == 4.0

    # Right: starts at 6s, duration 6s
    assert right.timeline_position == 6.0
    assert right.duration == 6.0


def test_track_trimming():
    """Validates trimming left in-point and right out-point of clips."""
    track = Track(name="Video 1")
    clip = Clip(
        file_path="test.mp4",
        name="Trim Target",
        source_start=0.0,
        source_end=20.0,
        timeline_position=10.0,
    )
    track.clips.append(clip)

    # Trim left edge: move start from 10.0s to 14.0s
    ok = track.trim_clip_left(clip.id, new_timeline_pos=14.0)
    assert ok is True
    assert clip.timeline_position == 14.0
    assert clip.source_start == 4.0
    assert clip.duration == 16.0

    # Trim right edge: shorten duration to 8.0s
    ok_r = track.trim_clip_right(clip.id, new_duration=8.0)
    assert ok_r is True
    assert clip.duration == 8.0

    # Extend right edge past source range to 32.0s (slow-motion stretch)
    ok_extend = track.trim_clip_right(clip.id, new_duration=32.0)
    assert ok_extend is True
    assert clip.duration == 32.0
    assert clip.speed == (16.0 / 32.0)  # 0.5x speed
    assert clip.get_source_time(16.0) == 4.0 + 8.0  # 12.0s midpoint in source


def test_track_serialization_round_trip():
    """Validates Track serialization to/from dictionary."""
    track = Track(name="Background Music", track_type="audio")
    clip = Clip(file_path="music.mp3", name="Theme", source_start=0.0, source_end=30.0, timeline_position=0.0)
    track.clips.append(clip)

    data = track.to_dict()
    assert data["name"] == "Background Music"
    assert data["track_type"] == "audio"
    assert len(data["clips"]) == 1
    assert data["clips"][0]["name"] == "Theme"

    restored = Track.from_dict(data)
    assert restored.name == track.name
    assert restored.track_type == track.track_type
    assert restored.id == track.id
    assert len(restored.clips) == 1
    assert restored.clips[0].name == "Theme"
    assert restored.clips[0].duration == 30.0
