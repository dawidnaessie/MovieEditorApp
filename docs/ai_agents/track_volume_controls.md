# Feature Request: Track Volume Control and Muting

## Overview
This document outlines the implementation of track-level volume control. The user needs the ability to adjust the volume of an entire track (e.g., Video 1, Audio 1) or mute it completely. This is essential for creating music videos or mixing dialogue over background music.

**CRITICAL DIRECTIVE:** Do NOT refactor, rewrite, or touch any existing logic for drag-and-drop, video frame extraction, or timeline scrolling. You are ONLY adding volume properties to the track, UI controls to the track headers, and audio processing logic to the engine.

All implementation must strictly adhere to the AI Agent guidelines found in `docs/ai_agents/`. Every new feature requires corresponding `pytest` coverage.

---

## Data Model Architect Tasks (`src/models/`)

1. **Update Track Model (`src/models/project.py`):**
   * Add a `volume` property to the `Track` dataclass (type `float`, default `1.0` where 1.0 is 100% volume).
   * Add an `is_muted` property (type `bool`, default `False`).
   * Add a method to update these values (e.g., `set_volume(level: float)` and `toggle_mute()`).

2. **Testing (`tests/test_models/`):**
   * Write tests in `tests/test_models/test_project.py` to verify that changing track volume and muting updates the properties correctly and that they serialize to JSON properly.

---

## UI Developer Tasks (`src/ui/`)

1. **Update Track Headers (`src/ui/timeline_view.py`):**
   * Locate the widget that draws the track names (e.g., "Video 1", "Audio 1") on the left side of the timeline.
   * Add a small UI control panel to each track header containing:
     * A Mute Button (`QPushButton` with a speaker icon or just "M" text). It should have a distinct visual toggle state (e.g., turns red when muted).
     * A Volume Slider (`QSlider`, horizontal, ranging from 0 to 200, defaulting to 100).
   
2. **Emit Signals:**
   * When the slider is moved, calculate the float value (e.g., slider value `50` = `0.5` float) and emit a signal: `track_volume_changed(track_id: str, new_volume: float)`.
   * When the mute button is clicked, emit: `track_mute_toggled(track_id: str, is_muted: bool)`.

3. **Testing (`tests/test_ui/`):**
   * Write a test to ensure the Track Header widget correctly emits the volume and mute signals with the expected data types.

---

## Engine Expert Tasks (`src/engine/`)

1. **Audio Mixing Support (`src/engine/render_engine.py` or equivalent):**
   * When constructing the final audio mix (or real-time audio playback, if implemented), the engine must read the `Track.volume` and `Track.is_muted` properties.
   * If `is_muted` is True, apply a volume of `0.0` to all clips on that track.
   * If `is_muted` is False, apply the `Track.volume` multiplier to all clips on that track using `moviepy.audio.fx.all.volumex` (or the equivalent audio array multiplication in NumPy).

2. **Testing (`tests/test_engine/`):**
   * Write a test that programmatically creates a dummy audio clip, processes it through a track with `volume=0.5`, and verifies the resulting audio array's amplitude is halved.