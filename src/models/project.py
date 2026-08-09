import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from .clip import Clip
from .track import Track


@dataclass
class Project:
    """The master root object and single source-of-truth for an entire video project.

    Project coordinates the sequence of video and audio tracks, project-level settings
    (canvas resolution, framerate), spatial layering, and serialization to/from JSON.

    Attributes:
        name (str): Project title.
        resolution (Tuple[int, int]): Master preview and export resolution in pixels as (width, height).
        fps (float): Master playback and timeline frame rate. Defaults to 30.0.
        tracks (List[Track]): Ordered list of Track layers contained within this project.
        id (str): Unique UUID identifier for the project.
    """

    name: str
    resolution: Tuple[int, int] = (1920, 1080)
    fps: float = 30.0
    tracks: List[Track] = field(default_factory=list)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def add_track(self, name: str, track_type: Optional[str] = None) -> Track:
        """Instantiates and appends a new Track to the project.

        Args:
            name (str): Display name for the track.
            track_type (Optional[str]): 'video' or 'audio'. If omitted, automatically inferred from name.

        Returns:
            Track: The newly created Track instance.
        """
        if track_type is None:
            track_type = "audio" if "audio" in name.lower() else "video"
        new_track = Track(name=name, track_type=track_type)
        self.tracks.append(new_track)
        return new_track

    def find_clip_at(self, global_time: float) -> Optional[Tuple[Track, Clip, float]]:
        """Finds the top-most active VIDEO clip covering the given timeline timestamp.

        Iterates video tracks in reverse order (top-down visual layering: Video 2 > Video 1).
        Uses half-open intervals [clip_start, clip_end) to ensure jitter-free boundary transitions.
        Provides a seamless fallback for the exact ending boundary of the project timeline.

        Args:
            global_time (float): Timeline timestamp in seconds.

        Returns:
            Optional[Tuple[Track, Clip, float]]: Tuple of (Track, Clip, local_clip_time_in_seconds)
                or None if no video clip exists at global_time (e.g. over a gap).
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
        """Finds all active clips across video and audio tracks intersecting a time window.

        Args:
            start_time (float): Start timestamp in seconds on the master timeline.
            duration (float): Time window duration in seconds.

        Returns:
            List[Tuple[Track, Clip, float, float]]: List of tuples containing
                (Track, Clip, overlap_start_global, overlap_end_global) for multi-track audio mixing.
        """
        end_time = start_time + duration
        active_clips: List[Tuple[Track, Clip, float, float]] = []

        for track in self.tracks:
            for clip in track.clips:
                clip_start = clip.timeline_position
                clip_end = clip.timeline_position + clip.duration
                overlap_start = max(start_time, clip_start)
                overlap_end = min(end_time, clip_end)
                if overlap_start < overlap_end:
                    active_clips.append((track, clip, overlap_start, overlap_end))

        return active_clips

    def find_track_for_clip(self, clip_id: str) -> Optional[Track]:
        """Finds the Track that contains the Clip matching the given UUID."""
        for track in self.tracks:
            for clip in track.clips:
                if clip.id == clip_id:
                    return track
        return None

    def find_clip_by_id(self, clip_id: str) -> Optional[Tuple[Track, Clip]]:
        """Finds a Clip and its owning Track by clip UUID."""
        for track in self.tracks:
            for clip in track.clips:
                if clip.id == clip_id:
                    return track, clip
        return None

    def split_clip(self, clip_id: str, global_time: float) -> Optional[Tuple[Clip, Clip]]:
        """Finds the owning track and splits the clip at global_time into two segments."""
        track = self.find_track_for_clip(clip_id)
        if track:
            return track.split_clip(clip_id, global_time)
        return None

    def get_total_duration(self) -> float:
        """Calculates the maximum end timestamp across all tracks and clips in the project.

        Returns:
            float: Total project duration in seconds (0.0 if empty).
        """
        max_duration = 0.0
        for track in self.tracks:
            for clip in track.clips:
                end_time = clip.timeline_position + clip.duration
                if end_time > max_duration:
                    max_duration = end_time
        return max_duration

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the entire Project model to a JSON-compatible dictionary.

        Returns:
            Dict[str, Any]: Key-value mapping representing complete project state.
        """
        return {
            "name": self.name,
            "resolution": list(self.resolution),
            "fps": float(self.fps),
            "tracks": [t.to_dict() for t in self.tracks],
            "id": self.id,
        }

    def to_json(self) -> str:
        """Serializes the project state to a formatted JSON string for persistence.

        Returns:
            str: Pretty-printed JSON representation.
        """
        return json.dumps(self.to_dict(), indent=4)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Project":
        """Constructs a Project model from a dictionary.

        Args:
            data (Dict[str, Any]): Serialized project data dictionary.

        Returns:
            Project: Reconstituted Project instance with deserialized Tracks and Clips.
        """
        raw_res = data.get("resolution", (1920, 1080))
        resolution = (int(raw_res[0]), int(raw_res[1]))
        project = cls(
            name=str(data.get("name", "Untitled Project")),
            resolution=resolution,
            fps=float(data.get("fps", 30.0)),
            id=str(data.get("id", uuid.uuid4())),
        )
        project.tracks = [Track.from_dict(t) for t in data.get("tracks", [])]
        return project

    @classmethod
    def from_json(cls, json_str: str) -> "Project":
        """Loads a Project instance from a JSON string.

        Args:
            json_str (str): Formatted JSON string representing a project file.

        Returns:
            Project: Deserialized Project instance.
        """
        return cls.from_dict(json.loads(json_str))
