"""Integration tests for PyQt6 UI components, event coordination, and asynchronous safety."""

import os
import sys
import numpy as np
import pytest
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QMouseEvent
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
    main_window.project.tracks[0].clips.append(
        Clip(file_path="sample.mp4", name="Sample", source_start=0.0, source_end=20.0, timeline_position=0.0)
    )
    main_window.timeline_view.set_max_duration(main_window.get_max_timeline_duration())

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

    # Extend right edge to 40.0s (slow-motion stretch: source range 17.0s over 40.0s = 0.425x)
    main_window._on_trim_requested(clip_w, 40.0, is_left=False)
    assert clip.duration == 40.0
    assert abs(clip.speed - (17.0 / 40.0)) < 1e-4
    assert "(0.42x)" in clip_w.lbl_dur.text() or "(0.43x)" in clip_w.lbl_dur.text()


def test_export_dialog_initialization(main_window):
    """Validates ExportDialog component initialization and preset options."""
    from ui.export_dialog import ExportDialog
    dlg = ExportDialog(main_window.project, main_window)
    assert dlg.combo_format.count() >= 2
    assert dlg.combo_res.count() >= 3
    assert dlg.combo_fps.count() >= 3
    assert dlg.btn_export.isEnabled()
    dlg.close()


def test_timeline_zoom_controls_and_scaling(main_window):
    """Validates timeline zoom level adjustments, clip width scaling, and fit-to-screen."""
    main_window.project.tracks[0].clips.clear()
    clip = Clip(
        file_path="sample.mp4",
        name="Zoom Target",
        source_start=0.0,
        source_end=10.0,
        timeline_position=2.0,
    )
    main_window.project.tracks[0].clips.append(clip)
    main_window._rebuild_timeline_widgets()

    clip_w = main_window.timeline_view.canvas.track_strips[0].lane.clip_widgets[0]
    initial_w = clip_w.width()

    # 1. Zoom in
    main_window.timeline_view.set_zoom_level(50.0)
    assert main_window.timeline_view.canvas.pixels_per_second == 50.0
    assert clip_w.width() > initial_w

    # 2. Zoom out (make timeline smaller / shorter ratio)
    main_window.timeline_view.set_zoom_level(5.0)
    assert main_window.timeline_view.canvas.pixels_per_second == 5.0
    assert clip_w.width() < initial_w
    assert clip_w.x() == int(2.0 * 5.0)  # 10px

    # 3. Fit to screen
    main_window.timeline_view.zoom_fit_to_screen()
    assert main_window.timeline_view.canvas.pixels_per_second >= 2.0


def test_clip_drag_moving_and_ruler_only_scrubbing(main_window):
    """Validates clip drag-to-move repositioning and ruler-restricted playhead scrubbing."""
    main_window.project.tracks[0].clips.clear()
    clip = Clip(
        file_path="sample.mp4",
        name="Move Target",
        source_start=0.0,
        source_end=10.0,
        timeline_position=0.0,
    )
    main_window.project.tracks[0].clips.append(clip)
    main_window._rebuild_timeline_widgets()

    clip_w = main_window.timeline_view.canvas.track_strips[0].lane.clip_widgets[0]
    assert clip.timeline_position == 0.0

    # 1. Move clip from 0.0s to 15.5s
    main_window._on_clip_moved(clip_w, 15.5)
    assert clip.timeline_position == 15.5
    assert main_window.get_max_timeline_duration() >= 25.5

    # 2. Ruler scrubbing validation
    canvas = main_window.timeline_view.canvas
    assert canvas.ruler_height == 30

    # Clicking ruler at y=15 triggers scrubbing
    from PyQt6.QtCore import QPointF
    from PyQt6.QtGui import QMouseEvent
    event_ruler = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPointF(230, 15),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    canvas.mousePressEvent(event_ruler)
    assert canvas.is_scrubbing is True

    # Clicking lane below ruler at y=50 does NOT trigger scrubbing
    canvas.is_scrubbing = False
    event_lane = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPointF(230, 50),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    canvas.mousePressEvent(event_lane)
    assert canvas.is_scrubbing is False


