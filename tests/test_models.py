import os
import sys

# Ensure Python can find our src directory regardless of working directory
src_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from models import Project, Clip


def run_test():
    # 1. Initialize a new 4K project
    print("Creating project...")
    my_project = Project(name="My First AI Movie", resolution=(3840, 2160), fps=60.0)

    # 2. Add a video track and an audio track
    video_track = my_project.add_track(name="Video Layer 1")
    my_project.add_track(name="Audio Layer 1")

    # 3. Create a 5-second clip (cutting a 5-second chunk out of a raw video)
    drone_clip = Clip(
        file_path="C:/videos/raw_drone_footage.mp4",
        name="Opening Sweep",
        source_start=15.0,
        source_end=20.0,
        timeline_position=0.0,
    )

    # 4. Add the clip to the video track
    video_track.clips.append(drone_clip)

    # 5. Output the calculated duration and the final JSON
    print(f"Clip '{drone_clip.name}' duration is {drone_clip.duration} seconds.\n")
    print("--- PROJECT JSON EXPORT ---")
    print(my_project.to_json())


if __name__ == "__main__":
    run_test()