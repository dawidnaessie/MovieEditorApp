# Feature Request: Set Clip Play Time (In/Out Points)

## Overview
This document outlines the implementation of a new feature: allowing the user to right-click a clip on the timeline and manually type in the exact start and end seconds for that clip. 

**CRITICAL DIRECTIVE:** Do NOT refactor, rewrite, or touch any existing logic for playback, drag-and-drop, or engine extraction. You are only adding this specific context menu, the popup dialog, and the signal to update the model's start/end times.

All implementation must strictly adhere to the AI Agent guidelines found in `docs/ai_agents/`. Every new feature requires corresponding `pytest` coverage.

---

## UI Developer Tasks (`src/ui/`)

1. **Create the Input Dialog (`src/ui/dialogs.py` or similar):**
   * Create a new `QDialog` named `SetTimeDialog`.
   * It should contain two `QDoubleSpinBox` or `QLineEdit` inputs: "Start Time (seconds)" and "End Time (seconds)".
   * Include "OK" and "Cancel" buttons.
   * Pre-fill the inputs with the clip's current `source_start` and `source_end` values.

2. **Add Context Menu to Clips (`src/ui/timeline_view.py`):**
   * Override the `contextMenuEvent` inside your existing `ClipWidget` class.
   * Create a `QMenu`. Add placeholder actions for "Delete" and "Cut" (if not already present), and add a new action named "Set Play Time...".
   * When "Set Play Time..." is clicked, open the `SetTimeDialog`.

3. **Emit Update Signal:**
   * If the user clicks "OK" in the dialog, emit a custom signal from the timeline (e.g., `clip_time_updated(clip_id: str, new_start: float, new_end: float)`).
   * Automatically update the `ClipWidget`'s visual width using your existing `PIXELS_PER_SECOND` math, as the clip's duration has now changed.

4. **Testing (`tests/test_ui/`):**
   * Write a test to ensure the `SetTimeDialog` correctly instantiates, accepts numeric input, and returns the correct start/end values when accepted.

---

## Data Model Architect Tasks (`src/models/`)

1. **Update Clip Model (`src/models/clip.py`):**
   * Add a method to the `Clip` class (e.g., `update_source_times(new_start: float, new_end: float)`).
   * Include basic validation (e.g., `new_end` must be strictly greater than `new_start`, neither can be negative).
   * Ensure the `duration` property automatically reflects this new math (it already should based on `source_end - source_start`).

2. **Testing (`tests/test_models/`):**
   * Write a test in `tests/test_models/test_clip.py` that validates `update_source_times` successfully updates the properties, recalculates duration, and throws a `ValueError` if the user tries to set an end time that is earlier than the start time.

---

## Engine Expert Tasks (`src/engine/`)

* **NO CHANGES REQUIRED:** Because the `PreviewEngine` was previously programmed to respect `clip.source_start`, updating the model will automatically make the engine extract the correct frames. Do not touch the engine code for this feature.