def test_cross_track_clip_moving_between_video1_and_video2(main_window):
    """Validates moving clip parts between Video 1 and Video 2 dynamically."""
    main_window.project.tracks[0].clips.clear()
    main_window.project.tracks[1].clips.clear()

    clip = Clip(
        file_path="sample.mp4",
        name="Layered Clip",
        source_start=0.0,
        source_end=20.0,
        timeline_position=0.0,
    )
    main_window.project.tracks[0].clips.append(clip)
    main_window._rebuild_timeline_widgets()

    # Verify initial state: 1 clip on Video 1, 0 on Video 2
    assert len(main_window.project.tracks[0].clips) == 1
    assert len(main_window.project.tracks[1].clips) == 0

    # 1. Split clip at 10.0s into two parts
    main_window._on_split_requested(clip.id, 10.0)
    assert len(main_window.project.tracks[0].clips) == 2
    part1 = main_window.project.tracks[0].clips[0]
    part2 = main_window.project.tracks[0].clips[1]
    assert part1.duration == 10.0
    assert part2.duration == 10.0

    # 2. Move part2 from Video 1 (idx 0) to Video 2 (idx 1) at timeline position 5.0s
    clip_w2 = [cw for cw in main_window.timeline_view.canvas.track_strips[0].lane.clip_widgets if cw.clip_id == part2.id][0]
    main_window._on_clip_moved(clip_w2, new_timeline_pos=5.0, target_track_index=1)

    # Verify part1 remains on Video 1, part2 is now on Video 2
    assert len(main_window.project.tracks[0].clips) == 1
    assert len(main_window.project.tracks[1].clips) == 1
    assert main_window.project.tracks[0].clips[0].id == part1.id
    assert main_window.project.tracks[1].clips[0].id == part2.id
    assert part2.timeline_position == 5.0

    # Verify widgets were rebuilt on the proper track strips
    video1_widgets = main_window.timeline_view.canvas.track_strips[0].lane.clip_widgets
    video2_widgets = main_window.timeline_view.canvas.track_strips[1].lane.clip_widgets
    assert len(video1_widgets) == 1
    assert len(video2_widgets) == 1
    assert video2_widgets[0].clip_id == part2.id

    # 3. Move part2 back from Video 2 (idx 1) to Video 1 (idx 0) at 12.0s
    main_window._on_clip_moved(video2_widgets[0], new_timeline_pos=12.0, target_track_index=0)
    assert len(main_window.project.tracks[0].clips) == 2
    assert len(main_window.project.tracks[1].clips) == 0
    assert part2.timeline_position == 12.0


def test_media_pool_custom_length_controls(main_window, tmp_path):
    """Validates selecting videos on the left side, setting custom length (e.g. 0.2s), and normal 1.0x playback speed."""
    mp = main_window.media_pool_view
    mp.list_widget.clear()
    mp.custom_durations.clear()
    main_window._load_thumbnails_async = lambda *args, **kwargs: None
    import numpy as np
    main_window.preview_engine.get_project_frame = lambda *args, **kwargs: np.zeros((100, 100, 3), dtype=np.uint8)

    fake_file1 = str(tmp_path / "vid1.mp4")
    fake_file2 = str(tmp_path / "vid2.mp4")
    with open(fake_file1, "wb") as f:
        f.write(b"0" * 100)
    with open(fake_file2, "wb") as f:
        f.write(b"0" * 100)

    mp.add_media_item(fake_file1)
    mp.add_media_item(fake_file2)

    assert mp.list_widget.count() == 2

    # 1. Select video 1 and set custom length to 0.2s using spinbox
    mp.list_widget.item(0).setSelected(True)
    mp.list_widget.item(1).setSelected(False)
    mp.spin_length.setValue(0.20)
    mp.btn_apply_length.click()

    assert mp.get_custom_duration(fake_file1) == pytest.approx(0.20)
    assert mp.get_custom_duration(fake_file2) is None
    assert "0.20s" in mp.list_widget.item(0).text()

    # 2. Select both videos and apply 0.5s preset
    mp.list_widget.item(0).setSelected(True)
    mp.list_widget.item(1).setSelected(True)
    mp._on_preset_clicked(0.50)

    assert mp.get_custom_duration(fake_file1) == pytest.approx(0.50)
    assert mp.get_custom_duration(fake_file2) == pytest.approx(0.50)
    assert "0.50s" in mp.list_widget.item(0).text()
    assert "0.50s" in mp.list_widget.item(1).text()

    # 3. Drop video onto timeline track with mock duration and verify it ends after 0.5s at 1.0x speed
    main_window.project.tracks[0].clips.clear()
    # Mock media duration to 10.0s
    main_window.preview_engine.get_media_duration = lambda path: 10.0

    main_window._on_clip_dropped(fake_file1, track_index=0, timeline_pos=0.0)
    assert len(main_window.project.tracks[0].clips) == 1
    clip = main_window.project.tracks[0].clips[0]
    assert clip.duration == pytest.approx(0.50)
    assert clip.source_start == 0.0
    assert clip.source_end == pytest.approx(0.50)
    assert clip.playback_duration is None
    assert clip.speed == pytest.approx(1.0)

    # 4. Reset duration back to original
    mp.list_widget.item(0).setSelected(True)
    mp.list_widget.item(1).setSelected(True)
    mp._on_reset_clicked()
    assert mp.get_custom_duration(fake_file1) is None
    assert mp.get_custom_duration(fake_file2) is None


