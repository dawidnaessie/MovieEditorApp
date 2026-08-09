import os
import sys

src_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src'))
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from PyQt6.QtWidgets import QApplication
from ui.main_window import MainWindow


def run_ui_test():
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    print('[1/5] Initializing MainWindow...')
    window = MainWindow()
    assert window is not None
    print('      MainWindow instantiated successfully.')

    print('[2/5] Checking PlayerView status badges...')
    assert hasattr(window.player_view, 'lbl_video_name')
    assert hasattr(window.player_view, 'lbl_frame_counter')
    assert hasattr(window.player_view, 'lbl_timecode')
    print(f'      Initial Frame status: {window.player_view.lbl_frame_counter.text()}')
    print(f'      Initial Timecode: {window.player_view.lbl_timecode.text()}')

    print('[3/5] Testing Seeking...')
    window._on_timeline_seek(5.0)
    print(f'      Seeked to 5.0s -> Frame status: {window.player_view.lbl_frame_counter.text()}')
    print(f'      Seeked to 5.0s -> Timecode: {window.player_view.lbl_timecode.text()}')
    assert window.current_playback_time == 5.0
    assert '00:00:05:' in window.player_view.lbl_timecode.text()

    print('[4/5] Testing Step Forward and Step Backward...')
    window.step_frame(1)
    print(f'      Stepped +1 frame -> Playback time: {window.current_playback_time:.3f}s')
    window.step_frame(-1)
    print(f'      Stepped -1 frame -> Playback time: {window.current_playback_time:.3f}s')

    # 5. Test Audio Subsystem & Volume / Mute Controls
    print("[5/6] Testing Audio Controls & Playback...")
    assert hasattr(window, "audio_sink")
    assert window.audio_sink is not None

    # Test Volume Change
    window.player_view.slider_volume.setValue(50)
    assert window.volume == 0.5
    print("      Volume slider update verified (50%).")

    # Test Mute Toggle
    window.player_view._toggle_mute()
    assert window.is_muted is True
    print("      Mute toggle verified.")

    # Unmute
    window.player_view._toggle_mute()
    assert window.is_muted is False

    # Test Play & Audio Start
    window.play()
    assert window._is_playing is True
    print("      Playback and audio stream started.")
    window.pause()
    assert window._is_playing is False
    print("      Playback and audio stream paused.")

    # 6. Test Clip Drag & Drop and Top-Down Layering in UI
    print("[6/6] Testing Clip Drag & Drop and Top-Down Video Layering in UI...")
    sample_path = r"C:\Users\rastisx\Desktop\Crystal Castles - Celestica.mp4"
    if os.path.exists(sample_path):
        # Drop clip onto Video 2 (track 1) at 10.0s
        window._on_clip_dropped(sample_path, track_index=1, timeline_pos=10.0)
        assert len(window.project.tracks[1].clips) >= 1
        print("      Clip dropped onto Track 1 (Video 2) at 10.0s.")

        # Seek to 12.0s (where Video 2 overlaps with Video 1)
        window._on_timeline_seek(12.0)
        status = window.preview_engine.get_playback_status(window.project, 12.0)
        assert status["track_name"] == "Video 2"
        print("      Verified in UI: Video 2 is active on top of Video 1 at 12.0s.")

    # 7. Test Clip Selection and Deletion
    print("[7/7] Testing Clip Selection and Deletion...")
    initial_clips_v1 = len(window.project.tracks[0].clips)
    if initial_clips_v1 > 0:
        first_clip_widget = window.timeline_view.canvas.track_strips[0].lane.clip_widgets[0]
        # Simulate selecting clip
        first_clip_widget.set_selected(True)
        window._on_clip_selected(first_clip_widget)
        assert window.selected_clip_widget is first_clip_widget
        print("      Clip selected successfully.")

        # Simulate Delete Key trigger
        window.delete_selected_clip()
        assert len(window.project.tracks[0].clips) == initial_clips_v1 - 1
        assert window.selected_clip_widget is None
    # 8. Test Clip Boundary Transition & Indicator Smoothness
    print("[8/10] Testing Clip Boundary Transition & Indicator Smoothness...")
    if os.path.exists(sample_path):
        # Create a fresh project structure: Video 1 (0 to 60s), Video 2 (10 to 25s)
        window.project.tracks[0].clips.clear()
        window.project.tracks[1].clips.clear()
        clip1 = window.project.tracks[0].clips
        from models.clip import Clip
        clip1.append(Clip(file_path=sample_path, name="V1_Long", source_start=0.0, source_end=60.0, timeline_position=0.0))
        window.project.tracks[1].clips.append(Clip(file_path=sample_path, name="V2_Short", source_start=0.0, source_end=15.0, timeline_position=10.0))

        # Seek to 24.9s (Video 2 active)
        window._on_timeline_seek(24.9)
        st_before = window.preview_engine.get_playback_status(window.project, 24.9)
        assert st_before["track_name"] == "Video 2"
        f_before = st_before["current_frame"]

        # Seek to 25.1s (Video 2 ended, seamlessly falls back to Video 1 underneath)
        window._on_timeline_seek(25.1)
        st_after = window.preview_engine.get_playback_status(window.project, 25.1)
        assert st_after["track_name"] == "Video 1"
        f_after = st_after["current_frame"]

        # Master timeline frames must strictly increase monotonically (no jumping back/tripping)
        assert f_after > f_before, f"Expected frame {f_after} > {f_before}"
        print("      Verified: Seamless transition from Video 2 back to Video 1 at boundary with monotonic frame indicator.")

    # 9. Test Async Thumbnail Delivery to Deleted Widget (Race Condition Safety)
    print("[9/10] Testing Async Thumbnail Delivery to Deleted/Destroyed ClipWidget...")
    dummy_clip_w = window.timeline_view.add_clip(
        track_index=0,
        file_path=sample_path if os.path.exists(sample_path) else "dummy.mp4",
        timeline_position=0.0,
        duration=5.0,
    )
    if dummy_clip_w:
        # Delete widget immediately
        window.timeline_view.remove_clip_widget(dummy_clip_w)
        app.processEvents()
        # Fire thumbnail delivery on deleted widget
        import numpy as np
        fake_thumbs = [np.zeros((36, 64, 3), dtype=np.uint8)]
        # This must not throw RuntimeError even though dummy_clip_w is deleted in C++
        window._on_thumbnails_ready(dummy_clip_w, fake_thumbs, object())
        print("      Verified: Delivering thumbnails to deleted ClipWidget handled safely without crash.")

    window.close()
    print("\n[SUCCESS] UI Integration test passed cleanly!")


if __name__ == "__main__":
    run_ui_test()



