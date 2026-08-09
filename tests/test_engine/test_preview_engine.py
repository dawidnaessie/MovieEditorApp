"""Unit and integration tests for PreviewEngine using programmatically generated dummy media."""

import os
import numpy as np
import pytest
from moviepy import ColorClip
from PIL import Image
from engine.preview_engine import PreviewEngine
from models.clip import Clip
from models.project import Project


@pytest.fixture(scope="session")
def dummy_video_file(tmp_path_factory):
    """Generates a small, lightweight 1-second solid color video clip for fast testing."""
    tmp_dir = tmp_path_factory.mktemp("media")
    video_path = os.path.join(str(tmp_dir), "dummy_test.mp4")

    # Generate a 1-second 120x80 red clip at 24 fps
    clip = ColorClip(size=(120, 80), color=(255, 0, 0), duration=1.0)
    clip.write_videofile(
        video_path,
        fps=24,
        codec="libx264",
        audio=False,
        logger=None,
    )
    clip.close()

    yield video_path


def test_preview_engine_media_info_and_duration(dummy_video_file):
    """Validates metadata extraction for a video file."""
    engine = PreviewEngine()
    try:
        info = engine.get_media_info(dummy_video_file)
        assert info is not None
        assert info["fps"] > 0
        assert info["duration"] > 0
        assert len(info["size"]) == 2

        duration = engine.get_media_duration(dummy_video_file)
        assert duration > 0
    finally:
        engine.close()


def test_preview_engine_get_frame(dummy_video_file):
    """Validates RGB frame extraction from Clip model."""
    engine = PreviewEngine()
    try:
        clip = Clip(
            file_path=dummy_video_file,
            name="Dummy",
            source_start=0.0,
            source_end=1.0,
            timeline_position=0.0,
        )
        frame = engine.get_frame(clip, time_in_seconds=0.2)
        assert isinstance(frame, np.ndarray)
        assert frame.ndim == 3
        assert frame.shape[2] == 3
        assert frame.dtype == np.uint8
        # Red clip: dominant red channel
        assert frame[..., 0].mean() > 180
    finally:
        engine.close()


def test_preview_engine_get_project_frame_and_gaps(dummy_video_file):
    """Validates project composite frame rendering and black frames in gaps."""
    engine = PreviewEngine()
    try:
        project = Project(name="Project Frame Test", resolution=(120, 80), fps=24.0)
        v1 = project.add_track("Video 1")
        # Clip placed at 5.0s to 6.0s
        v1.clips.append(Clip(file_path=dummy_video_file, name="Clip1", source_start=0.0, source_end=1.0, timeline_position=5.0))

        # At 5.5s -> inside clip (red frame)
        active_frame = engine.get_project_frame(project, global_time=5.5)
        assert active_frame.shape == (80, 120, 3)
        assert active_frame[..., 0].mean() > 180

        # At 1.0s -> empty timeline gap (solid black frame)
        black_frame = engine.get_project_frame(project, global_time=1.0)
        assert black_frame.shape == (80, 120, 3)
        assert black_frame.mean() == 0.0
    finally:
        engine.close()


def test_preview_engine_thumbnails(dummy_video_file):
    """Validates thumbnail filmstrip generation."""
    engine = PreviewEngine()
    try:
        thumbs = engine.extract_clip_thumbnails(
            dummy_video_file,
            source_start=0.0,
            duration=1.0,
            count=3,
            thumb_height=36,
        )
        assert len(thumbs) == 3
        for thumb in thumbs:
            assert isinstance(thumb, np.ndarray)
            assert thumb.shape[0] == 36
            assert thumb.shape[2] == 3
    finally:
        engine.close()


def test_preview_engine_timecode_formatting():
    """Validates SMPTE timecode string formatting."""
    assert PreviewEngine.format_timecode(0.0, fps=30.0) == "00:00:00:00"
    assert PreviewEngine.format_timecode(1.0, fps=30.0) == "00:00:01:00"
    assert PreviewEngine.format_timecode(65.5, fps=30.0) == "00:01:05:15"
    assert PreviewEngine.format_timecode(3661.0, fps=30.0) == "01:01:01:00"


def test_preview_engine_playback_status(dummy_video_file):
    """Validates playback status metadata dictionary."""
    engine = PreviewEngine()
    try:
        project = Project(name="Status Test", fps=30.0)
        v1 = project.add_track("Video 1")
        v1.clips.append(Clip(file_path=dummy_video_file, name="Status Clip", source_start=0.0, source_end=1.0, timeline_position=5.0))

        # Status inside clip (5.2s)
        st_active = engine.get_playback_status(project, global_time=5.2)
        assert st_active["has_active_clip"] is True
        assert st_active["clip_name"] == "Status Clip"
        assert st_active["track_name"] == "Video 1"
        assert st_active["current_frame"] == int(round(5.2 * 30.0)) + 1
        assert "00:00:05:" in st_active["timecode"]

        # Status in gap (2.0s)
        st_gap = engine.get_playback_status(project, global_time=2.0)
        assert st_gap["has_active_clip"] is False
        assert st_gap["clip_name"] == "No Active Clip"
        assert st_gap["current_frame"] == int(round(2.0 * 30.0)) + 1
    finally:
        engine.close()


def test_preview_engine_static_image_support(tmp_path):
    """Validates frame extraction, metadata, and thumbnails for static PNG/JPG images."""
    img_path = os.path.join(str(tmp_path), "test_graphic.png")
    img = Image.new("RGB", (320, 240), color=(0, 255, 120))
    img.save(img_path)

    engine = PreviewEngine()
    try:
        # 1. Image metadata
        info = engine.get_media_info(img_path)
        assert info["size"] == [320, 240]
        assert info["duration"] == 5.0

        # 2. Image frame decoding
        img_clip = Clip(file_path=img_path, name="Graphic", media_type="image", image_duration=8.0)
        frame = engine.get_frame(img_clip, time_in_seconds=3.5)
        assert isinstance(frame, np.ndarray)
        assert frame.shape == (240, 320, 3)
        assert frame[..., 1].mean() > 200  # Green channel

        # 3. Image thumbnails
        thumbs = engine.extract_clip_thumbnails(img_path, source_start=0.0, duration=8.0, count=4, thumb_height=36)
        assert len(thumbs) == 4
        assert thumbs[0].shape[0] == 36
    finally:
        engine.close()


def test_preview_engine_audio_pcm(dummy_video_file):
    """Validates audio PCM synthesis without crashing on video-only or empty files."""
    engine = PreviewEngine()
    try:
        project = Project(name="Audio PCM Test")
        v1 = project.add_track("Video 1")
        v1.clips.append(Clip(file_path=dummy_video_file, name="Clip", source_start=0.0, source_end=1.0, timeline_position=0.0))

        pcm = engine.get_project_audio_pcm(project, start_time=0.0, duration=0.5, sample_rate=44100)
        assert isinstance(pcm, bytes)
        # 0.5s * 44100 samples * 2 channels * 2 bytes/sample = 88200 bytes
        assert len(pcm) == int(0.5 * 44100 * 2 * 2)
    finally:
        engine.close()