def test_media_pool_batch_insert_to_timeline(main_window, tmp_path):
    """Validates multi-selecting videos on the left side and batch inserting them onto the timeline at 0.2s each."""
    mp = main_window.media_pool_view
    mp.list_widget.clear()
    mp.custom_durations.clear()
    main_window._load_thumbnails_async = lambda *args, **kwargs: None
    import numpy as np
    main_window.preview_engine.get_project_frame = lambda *args, **kwargs: np.zeros((100, 100, 3), dtype=np.uint8)

    f1 = str(tmp_path / "clip_a.mp4")
    f2 = str(tmp_path / "clip_b.mp4")
    with open(f1, "wb") as f:
        f.write(b"0" * 100)
    with open(f2, "wb") as f:
        f.write(b"0" * 100)

    mp.add_media_item(f1)
    mp.add_media_item(f2)

    main_window.project.tracks[0].clips.clear()
    main_window.preview_engine.get_media_duration = lambda path: 60.0

    # Select both and insert at 0.2s each
    mp.list_widget.item(0).setSelected(True)
    mp.list_widget.item(1).setSelected(True)
    mp.spin_length.setValue(0.20)
    mp.btn_insert.click()

    # Verify both clips added sequentially on Track 1
    clips = main_window.project.tracks[0].clips
    assert len(clips) == 2
    assert clips[0].file_path == f1
    assert clips[0].timeline_position == pytest.approx(0.0)
    assert clips[0].duration == pytest.approx(0.20)
    assert clips[0].source_end == pytest.approx(0.20)
    assert clips[0].speed == pytest.approx(1.0)

    assert clips[1].file_path == f2
    assert clips[1].timeline_position == pytest.approx(0.20)
    assert clips[1].duration == pytest.approx(0.20)
    assert clips[1].source_end == pytest.approx(0.20)
    assert clips[1].speed == pytest.approx(1.0)

    assert main_window.get_max_timeline_duration() == pytest.approx(0.40)


