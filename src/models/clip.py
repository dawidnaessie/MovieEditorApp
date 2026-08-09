import os
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".gif"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".aac", ".flac", ".m4a", ".ogg"}


def detect_media_type(file_path: str) -> str:
    """Infers the media category ('video', 'image', or 'audio') from a file path extension.

    Args:
        file_path (str): Filesystem path or filename to check.

    Returns:
        str: 'image', 'audio', or 'video'.
    """
    if not file_path:
        return "video"
    _, ext = os.path.splitext(file_path.lower())
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in AUDIO_EXTENSIONS:
        return "audio"
    return "video"


@dataclass
class Clip:
    """Represents a discrete media segment placed on a timeline track.

    The Clip model acts as a source-of-truth metadata container. It defines
    which portion of an underlying media file is active (source_start to source_end
    for video/audio, or image_duration for static images) and where it appears
    on the master project timeline (timeline_position).

    Attributes:
        file_path (str): Absolute or relative filesystem path to the source media file.
        name (str): User-facing display title of the clip on the timeline strip.
        source_start (float): The in-point timestamp (in seconds) within the original media file.
        source_end (float): The out-point timestamp (in seconds) within the original media file.
        timeline_position (float): The global timeline timestamp (in seconds) where this clip begins playback.
        media_type (str): Category of media ('video', 'image', or 'audio'). Defaults to auto-detected type.
        image_duration (float): Display duration in seconds for static image clips (defaults to 5.0s, freely extendable).
        id (str): Unique UUID identifier for tracking this clip across the UI and preview engine.
    """

    file_path: str
    name: str
    source_start: float = 0.0
    source_end: float = 0.0
    timeline_position: float = 0.0
    media_type: str = "video"
    image_duration: float = 5.0
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __post_init__(self) -> None:
        """Auto-detects media_type from file path if set to default 'video' and file is an image/audio."""
        if self.file_path:
            detected = detect_media_type(self.file_path)
            if self.media_type == "video" and detected != "video":
                self.media_type = detected

    @property
    def is_image(self) -> bool:
        """Returns True if the clip represents a static graphic/image."""
        return self.media_type == "image"

    @property
    def duration(self) -> float:
        """Calculates the duration of the active clip segment in seconds.

        For images, returns `image_duration`.
        For video and audio, returns `source_end - source_start`.

        Returns:
            float: Non-negative duration in seconds.
        """
        if self.is_image:
            return max(0.1, float(self.image_duration))
        return max(0.0, float(self.source_end - self.source_start))

    def frame_count(self, fps: float = 30.0) -> int:
        """Calculates the total number of frames contained within this clip segment.

        Args:
            fps (float): The target frame rate (frames per second). Defaults to 30.0.

        Returns:
            int: Total frame count (minimum 1).
        """
        safe_fps = max(1.0, float(fps))
        return max(1, int(round(self.duration * safe_fps)))

    def time_to_frame(self, local_time: float, fps: float = 30.0) -> int:
        """Translates a local clip timestamp (0.0 to duration) to a zero-based frame index.

        Args:
            local_time (float): Time offset in seconds relative to the start of this clip.
            fps (float): The target frame rate (frames per second). Defaults to 30.0.

        Returns:
            int: Zero-based frame index, strictly clamped between 0 and (total_frames - 1).
        """
        safe_fps = max(1.0, float(fps))
        clamped_time = max(0.0, min(float(local_time), self.duration))
        total_frames = self.frame_count(safe_fps)
        frame = int(clamped_time * safe_fps)
        return min(frame, max(0, total_frames - 1))

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the Clip model to a JSON-compatible dictionary.

        Returns:
            Dict[str, Any]: Key-value mapping representing the clip state.
        """
        return {
            "file_path": self.file_path,
            "name": self.name,
            "source_start": float(self.source_start),
            "source_end": float(self.source_end),
            "timeline_position": float(self.timeline_position),
            "media_type": self.media_type,
            "image_duration": float(self.image_duration),
            "id": self.id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Clip":
        """Constructs a Clip model from a dictionary.

        Args:
            data (Dict[str, Any]): Dictionary containing serialized Clip fields.

        Returns:
            Clip: Reconstituted Clip object.
        """
        file_path = str(data.get("file_path", ""))
        default_type = detect_media_type(file_path)
        media_type = str(data.get("media_type", default_type))

        return cls(
            file_path=file_path,
            name=str(data.get("name", "Untitled Clip")),
            source_start=float(data.get("source_start", 0.0)),
            source_end=float(data.get("source_end", 0.0)),
            timeline_position=float(data.get("timeline_position", 0.0)),
            media_type=media_type,
            image_duration=float(data.get("image_duration", 5.0)),
            id=str(data.get("id", uuid.uuid4())),
        )