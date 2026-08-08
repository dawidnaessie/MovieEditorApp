import uuid
from dataclasses import dataclass, field

@dataclass
class Clip:
    """Represents a single piece of media on the timeline."""
    file_path: str
    name: str
    
    # Times are represented in seconds (e.g., 1.5 is one and a half seconds)
    source_start: float = 0.0      # Where the cut starts in the original file
    source_end: float = 0.0        # Where the cut ends in the original file
    timeline_position: float = 0.0 # Where this clip sits on the main timeline
    
    # We generate a unique ID for every clip so the UI can keep track of them
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    
    @property
    def duration(self) -> float:
        """Calculates the current length of the clip."""
        return self.source_end - self.source_start