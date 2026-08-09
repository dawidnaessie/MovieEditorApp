"""Integration tests for PyQt6 UI components, event coordination, and asynchronous safety."""

import os
import sys
import numpy as np
import pytest
from PyQt6.QtWidgets import QApplication

from models.clip import Clip
from ui.main_window import MainWindow
from ui.timeline_view import ClipWidget


@pytest.fixture(scope="session")
def qapp():
    """Provides or initializes a persistent QApplication instance."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


@pytest.fixture
def main_window(qapp):
    """Provides an instantiated MainWindow for testing."""
    window = MainWindow()
    yield window
    try:
        window.close()
    except Exception:
        pass


def test_main_window_components(main_window):
    """Validates presence and initialization of core views in MainWindow."""
    assert main_window.player_view is not None
    assert main_window.timeline_view is not None
    assert main_window.media_pool_view is not None
    assert main_window.preview_engine is not None
    assert main_window.project is not None


def test_player_view_playback_and_seeking(main_window):
    """Validates timeline seeking and frame step interactions."""
    # Seek to 5.0s
    main_window._on_timeline_seek(5.0)
    assert main_window.current_playback_time == 5.0
    assert "00:00:05:" in main_window.player_view.lbl_timecode.text()

    # Step frame forward
    main_window.step_frame(1)
    assert main_window.current_playback_time > 5.0

    # Step frame backward
    main_window.step_frame(-1)
    assert main_window.current_playback_time == pytest.approx(5.0, abs=1e-3)


def test_player_view_audio_controls(main_window):
    """Validates volume slider and mute toggle event handling."""
    main_window._on_volume_changed(0.65)
    if hasattr(main_window, "audio_sink") and main_window.audio_sink:
        assert main_window.audio_sink.volume() == pytest.approx(0.65, abs=1e-2)

    main_window._on_mute_toggled(True)
    if hasattr(main_window, "audio_sink") and main_window.audio_sink:
        assert main_window.audio_sink.volume() == 0.0


def test_timeline_clip_selection_and_deletion(main_window):
    """Validates clip addition, selection, and deletion workflow."""
    clip_w = main_window.timeline_view.add_clip(
        track_index=0,
        file_path="sample.mp4",
        timeline_position=0.0,
        duration=10.0,
    )
    assert clip_w is not None

    # Select clip
    clip_w.set_selected(True)
    main_window._on_clip_selected(clip_w)
    assert main_window.selected_clip_widget is clip_w

    # Delete selected clip
    main_window.delete_selected_clip()
    assert main_window.selected_clip_widget is None


def test_clip_boundary_transition_and_smooth_indicator(main_window):
    """Validates monotonic master frame progression across overlapping layered clips."""
    main_window.project.tracks[0].clips.clear()
    main_window.project.tracks[1].clips.clear()

    # Video 1: 0s to 60s
    main_window.project.tracks[0].clips.append(
        Clip(file_path="dummy1.mp4", name="V1_Long", source_start=0.0, source_end=60.0, timeline_position=0.0)
    )
    # Video 2: 10s to 25s (overlay ending in middle of Video 1)
    main_window.project.tracks[1].clips.append(
        Clip(file_path="dummy2.mp4", name="V2_Short", source_start=0.0, source_end=15.0, timeline_position=10.0)
    )

    # 1. Inside Video 2 (24.9s)
    st_before = main_window.preview_engine.get_playback_status(main_window.project, 24.9)
    assert st_before["track_name"] == "Video 2"
    f_before = st_before["current_frame"]

    # 2. Right after Video 2 ends (25.1s) -> falls back to Video 1
    st_after = main_window.preview_engine.get_playback_status(main_window.project, 25.1)
    assert st_after["track_name"] == "Video 1"
    f_after = st_after["current_frame"]

    # Frame counter must increase monotonically (no backward tripping)
    assert f_after > f_before


def test_async_thumbnail_delivery_to_deleted_widget_safety(main_window, qapp):
    """Validates sip.isdeleted protection when thumbnails arrive after ClipWidget deletion."""
    dummy_clip_w = main_window.timeline_view.add_clip(
        track_index=0,
        file_path="dummy.mp4",
        timeline_position=0.0,
        duration=5.0,
    )
    assert dummy_clip_w is not None

    # Delete widget immediately
    main_window.timeline_view.remove_clip_widget(dummy_clip_w)
    qapp.processEvents()

    # Fire background thumbnail delivery
    fake_thumbs = [np.zeros((36, 64, 3), dtype=np.uint8)]
    main_window._on_thumbnails_ready(dummy_clip_w, fake_thumbs, object())


def test_toolbar_mode_switching_and_shortcuts(main_window):
    """Validates ToolbarView tool mode switching between Select and Razor."""
    tb = main_window.timeline_view.toolbar
    assert tb.active_tool == "select"

    # Switch to Razor tool
    main_window.timeline_view.set_active_tool("razor")
    assert tb.active_tool == "razor"
    assert main_window.timeline_view.canvas.active_tool == "razor"

    # Switch back to Select tool
    main_window.timeline_view.set_active_tool("select")
    assert tb.active_tool == "select"
    assert main_window.timeline_view.canvas.active_tool == "select"


def test_razor_split_and_playhead_split(main_window):
    """Validates razor click splitting and split-at-playhead."""
    main_window.project.tracks[0].clips.clear()
    clip = Clip(
        file_path="sample.mp4",
        name="Scene 1",
        source_start=0.0,
        source_end=20.0,
        timeline_position=0.0,
    )
    main_window.project.tracks[0].clips.append(clip)
    main_window._rebuild_timeline_widgets()

    assert len(main_window.project.tracks[0].clips) == 1

    # Split at 8.0s
    main_window._on_split_requested(clip.id, 8.0)
    assert len(main_window.project.tracks[0].clips) == 2
    c1 = main_window.project.tracks[0].clips[0]
    c2 = main_window.project.tracks[0].clips[1]
    assert c1.duration == 8.0
    assert c2.duration == 12.0
    assert c2.timeline_position == 8.0

    # Split at playhead at 14.0s (which falls inside c2)
    main_window.current_playback_time = 14.0
    main_window._on_split_at_playhead()
    assert len(main_window.project.tracks[0].clips) == 3


def test_edge_trimming_signal_handling(main_window):
    """Validates in-point and out-point edge trimming on the timeline."""
    main_window.project.tracks[0].clips.clear()
    clip = Clip(
        file_path="sample.mp4",
        name="Trim Target",
        source_start=0.0,
        source_end=20.0,
        timeline_position=5.0,
    )
    main_window.project.tracks[0].clips.append(clip)
    main_window._rebuild_timeline_widgets()

    clip_w = main_window.timeline_view.canvas.track_strips[0].lane.clip_widgets[0]

    # Trim right edge to 12.0s duration
    main_window._on_trim_requested(clip_w, 12.0, is_left=False)
    assert clip.duration == 12.0

    # Trim left edge to move timeline_pos from 5.0s to 8.0s
    main_window._on_trim_requested(clip_w, 8.0, is_left=True)
    assert clip.timeline_position == 8.0
    assert clip.source_start == 3.0


def test_export_dialog_initialization(main_window):
    """Validates ExportDialog component initialization and preset options."""
    from ui.export_dialog import ExportDialog
    dlg = ExportDialog(main_window.project, main_window)
    assert dlg.combo_format.count() >= 2
    assert dlg.combo_res.count() >= 3
    assert dlg.combo_fps.count() >= 3
    assert dlg.btn_export.isEnabled()
    dlg.close()
