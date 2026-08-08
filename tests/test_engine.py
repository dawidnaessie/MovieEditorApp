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

    # 5. Display the extracted project frame
    print("[5/5] Popping open preview window...")
    displayed = False

    try:
        cv2 = importlib.import_module("cv2")
        bgr_frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        window_name = f"Project Frame at {global_time}s (Press any key to close)"
        cv2.imshow(window_name, bgr_frame)
        print("      Opened via OpenCV (cv2). Press any key in the window to exit.")
        cv2.waitKey(0)
        cv2.destroyAllWindows()
        displayed = True
    except (ImportError, ModuleNotFoundError):
        pass

    if not displayed:
        image = Image.fromarray(frame)
        image.show(title=f"Project Frame at {global_time}s")
        print("      Opened via Pillow (PIL). Image viewer launched.")

    # Clean up engine resources
    engine.close()
    print("Test finished successfully.")


if __name__ == "__main__":
    test_frame_extraction()
