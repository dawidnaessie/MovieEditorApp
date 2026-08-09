import uuid
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from .clip import Clip


@dataclass
class Track:
    """Represents a single layer/track on the timeline (e.g., Video 1, Video 2, Audio 1)."""
    name: str
    track_type: str = "video"  # "video" or "audio"
    clips: List[Clip] = field(default_factory=list)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "track_type": self.track_type,
            "clips": [c.to_dict() for c in self.clips],
            "id": self.id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Track":
        name = data.get("name", "Track")
        default_type = "audio" if "audio" in name.lower() else "video"
        track_type = data.get("track_type", default_type)
        track = cls(
            name=name,
            track_type=track_type,
            id=data.get("id", str(uuid.uuid4())),
        )
        track.clips = [Clip.from_dict(c) for c in data.get("clips", [])]
        return track


@dataclass
class Project:
    """The master root object for the entire video project."""
    name: str
    resolution: Tuple[int, int] = (1920, 1080) # Default to Full HD
    fps: float = 30.0                          # Default framerate
    tracks: List[Track] = field(default_factory=list)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def add_track(self, name: str, track_type: Optional[str] = None) -> Track:
        if track_type is None:
            track_type = "audio" if "audio" in name.lower() else "video"
        new_track = Track(name=name, track_type=track_type)
        self.tracks.append(new_track)
        return new_track

    def find_clip_at(self, global_time: float) -> Optional[Tuple[Track, Clip, float]]:
        """
        Finds the top-most active VIDEO clip at global_time (Top-Down visual layering: Video 2 > Video 1).
        Iterates video tracks in reverse order so higher tracks take visual precedence.
        Uses half-open intervals [start, end) so boundary transitions between clips are clean and jitter-free.
        At the exact end of the project timeline, cleanly returns the final frame.
        """
        video_tracks = [t for t in self.tracks if t.track_type == "video"]
        # 1. Primary pass: half-open interval [start, end)
        for track in reversed(video_tracks):
            for clip in track.clips:
                clip_start = clip.timeline_position
                clip_end = clip.timeline_position + clip.duration
                if clip_start <= global_time < clip_end:
                    local_time = min(clip.duration, max(0.0, global_time - clip_start))
                    return track, clip, local_time

        # 2. Secondary fallback pass for the exact end boundary of the timeline
        total_duration = self.get_total_duration()
        if total_duration > 0 and global_time >= total_duration - 1e-4:
            for track in reversed(video_tracks):
                for clip in track.clips:
                    clip_start = clip.timeline_position
                    clip_end = clip.timeline_position + clip.duration
                    if abs(clip_end - total_duration) < 1e-3 and clip_start <= global_time <= clip_end + 1e-3:
                        local_time = min(clip.duration, max(0.0, global_time - clip_start))
                        return track, clip, local_time

        return None


    def find_all_audio_clips_at(
        self, start_time: float, duration: float
    ) -> List[Tuple[Track, Clip, float, float]]:
        """
        Finds ALL active clips across both video and audio tracks that intersect the time window [start_time, start_time + duration].
        Returns list of (Track, Clip, overlap_start_global, overlap_end_global) for multi-track audio mixing.
        """
        end_time = start_time + duration
        active_clips: List[Tuple[Track, Clip, float, float]] = []

        for track in self.tracks:
            for clip in track.clips:
                clip_start = clip.timeline_position
                clip_end = clip.timeline_position + clip.duration
                # Check for interval overlap
                overlap_start = max(start_time, clip_start)
                overlap_end = min(end_time, clip_end)
                if overlap_start < overlap_end:
                    active_clips.append((track, clip, overlap_start, overlap_end))

        return active_clips

    def get_total_duration(self) -> float:
        """Returns the maximum end time across all tracks and clips."""
        max_duration = 0.0
        for track in self.tracks:
            for clip in track.clips:
                end_time = clip.timeline_position + clip.duration
                if end_time > max_duration:
                    max_duration = end_time
        return max_duration

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the project to a dictionary."""
        return {
            "name": self.name,
            "resolution": list(self.resolution),
            "fps": self.fps,
            "tracks": [t.to_dict() for t in self.tracks],
            "id": self.id,
        }

    def to_json(self) -> str:
        """Serializes the entire project state into a formatted JSON string for saving."""
        return json.dumps(self.to_dict(), indent=4)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Project":
        """Instantiates a Project from a dictionary."""
        raw_res = data.get("resolution", (1920, 1080))
        resolution = (int(raw_res[0]), int(raw_res[1]))
        project = cls(
            name=data.get("name", "Untitled Project"),
            resolution=resolution,
            fps=float(data.get("fps", 30.0)),
            id=data.get("id", str(uuid.uuid4())),
        )
        project.tracks = [Track.from_dict(t) for t in data.get("tracks", [])]
        return project

    @classmethod
    def from_json(cls, json_str: str) -> "Project":
        """Loads a Project instance from a JSON string."""
        return cls.from_dict(json.loads(json_str))
