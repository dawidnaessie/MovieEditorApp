import numpy as np
from moviepy import VideoFileClip

from models.clip import Clip
from models.project import Project


class PreviewEngine:
    """Handles extracting video frames and querying media metadata without freezing the UI."""

    def __init__(self):
        # Cache loaded video files so scrubbing the timeline is fast
        self._loaded_media: dict[str, VideoFileClip] = {}

    def get_media_duration(self, file_path: str) -> float:
        """Returns the media duration in seconds for a video file, loading into cache if needed."""
        if file_path not in self._loaded_media:
            try:
                self._loaded_media[file_path] = VideoFileClip(file_path)
            except Exception as e:
                print(f"Engine Error: Could not load duration for {file_path}. {e}")
                return 10.0
        media = self._loaded_media[file_path]
        return float(getattr(media, "duration", 10.0))

    def get_frame(self, clip: Clip, time_in_seconds: float) -> np.ndarray:
        """
        Reads a video file and returns a single frame as a raw RGB numpy array (H, W, 3).
        Returns a solid black frame if file is missing, broken, or empty.
        """
        if clip.file_path not in self._loaded_media:
            try:
                self._loaded_media[clip.file_path] = VideoFileClip(clip.file_path)
            except Exception as e:
                print(f"Engine Error: Could not load {clip.file_path}. {e}")
                return np.zeros((1080, 1920, 3), dtype=np.uint8)

        media = self._loaded_media[clip.file_path]

        # Account for clip cut offset
        actual_media_time = clip.source_start + time_in_seconds

        # Clamp time within valid media range
        media_duration = getattr(media, "duration", 0.0)
        safe_time = max(0.0, min(actual_media_time, media_duration))

        # Extract and return raw RGB numpy array
        try:
            return media.get_frame(safe_time)
        except Exception as e:
            print(f"Engine Error: Failed to extract frame at {safe_time}s from {clip.file_path}. {e}")
            return np.zeros((1080, 1920, 3), dtype=np.uint8)

    def get_project_frame(self, project: Project, global_time: float) -> np.ndarray:
        """
        Extracts the frame at global_time across all tracks in a Project.
        1. Loops through project.tracks to find which Clip exists at global_time.
        2. Calculates the local time for that clip (global_time - clip.timeline_position).
        3. Extracts and returns the frame for that specific clip using existing logic.
        4. If no clip exists at global_time, returns a clean black frame matching project resolution.
        """
        # Loop through tracks to find the active clip at global_time
        for track in project.tracks:
            for clip in track.clips:
                clip_start = clip.timeline_position
                clip_end = clip.timeline_position + clip.duration
                if clip_start <= global_time < clip_end:
                    local_time = global_time - clip_start
                    return self.get_frame(clip, local_time)

        # Return solid black frame if playhead is over an empty gap or outside all clips
        width, height = project.resolution if hasattr(project, "resolution") else (1920, 1080)
        return np.zeros((height, width, 3), dtype=np.uint8)

    def close(self):
        """Release all open video file handles."""
        for path, media in list(self._loaded_media.items()):
            try:
                media.close()
            except Exception:
                pass
        self._loaded_media.clear()
