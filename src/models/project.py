import uuid
import json
from dataclasses import dataclass, field, asdict
from typing import List
from .clip import Clip

@dataclass
class Track:
    """Represents a single layer/track on the timeline (e.g., Video 1, Audio 1)."""
    name: str
    clips: List[Clip] = field(default_factory=list)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

@dataclass
class Project:
    """The master root object for the entire video project."""
    name: str
    resolution: tuple[int, int] = (1920, 1080) # Default to Full HD
    fps: float = 30.0                          # Default framerate
    tracks: List[Track] = field(default_factory=list)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def add_track(self, name: str) -> Track:
        new_track = Track(name=name)
        self.tracks.append(new_track)
        return new_track

    def to_json(self) -> str:
        """Serializes the entire project state into a JSON string for saving."""
        return json.dumps(asdict(self), indent=4)