def test_clip_set_play_time_dialog_and_signal_integration(main_window, monkeypatch):
    """Validates right-click 'Set Play Time...' dialog interaction, signal propagation, and model updates."""
    main_window.project.tracks[0].clips.clear()
    clip = Clip(
        file_path="scene.mp4",
        name="Scene 1",
        source_start=1.0,
        source_end=11.0,
        timeline_position=0.0,
    )
    main_window.project.tracks[0].clips.append(clip)
    main_window._rebuild_timeline_widgets()

    clip_w = main_window.timeline_view.canvas.track_strips[0].lane.clip_widgets[0]
    assert clip_w.source_start == 1.0
    assert clip_w.source_end == 11.0
    assert clip_w.duration == 10.0
    initial_w = clip_w.width()

    # Track emitted signals
    received_signals = []
    main_window.timeline_view.clip_time_updated.connect(lambda cid, s, e: received_signals.append((cid, s, e)))

    # Mock SetTimeDialog execution to simulate user typing 4.0s start and 18.0s end (14.0s duration)
    from ui.dialogs import SetTimeDialog
    original_init = SetTimeDialog.__init__

    def mock_init(self, start_time=0.0, end_time=0.0, parent=None):
        original_init(self, start_time=start_time, end_time=end_time, parent=parent)
        self.spin_start.setValue(4.0)
        self.spin_end.setValue(18.0)

    monkeypatch.setattr(SetTimeDialog, "__init__", mock_init)
    monkeypatch.setattr(SetTimeDialog, "exec", lambda self: 1)  # QDialog.DialogCode.Accepted

    # Trigger dialog workflow
    clip_w._open_set_time_dialog()

    # 1. Verify ClipWidget local properties updated
    assert clip_w.source_start == 4.0
    assert clip_w.source_end == 18.0
    assert clip_w.duration == 14.0
    assert clip_w.width() > initial_w
    assert clip_w.lbl_dur.text() == "14.0s"

    # 2. Verify signal emission
    assert len(received_signals) == 1
    assert received_signals[0] == (clip.id, 4.0, 18.0)

    # 3. Verify Project model Clip object updated
    model_clip = main_window.project.tracks[0].clips[0]
    assert model_clip.source_start == 4.0
    assert model_clip.source_end == 18.0
    assert model_clip.duration == 14.0
    assert main_window.get_max_timeline_duration() >= 14.0


def test_fullscreen_and_media_pool_proportions(main_window):
    """Validates that media pool has sufficient width and controls fit comfortably without clipping."""
    mp = main_window.media_pool_view
    assert mp.minimumWidth() >= 260
    assert not mp.btn_apply_length.isHidden()
    assert not mp.btn_insert.isHidden()
    assert not mp.spin_length.isHidden()
    assert not mp.length_frame.isHidden()
    assert main_window.minimumWidth() >= 800
    assert main_window.minimumHeight() >= 500


def test_track_header_volume_and_mute_controls(qapp):
    """Validates TrackHeaderWidget volume slider and mute button interactions and signal emissions."""
    from ui.timeline_view import TrackHeaderWidget

    header = TrackHeaderWidget(
        track_name="Audio 1",
        track_index=2,
        track_id="trk-12345",
        volume=1.0,
        is_muted=False,
    )

    assert header.track_id == "trk-12345"
    assert header.volume == 1.0
    assert header.is_muted is False
    assert header.btn_mute.isChecked() is False
    assert header.vol_slider.value() == 100
    assert header.lbl_vol.text() == "100%"

    vol_signals = []
    mute_signals = []
    header.track_volume_changed.connect(lambda tid, vol: vol_signals.append((tid, vol)))
    header.track_mute_toggled.connect(lambda tid, muted: mute_signals.append((tid, muted)))

    # 1. Move volume slider to 65% (0.65)
    header.vol_slider.setValue(65)
    assert len(vol_signals) == 1
    assert vol_signals[-1][0] == "trk-12345"
    assert vol_signals[-1][1] == pytest.approx(0.65, abs=1e-3)
    assert isinstance(vol_signals[-1][1], float)
    assert header.lbl_vol.text() == "65%"

    # 2. Toggle mute button
    header.btn_mute.click()
    assert len(mute_signals) == 1
    assert mute_signals[-1] == ("trk-12345", True)
    assert isinstance(mute_signals[-1][1], bool)
    assert header.is_muted is True
    assert header.btn_mute.isChecked() is True

    # 3. Toggle mute button back
    header.btn_mute.click()
    assert len(mute_signals) == 2
    assert mute_signals[-1] == ("trk-12345", False)
    assert header.is_muted is False

    # 4. Programmatic setters
    header.set_volume(1.8)
    assert header.vol_slider.value() == 180
    assert header.lbl_vol.text() == "180%"

    header.set_muted(True)
    assert header.btn_mute.isChecked() is True


