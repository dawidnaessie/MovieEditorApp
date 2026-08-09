import importlib
import os
import sys
from PIL import Image

# Ensure Python can resolve the src directory regardless of working directory
src_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from engine.preview_engine import PreviewEngine
from models.clip import Clip
from models.project import Project


def find_sample_video() -> str:
    """Finds an existing sample video on the machine or accepts a command-line argument."""
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        return sys.argv[1]

    # Candidate sample files found on your system
    candidates = [
        os.path.abspath("Getting hit by a lance..mp4"),
        r"C:\Users\rastisx\Desktop\Crystal Castles - Celestica.mp4",
        r"C:\Users\rastisx\Desktop\0609 (1).mp4",
        r"C:\Users\rastisx\Videos\2026-01-27 08-41-55.mp4",
    ]

    for path in candidates:
        if os.path.exists(path):
            return path

    raise FileNotFoundError(
        "No sample MP4 file found. Please provide a path: python tests/test_engine.py <path_to_video.mp4>"
    )


def test_frame_extraction():
    video_path = find_sample_video()
    print(f"[1/5] Found test video: {video_path}")

    # 1. Create a Clip object representing a cut segment placed at timeline position 5.0s
    clip = Clip(
        file_path=video_path,
        name="Test Clip Segment",
        source_start=0.0,
        source_end=10.0,
        timeline_position=5.0,  # Starts at 5.0s on the master timeline
    )
    print(f"[2/5] Initialized Clip: '{clip.name}' (cut 0s-10s, timeline pos: {clip.timeline_position}s)")

    # 2. Set up a Project and add the clip to a track
    project = Project(name="Test Project", resolution=(1920, 1080), fps=30.0)
    video_track = project.add_track(name="Video 1")
    video_track.clips.append(clip)

    engine = PreviewEngine()

    # 3. Test get_project_frame at 7.0s (which is 2.0s into the clip)
    global_time = 7.0
    print(f"[3/5] Extracting project frame at global_time={global_time}s (clip offset: 2.0s)...")
    frame = engine.get_project_frame(project, global_time=global_time)
    print(f"      Project frame extracted! Shape: {frame.shape}, Dtype: {frame.dtype}")

    # 4. Test get_project_frame at 1.0s (outside clip timeline range -> should return black frame)
    gap_time = 1.0
    black_frame = engine.get_project_frame(project, global_time=gap_time)
    print(f"[4/5] Testing gap at global_time={gap_time}s -> black frame shape: {black_frame.shape}, mean: {black_frame.mean():.2f}")
    assert black_frame.mean() == 0.0, "Expected empty black frame when no clip exists at global_time"

    # 5. Test Playback Status metadata
    print("[5/6] Testing get_playback_status...")
    status = engine.get_playback_status(project, global_time=7.0)
    print(f"      Status at 7.0s: {status}")
    assert status["has_active_clip"] is True
    assert status["clip_name"] == "Test Clip Segment"
    assert status["clip_frame"] == 61  # 2.0s * 30fps + 1
    assert status["current_frame"] == 211  # 7.0s * 30fps + 1
    assert "00:00:07:" in status["timecode"]

    gap_status = engine.get_playback_status(project, global_time=1.0)
    assert gap_status["has_active_clip"] is False

    # 6. Test Filmstrip Thumbnail Extraction
    print("[6/8] Testing extract_clip_thumbnails...")
    thumbs = engine.extract_clip_thumbnails(video_path, source_start=0.0, duration=10.0, count=5, thumb_height=36)
    print(f"      Extracted {len(thumbs)} thumbnails. Shapes: {[t.shape for t in thumbs]}")
    assert len(thumbs) == 5
    assert thumbs[0].shape[0] == 36

    # 7. Test Top-Down Video Layering (Video 2 > Video 1)
    print("[7/8] Testing Top-Down Video Layering (Video 2 > Video 1)...")
    video_track2 = project.add_track(name="Video 2", track_type="video")
    clip_v2 = Clip(
        file_path=video_path,
        name="Overlay Clip on V2",
        source_start=0.0,
        source_end=2.0,
        timeline_position=6.0,  # Overlaps with Video 1 from 6.0s to 8.0s
    )
    video_track2.clips.append(clip_v2)

    # At 6.5s: Video 2 is active -> status must show Video 2 clip!
    status_at_6_5 = engine.get_playback_status(project, global_time=6.5)
    assert status_at_6_5["clip_name"] == "Overlay Clip on V2"
    assert status_at_6_5["track_name"] == "Video 2"
    print("      Verified: Video 2 takes visual precedence over Video 1 during overlap (6.5s)")

    # At 9.0s: Video 2 is finished, but Video 1 is still active -> falls through to Video 1!
    status_at_9_0 = engine.get_playback_status(project, global_time=9.0)
    assert status_at_9_0["clip_name"] == "Test Clip Segment"
    assert status_at_9_0["track_name"] == "Video 1"
    print("      Verified: Video 1 shows through during gaps in Video 2 (9.0s)")

    # 8. Test Multi-Track Audio PCM Extraction & Mixing
    print("[8/8] Testing Multi-Track Audio Mixing...")
    audio_track = project.add_track(name="Audio 1", track_type="audio")
    audio_clip = Clip(
        file_path=video_path,
        name="Background Music",
        source_start=0.0,
        source_end=5.0,
        timeline_position=5.0,
    )
    audio_track.clips.append(audio_clip)

    pcm_bytes = engine.get_project_audio_pcm(project, start_time=5.0, duration=3.0, sample_rate=44100)
    expected_bytes = 3 * 44100 * 2 * 2  # 3s * 44100Hz * 2 channels * 2 bytes/sample
    print(f"      Mixed PCM bytes length: {len(pcm_bytes)} (expected: {expected_bytes})")
    assert len(pcm_bytes) == expected_bytes
    # 9. Test Exact Clip End Boundary Inclusiveness
    print("[9/9] Testing Exact Clip End Boundary (15.0s)...")
    end_status = engine.get_playback_status(project, global_time=15.0)
    assert end_status["has_active_clip"] is True
    assert end_status["clip_name"] == "Test Clip Segment"
    end_frame = engine.get_project_frame(project, global_time=15.0)
    assert end_frame.shape == (1080, 1920, 3)
    assert end_frame.mean() > 0.0
    print("      Verified: Clip remains active and renders last frame at exact end boundary (15.0s) without black screen glitch.")

    # Clean up engine resources
    engine.close()
    print("\n[SUCCESS] Engine test suite passed completely!")



if __name__ == "__main__":
    test_frame_extraction()


