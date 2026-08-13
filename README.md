# MovieEditorApp (Alpha)

A modular, production-grade Non-Linear Video Editor (NLE) built entirely in Python. 

Inspired by the clean, intuitive interfaces of modern editing software like CapCut, MovieEditor was originally designed and developed as a streamlined, custom editing tool for my girlfriend. Because it was built with a specific end-user in mind, the focus is entirely on user experience, responsiveness, and simplicity. Under the hood, it boasts a strictly decoupled, highly scalable architecture making it an excellent showcase of modern Python desktop application development.

---

## 🚀 Current Features

* **Interactive Multi-Track Timeline:** Drag-and-drop functionality for placing clips onto dedicated video and audio tracks.
* **Real-Time Playback Engine:** Smooth, lag-free video scrubbing and playback powered by a custom caching engine.
* **Dynamic Media Pool:** Import and manage local `.mp4` and media files seamlessly.
* **Precision Trimming:** Context-menu integration allowing users to manually set specific In and Out points (Play Time) for exact clip durations.
* **Event-Driven UI:** A completely non-blocking PyQt6 interface utilizing signal/slot architecture.

---

## 🧠 Software Architecture

This project strictly adheres to a modular design pattern, ensuring that the interface, data, and processing logic are completely isolated. 

### 1. The Data Models (`src/models/`)
The **Source of Truth**. Built using lightweight Python `dataclasses`, these models represent the project state (Tracks, Clips, Resolutions). They contain zero UI or media processing logic and can instantly serialize to/from JSON for saving and loading project files.

### 2. The Engine (`src/engine/`)
The **Backend Muscle**. Powered by `moviepy` and `numpy`, the engine handles all heavy media extraction and rendering. It caches loaded video files in memory to ensure UI interactions (like scrubbing the timeline) instantly retrieve the correct frames without freezing the main application thread.

### 3. The UI (`src/ui/`)
The **Visual Shell**. Built with `PyQt6`, the interface is strictly event-driven. It does not own the project data or process video. It simply reads state from the Models, requests visual frames from the Engine, and emits custom `pyqtSignals` when user interactions occur. 

---

## 🛠️ Tech Stack

* **Language:** Python 3.10+
* **GUI Framework:** PyQt6
* **Media Processing:** MoviePy, NumPy
* **Testing:** Pytest (Test-Driven Development enforced)
* **Packaging:** Setuptools (pyproject.toml)

---

## 💻 Installation & Usage
1. **Clone the repository:**
   ```bash
   git clone https://github.com/dawidnaessie/MovieEditorApp.git
   cd MovieEditorApp
   ```
2. **Create and activate a virtual environment:**
  ```bash
  # On Windows
  python -m venv .venv
  .venv\Scripts\activate

  # On macOS/Linux
  python3 -m venv .venv
  source .venv/bin/activate
  ```
3. **Install the project in editable mode:**
  ```bash
  pip install -e .
  ```
4. **Run the application:**
   ```bash
   python src/main.py
   ```

---

## 📦 Building Standalone Executable (.exe)

To build a standalone Windows `.exe` without requiring Python on the target machine:

```powershell
pip install pyinstaller
pyinstaller --noconfirm --onedir --windowed --name "MovieEditor" --paths "src" src/main.py
```

For full options (Single-File vs One-Folder, custom icons, GUI builder, troubleshooting), see the [BUILD_EXE.md](BUILD_EXE.md) guide.
