"""Unit tests for Clip model validating edge cases, calculations, and serialization."""

import pytest
from models.clip import Clip


def test_clip_initialization_and_duration():
    """Validates basic initialization and segment duration calculation."""
    clip = Clip(
        file_path="C:/media/video1.mp4",
        name="Intro Scene",
        source_start=5.0,
        source_end=15.5,
        timeline_position=2.0,
    )
    assert clip.file_path == "C:/media/video1.mp4"
    assert clip.name == "Intro Scene"
    assert clip.source_start == 5.0
    assert clip.source_end == 15.5
    assert clip.timeline_position == 2.0
    assert clip.duration == 10.5
    assert clip.id is not None and len(clip.id) > 0


def test_clip_zero_and_negative_duration_edge_cases():
    """Validates duration clamping when in-point equals or exceeds out-point."""
    zero_clip = Clip(
        file_path="dummy.mp4",
        name="Zero Duration",
        source_start=10.0,
        source_end=10.0,
    )
    assert zero_clip.duration == 0.0

    inverted_clip = Clip(
        file_path="dummy.mp4",
        name="Inverted Cuts",
        source_start=15.0,
        source_end=5.0,
    )
    assert inverted_clip.duration == 0.0


def test_clip_frame_count_and_time_to_frame():
    """Validates frame calculation and clamping logic."""
    clip = Clip(
        file_path="dummy.mp4",
        name="Cut Clip",
        source_start=0.0,
        source_end=4.0,
    )
    fps = 30.0
    # 4.0s * 30fps = 120 frames
    assert clip.frame_count(fps=fps) == 120

    # Local time 0.0s -> frame 0
    assert clip.time_to_frame(0.0, fps=fps) == 0

    # Local time 1.0s -> frame 30
    assert clip.time_to_frame(1.0, fps=fps) == 30

    # Local time at exact end (4.0s) -> clamped to max index 119
    assert clip.time_to_frame(4.0, fps=fps) == 119

    # Local time past duration (10.0s) -> clamped to max index 119
    assert clip.time_to_frame(10.0, fps=fps) == 119

    # Negative local time -> clamped to 0
    assert clip.time_to_frame(-2.5, fps=fps) == 0


def test_clip_image_support_and_media_type_detection():
    """Validates static image clips, default and custom image durations, and extension detection."""
    # Automatic detection from filename
    img_clip = Clip(file_path="C:/photos/sunset.PNG", name="Sunset")
    assert img_clip.media_type == "image"
    assert img_clip.is_image is True
    assert img_clip.duration == 5.0  # Default 5.0s

    # Extending image duration
    img_clip.image_duration = 18.5
    assert img_clip.duration == 18.5

    # Image serialization round-trip
    img_dict = img_clip.to_dict()
    assert img_dict["media_type"] == "image"
    assert img_dict["image_duration"] == 18.5

    restored_img = Clip.from_dict(img_dict)
    assert restored_img.is_image is True
    assert restored_img.duration == 18.5


def test_clip_serialization_round_trip():
    """Validates dictionary serialization and deserialization."""
    original = Clip(
        file_path="/path/to/source.mp4",
        name="Drone Shot",
        source_start=12.0,
        source_end=24.0,
        timeline_position=5.0,
    )
    data = original.to_dict()
    assert data["file_path"] == "/path/to/source.mp4"
    assert data["name"] == "Drone Shot"
    assert data["source_start"] == 12.0
    assert data["source_end"] == 24.0
    assert data["timeline_position"] == 5.0
    assert data["id"] == original.id

    restored = Clip.from_dict(data)
    assert restored.file_path == original.file_path
    assert restored.name == original.name
    assert restored.source_start == original.source_start
    assert restored.source_end == original.source_end
    assert restored.timeline_position == original.timeline_position
    assert restored.id == original.id
    assert restored.duration == original.duration


def test_clip_time_stretch_slow_motion_and_source_time_mapping():
    """Validates slow-motion stretching when extending clip duration on timeline."""
    clip = Clip(
        file_path="action.mp4",
        name="Action Shot",
        source_start=2.0,
        source_end=12.0,  # 10.0s source range
        timeline_position=0.0,
    )
    # Default: speed is 1.0x, duration is 10.0s
    assert clip.duration == 10.0
    assert clip.speed == 1.0
    assert clip.get_source_time(0.0) == 2.0
    assert clip.get_source_time(5.0) == 7.0
    assert clip.get_source_time(10.0) == 12.0

    # Extend duration to 20.0s (0.5x half-speed slow motion)
    clip.playback_duration = 20.0
    assert clip.duration == 20.0
    assert clip.speed == 0.5

    # Verify source time maps smoothly across 20s without freezing
    assert clip.get_source_time(0.0) == 2.0
    assert clip.get_source_time(10.0) == 7.0
    assert clip.get_source_time(20.0) == 12.0

    # Serialization round-trip with playback_duration
    data = clip.to_dict()
    assert data["playback_duration"] == 20.0
    restored = Clip.from_dict(data)
    assert restored.duration == 20.0
    assert restored.speed == 0.5
    assert restored.get_source_time(10.0) == 7.0


def test_clip_update_source_times_success_and_validation():
    """Validates update_source_times updates properties, recalculates duration, and enforces strict validation."""
    clip = Clip(
        file_path="video.mp4",
        name="Scene Clip",
        source_start=2.0,
        source_end=10.0,
        timeline_position=0.0,
    )
    assert clip.duration == 8.0

    # 1. Update with valid timestamps
    clip.update_source_times(5.0, 15.5)
    assert clip.source_start == 5.0
    assert clip.source_end == 15.5
    assert clip.duration == 10.5
    assert clip.playback_duration is None

    # 2. Inverted timestamps (end <= start) must raise ValueError
    with pytest.raises(ValueError, match="must be strictly greater than start time"):
        clip.update_source_times(10.0, 5.0)

    # 3. Equal timestamps (end == start) must raise ValueError
    with pytest.raises(ValueError, match="must be strictly greater than start time"):
        clip.update_source_times(8.0, 8.0)

    # 4. Negative start timestamp must raise ValueError
    with pytest.raises(ValueError, match="cannot be negative"):
        clip.update_source_times(-1.0, 10.0)

    # 5. Negative end timestamp must raise ValueError
    with pytest.raises(ValueError, match="cannot be negative"):
        clip.update_source_times(0.0, -5.0)


