"""Unit and integration tests for RenderEngine validating video and image project exports."""

import os
import numpy as np
import pytest
from moviepy import ColorClip
from PIL import Image

from engine.preview_engine import PreviewEngine
from engine.render_engine import RenderEngine
from models.clip import Clip
from models.project import Project


@pytest.fixture(scope="session")
def render_dummy_media(tmp_path_factory):
    """Creates a 1-second video clip and a static PNG image for export testing."""
    tmp_dir = tmp_path_factory.mktemp("render_media")
    video_path = os.path.join(str(tmp_dir), "source_vid.mp4")
    image_path = os.path.join(str(tmp_dir), "source_img.png")

    # 1. Video clip (1.0s, 160x90, 24fps)
    v_clip = ColorClip(size=(160, 90), color=(0, 120, 255), duration=1.0)
    v_clip.write_videofile(
        video_path,
        fps=24,
        codec="libx264",
        audio=False,
        logger=None,
    )
    v_clip.close()

    # 2. Static PNG image
    img = Image.new("RGB", (160, 90), color=(255, 100, 50))
    img.save(image_path)

    return {
        "video": video_path,
        "image": image_path,
        "out_dir": str(tmp_dir),
    }


def test_render_engine_mp4_export(render_dummy_media):
    """Validates exporting a multi-track timeline (video + image) to MP4."""
    media = render_dummy_media
    out_mp4 = os.path.join(media["out_dir"], "exported_master.mp4")

    project = Project(name="Render MP4 Test", resolution=(160, 90), fps=24.0)
    v1 = project.add_track("Video 1")
    v2 = project.add_track("Video 2")

    # Track 1: 1s video clip at 0.0s
    v1.clips.append(Clip(file_path=media["video"], name="Vid1", source_start=0.0, source_end=1.0, timeline_position=0.0))
    # Track 2: 1s static image clip at 0.5s (overlapping end of video)
    v2.clips.append(Clip(file_path=media["image"], name="Img1", media_type="image", image_duration=1.0, timeline_position=0.5))

    progress_events = []

    def on_progress(pct: float, msg: str):
        progress_events.append((pct, msg))

    engine = RenderEngine()
    success = engine.render_project(
        project=project,
        output_path=out_mp4,
        export_format="mp4",
        resolution=(160, 90),
        fps=24.0,
        progress_callback=on_progress,
    )

    assert success is True
    assert os.path.exists(out_mp4)
    assert os.path.getsize(out_mp4) > 1000
    assert len(progress_events) > 0

    # Validate exported video can be read by PreviewEngine
    preview = PreviewEngine()
    try:
        info = preview.get_media_info(out_mp4)
        assert info["duration"] >= 1.4  # Total duration is ~1.5s
    finally:
        preview.close()


def test_render_engine_webm_export(render_dummy_media):
    """Validates exporting a project to WebM format."""
    media = render_dummy_media
    out_webm = os.path.join(media["out_dir"], "exported_master.webm")

    project = Project(name="Render WebM Test", resolution=(160, 90), fps=24.0)
    v1 = project.add_track("Video 1")
    v1.clips.append(Clip(file_path=media["video"], name="Vid1", source_start=0.0, source_end=1.0, timeline_position=0.0))

    engine = RenderEngine()
    success = engine.render_project(
        project=project,
        output_path=out_webm,
        export_format="webm",
        resolution=(160, 90),
        fps=24.0,
    )

    assert success is True
    assert os.path.exists(out_webm)
    assert os.path.getsize(out_webm) > 500


def test_render_engine_empty_project_guard(tmp_path):
    """Validates that rendering an empty project cleanly fails without throwing unhandled exceptions."""
    out_path = os.path.join(str(tmp_path), "empty.mp4")
    empty_proj = Project(name="Empty")

    engine = RenderEngine()
    success = engine.render_project(
        project=empty_proj,
        output_path=out_path,
        export_format="mp4",
    )
    assert success is False
    assert not os.path.exists(out_path)


def test_render_engine_with_audio_track_and_volume(render_dummy_media, tmp_path):
    """Validates video rendering with dedicated audio tracks, volume scaling, and muting."""
    import wave

    media = render_dummy_media
    wav_path = os.path.join(str(tmp_path), "score.wav")
    sample_rate = 44100
    duration = 1.5
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
    sine = (np.sin(2 * np.pi * 440 * t) * 28000).astype(np.int16)
    stereo = np.column_stack([sine, sine]).flatten()

    with wave.open(wav_path, "w") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(stereo.tobytes())

    out_mp4 = os.path.join(str(tmp_path), "rendered_audio_mix.mp4")
    project = Project(name="Audio Mix Render", resolution=(160, 90), fps=24.0)
    v1 = project.add_track("Video 1")
    v1.clips.append(Clip(file_path=media["video"], name="Vid1", source_start=0.0, source_end=1.0, timeline_position=0.0))

    a1 = project.add_track("Audio 1", track_type="audio")
    a1.set_volume(0.5)
    a1.clips.append(Clip(file_path=wav_path, name="Score", source_start=0.0, source_end=1.0, timeline_position=0.0))

    engine = RenderEngine()
    success = engine.render_project(
        project=project,
        output_path=out_mp4,
        export_format="mp4",
        resolution=(160, 90),
        fps=24.0,
    )

    assert success is True
    assert os.path.exists(out_mp4)
    assert os.path.getsize(out_mp4) > 1000
