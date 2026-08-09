import uuid
from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class Clip:
    """Represents a single piece of media on the timeline."""
    file_path: str
    name: str

    # Times are represented in seconds (e.g., 1.5 is one and a half seconds)
    source_start: float = 0.0      # Where the cut starts in the original file
    source_end: float = 0.0        # Where the cut ends in the original file
    timeline_position: float = 0.0 # Where this clip sits on the main timeline

    # Unique ID for tracking across UI and engine
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    @property
    def duration(self) -> float:
        """Calculates the current length of the clip in seconds."""
        return max(0.0, self.source_end - self.source_start)

    def frame_count(self, fps: float = 30.0) -> int:
        """Calculates the total frame count of the clip for a given FPS."""
        return max(1, int(round(self.duration * fps)))

    def time_to_frame(self, local_time: float, fps: float = 30.0) -> int:
        """Calculates the zero-based frame index at a local timestamp within the clip."""
        clamped_time = max(0.0, min(local_time, self.duration))
        total_frames = self.frame_count(fps)
        frame = int(clamped_time * fps)
        return min(frame, max(0, total_frames - 1))


    def to_dict(self) -> Dict[str, Any]:
        """Serializes Clip to a dictionary."""
        return {
            "file_path": self.file_path,
            "name": self.name,
            "source_start": self.source_start,
            "source_end": self.source_end,
            "timeline_position": self.timeline_position,
            "id": self.id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Clip":
        """Instantiates a Clip from a dictionary."""
        return cls(
            file_path=data["file_path"],
            name=data["name"],
            source_start=float(data.get("source_start", 0.0)),
            source_end=float(data.get("source_end", 0.0)),
            timeline_position=float(data.get("timeline_position", 0.0)),
            id=data.get("id", str(uuid.uuid4())),
        )