# Phase 2: Core Editing & Export Pipeline

## Overview
This document outlines the requirements for Phase 2 of the video editor. The goal is to transition from a basic timeline viewer to a functional, CapCut-inspired Non-Linear Editor (NLE) with cutting tools, mixed media support, and video export capabilities.

All implementation must strictly adhere to the AI Agent guidelines found in `docs/ai_agents/`. Every new feature requires corresponding `pytest` coverage.

---

## Feature 1: The Rendering & Export Engine (MP4/WebM)

### **Engine Expert Tasks (`src/engine/`)**
*   **Create `render_engine.py`:** Build a class responsible for reading the entire `Project` model and using `moviepy` to stitch the tracks together into a final video file.
*   **Format Support:** Support exporting to `.mp4` and `.webm`. 
*   **Non-Blocking:** The render process must run on a separate thread (e.g., using `QThread` or Python's `threading`) so it does not freeze the main application window.
*   **Progress Tracking:** The engine must emit progress callbacks (e.g., percentage complete) so the UI can read them.
*   **Testing:** Write `tests/test_engine/test_render_engine.py` using small, programmatically generated 1-second clips to verify the export completes successfully.

### **UI Developer Tasks (`src/ui/`)**
*   **Export Dialog:** Add an "Export" button to the main window that opens a `QDialog` to select the file name, format (MP4/WebM), and resolution.
*   **Progress Bar:** Display a `QProgressBar` that updates based on the signals emitted by the background rendering thread.

---

## Feature 2: CapCut-Inspired UI/UX Overhaul

### **UI Developer Tasks (`src/ui/`)**
*   **Global Styling:** Update `main_window.py` to use a sophisticated, modern QSS (Qt Style Sheet). It should heavily mimic CapCut's aesthetic:
    *   Deep dark grays for backgrounds (e.g., `#181818`).
    *   Subtle rounded corners on panels and widgets (`border-radius`).
    *   Bright, distinct accent colors for active tools and selected clips (e.g., cyan or vivid blue).
*   **Timeline Polish:** Ensure tracks have clear headers, the playhead is distinct and easy to grab, and timecodes (e.g., `00:01:23:15`) are displayed clearly above the timeline.

---

## Feature 3: Editing Tools (Scissors, Trimming, & Image Support)

### **Data Model Architect Tasks (`src/models/`)**
*   **Media Type Handling:** Update the `Clip` model in `clip.py` to differentiate between video and static images. 
*   **Image Duration:** For images, `source_start` and `source_end` are irrelevant. Add logic so that an image clip defaults to a set duration (e.g., 5.0 seconds) but can be extended infinitely.
*   **Split Logic (Scissors):** Add a method to the `Track` model (e.g., `split_clip(clip_id, global_time)`). This method should locate the clip, truncate its `source_end`, and generate a brand-new `Clip` object for the remainder of the footage.
*   **Testing:** Write tests in `tests/test_models/test_project.py` to prove that splitting a clip correctly updates durations and timeline positions.

### **UI Developer Tasks (`src/ui/`)**
*   **Toolbar:** Create a new `ToolbarView` above the timeline containing selectable tools (e.g., "Pointer/Select" [V] and "Razor/Blade" [C]).
*   **Razor Tool Interaction:** When the Razor tool is active and the user clicks on a `ClipWidget` in the timeline, the UI must calculate the exact time of the click based on the X-coordinate and emit a `split_requested(clip_id, time)` signal.
*   **Edge Trimming:** Allow the user to hover over the left or right edge of a `ClipWidget`. The cursor should change to a resize arrow. Dragging the edge should visually resize the clip and emit a `trim_requested` signal to update the data model (shortening a video or extending an image).

### **Engine Expert Tasks (`src/engine/`)**
*   **Image Processing:** Update `preview_engine.py`. If the `Clip` points to an image file (e.g., `.png`, `.jpg`), `moviepy` (or `PIL`/`cv2`) should simply return that static image array regardless of the requested timestamp.