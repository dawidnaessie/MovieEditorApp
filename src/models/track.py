import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from .clip import Clip


@dataclass
class Track:
    """Represents a single layer/lane on the master editing timeline.

    Tracks group and sequence multiple Clip objects either as visual layers
    (track_type="video") or auditory layers (track_type="audio"). Higher video tracks
    take top-down visual precedence during frame rendering.

    Attributes:
        name (str): Human-readable name of the track (e.g., 'Video 1', 'Audio 1').
        track_type (str): Type of track media content ('video' or 'audio'). Defaults to 'video'.
        clips (List[Clip]): Ordered list of Clip objects placed on this track.
        id (str): Unique UUID identifier for the track.
    """

    name: str
    track_type: str = "video"
    clips: List[Clip] = field(default_factory=list)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def find_clip_by_id(self, clip_id: str) -> Optional[Clip]:
        """Finds and returns a Clip on this track matching the given UUID."""
        for c in self.clips:
            if c.id == clip_id:
                return c
        return None

    def split_clip(self, clip_id: str, global_time: float) -> Optional[Tuple[Clip, Clip]]:
        """Splits an active clip into two independent segments at the given timeline timestamp.

        Args:
            clip_id (str): UUID of the clip to split.
            global_time (float): Timeline timestamp in seconds where the split cut occurs.

        Returns:
            Optional[Tuple[Clip, Clip]]: Tuple of (left_clip, right_clip) or None if split is invalid.
        """
        target_index = -1
        target_clip: Optional[Clip] = None
        for idx, c in enumerate(self.clips):
            if c.id == clip_id:
                target_index = idx
                target_clip = c
                break

        if target_clip is None or target_index == -1:
            return None

        clip_start = target_clip.timeline_position
        clip_end = clip_start + target_clip.duration

        # Ensure cut is strictly within clip boundaries (with 0.05s safety margin)
        if not (clip_start + 0.05 <= global_time <= clip_end - 0.05):
            return None

        offset = global_time - clip_start

        if target_clip.is_image:
            orig_duration = target_clip.duration
            target_clip.image_duration = offset
            right_clip = Clip(
                file_path=target_clip.file_path,
                name=f"{target_clip.name} (Split)",
                timeline_position=global_time,
                media_type="image",
                image_duration=max(0.1, orig_duration - offset),
            )
        else:
            orig_source_end = target_clip.source_end
            split_source_time = target_clip.get_source_time(offset)
            orig_duration = target_clip.duration
            target_clip.source_end = split_source_time
            target_clip.playback_duration = offset

            right_clip = Clip(
                file_path=target_clip.file_path,
                name=f"{target_clip.name} (Split)",
                source_start=split_source_time,
                source_end=orig_source_end,
                timeline_position=global_time,
                media_type=target_clip.media_type,
                playback_duration=max(0.1, orig_duration - offset),
            )

        self.clips.insert(target_index + 1, right_clip)
        return target_clip, right_clip

    def trim_clip_left(self, clip_id: str, new_timeline_pos: float) -> bool:
        """Trims the in-point (start) of a clip to a new timeline position.

        Args:
            clip_id (str): UUID of the clip to trim.
            new_timeline_pos (float): New global start timestamp in seconds.

        Returns:
            bool: True if trimming succeeded.
        """
        clip = self.find_clip_by_id(clip_id)
        if clip is None:
            return False

        old_start = clip.timeline_position
        old_end = old_start + clip.duration
        if new_timeline_pos >= old_end - 0.1 or new_timeline_pos < 0:
            return False

        delta = new_timeline_pos - old_start
        clip.timeline_position = new_timeline_pos

        if clip.is_image:
            clip.image_duration = max(0.1, clip.image_duration - delta)
        else:
            clip.source_start = max(0.0, clip.source_start + delta)
            if clip.playback_duration is not None:
                clip.playback_duration = max(0.1, clip.playback_duration - delta)

        return True

    def trim_clip_right(self, clip_id: str, new_duration: float) -> bool:
        """Trims or extends the out-point (duration) of a clip.

        When extended past the original source range, adjusts playback duration
        to slow down footage and match the new timeline length.

        Args:
            clip_id (str): UUID of the clip to trim.
            new_duration (float): New duration in seconds (minimum 0.1s).

        Returns:
            bool: True if trimming succeeded.
        """
        clip = self.find_clip_by_id(clip_id)
        if clip is None or new_duration < 0.1:
            return False

        if clip.is_image:
            clip.image_duration = max(0.1, new_duration)
        else:
            clip.playback_duration = max(0.1, new_duration)

        return True

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the Track model to a JSON-compatible dictionary.

        Returns:
            Dict[str, Any]: Key-value mapping representing the track state and its clips.
        """
        return {
            "name": self.name,
            "track_type": self.track_type,
            "clips": [c.to_dict() for c in self.clips],
            "id": self.id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Track":
        """Constructs a Track model from a dictionary.

        Args:
            data (Dict[str, Any]): Dictionary containing serialized Track fields.

        Returns:
            Track: Reconstituted Track instance with deserialized Clip children.
        """
        name = str(data.get("name", "Track"))
        default_type = "audio" if "audio" in name.lower() else "video"
        track_type = str(data.get("track_type", default_type))
        track = cls(
            name=name,
            track_type=track_type,
            id=str(data.get("id", uuid.uuid4())),
        )
        track.clips = [Clip.from_dict(c) for c in data.get("clips", [])]
        return track