def test_main_window_track_volume_and_mute_integration(main_window):
    """Validates end-to-end signal flow from track headers to Project model state in MainWindow."""
    strip_v1 = main_window.timeline_view.canvas.track_strips[0]
    track_v1 = main_window.project.tracks[0]

    assert strip_v1.track_id == track_v1.id
    assert track_v1.volume == 1.0
    assert track_v1.is_muted is False

    # 1. Change volume slider on Video 1 header
    strip_v1.header.vol_slider.setValue(40)
    assert track_v1.volume == pytest.approx(0.4, abs=1e-3)

    # 2. Click mute on Video 1 header
    strip_v1.header.btn_mute.click()
    assert track_v1.is_muted is True

    # 3. Click unmute on Video 1 header
    strip_v1.header.btn_mute.click()
    assert track_v1.is_muted is False


def test_export_dialog_phone_format_presets(main_window):
    """Validates presence and correct resolutions for phone format presets in ExportDialog."""
    from ui.export_dialog import ExportDialog
    dialog = ExportDialog(project=main_window.project)
    try:
        # Collect resolution presets in combo_res
        resolutions = [dialog.combo_res.itemData(i) for i in range(dialog.combo_res.count())]
        labels = [dialog.combo_res.itemText(i) for i in range(dialog.combo_res.count())]

        # Verify phone format 1080x1920 and 720x1280
        assert (1080, 1920) in resolutions
        assert (720, 1280) in resolutions
        assert any("Phone" in lbl and "1080 × 1920" in lbl for lbl in labels)
        assert any("Phone" in lbl and "720 × 1280" in lbl for lbl in labels)
    finally:
        dialog.close()


def test_clip_widget_transform_context_and_signals(qapp):
    """Validates ClipWidget rotation and flipping methods and signal emissions."""
    cw = ClipWidget(
        clip_name="Test Clip",
        file_path="video.mp4",
        timeline_position=0.0,
        duration=5.0,
        clip_id="clip-abc",
    )
    assert cw.rotation == 0
    assert cw.flip_horizontal is False
    assert cw.flip_vertical is False

    transforms_received = []
    cw.clip_transform_changed.connect(lambda cid, rot, fh, fv: transforms_received.append((cid, rot, fh, fv)))

    # 1. Rotate CW
    cw._rotate_cw()
    assert cw.rotation == 90
    assert len(transforms_received) == 1
    assert transforms_received[-1] == ("clip-abc", 90, False, False)

    # 2. Rotate CCW -> back to 0
    cw._rotate_ccw()
    assert cw.rotation == 0
    assert transforms_received[-1] == ("clip-abc", 0, False, False)

    # 3. Rotate 180
    cw._rotate_180()
    assert cw.rotation == 180
    assert transforms_received[-1] == ("clip-abc", 180, False, False)

    # 4. Flip horizontal
    cw._toggle_flip_h()
    assert cw.flip_horizontal is True
    assert transforms_received[-1] == ("clip-abc", 180, True, False)

    # 5. Flip vertical
    cw._toggle_flip_v()
    assert cw.flip_vertical is True
    assert transforms_received[-1] == ("clip-abc", 180, True, True)

    # 6. Reset transform
    cw._reset_transform()
    assert cw.rotation == 0
    assert cw.flip_horizontal is False
    assert cw.flip_vertical is False
    assert transforms_received[-1] == ("clip-abc", 0, False, False)


def test_main_window_clip_transform_integration(main_window):
    """Validates end-to-end clip transformation integration from timeline to project model."""
    clip = Clip(
        file_path="sample.mp4",
        name="Sample",
        source_start=0.0,
        source_end=10.0,
        timeline_position=0.0,
    )
    main_window.project.tracks[0].clips.append(clip)
    main_window._rebuild_timeline_widgets()

    assert clip.rotation == 0
    assert clip.flip_horizontal is False
    assert clip.flip_vertical is False

    # Simulate transform change signal from timeline (90 deg CW, flip horizontal)
    main_window.timeline_view.clip_transform_changed.emit(clip.id, 90, True, False)

    assert clip.rotation == 90
    assert clip.flip_horizontal is True
    assert clip.flip_vertical is False

    # Reset transform
    main_window.timeline_view.clip_transform_changed.emit(clip.id, 0, False, False)
    assert clip.rotation == 0
    assert clip.flip_horizontal is False
    assert clip.flip_vertical is False

