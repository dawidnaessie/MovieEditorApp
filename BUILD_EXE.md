# How to Convert MovieEditor to a Windows `.exe`

This guide explains how to easily compile **MovieEditorApp** into a standalone Windows executable (`.exe`) using **PyInstaller** or a graphical tool (**auto-py-to-exe**).

---

## ⚡ Quick Start (1-Minute Guide)

### 1. Activate Your Virtual Environment
Open PowerShell or Command Prompt in the project root directory:

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1

# Or Command Prompt (cmd.exe)
.\.venv\Scripts\activate.bat
```

### 2. Install PyInstaller
```powershell
pip install pyinstaller
```

### 3. Run the Build Command

#### 🌟 Option A: Folder Distribution (Recommended — Fast Startup)
Creates a folder containing the `.exe` and required dependencies. This provides the fastest application startup time for PyQt6/MoviePy:

```powershell
pyinstaller --noconfirm --onedir --windowed --name "MovieEditor" --paths "src" src/main.py
```
> **Output location:** `dist/MovieEditor/MovieEditor.exe`

---

#### 📦 Option B: Single Portable File (`.exe`)
Packs everything into a single, self-contained executable:

```powershell
pyinstaller --noconfirm --onefile --windowed --name "MovieEditor" --paths "src" src/main.py
```
> **Output location:** `dist/MovieEditor.exe`

---

## ⚙️ Command Flags Explained

| Flag | Purpose |
| :--- | :--- |
| `--paths "src"` | **Crucial:** Tells PyInstaller where to find project modules (`models`, `ui`, `engine`). |
| `--windowed` (or `-w`) | Hides the background black console/terminal window so only the GUI appears. |
| `--onefile` (or `-F`) | Packages everything into a single `.exe` file. |
| `--onedir` (or `-D`) | Packages into a directory with `MovieEditor.exe` + `_internal` folder (fastest launch speed). |
| `--name "MovieEditor"` | Sets the output executable name to `MovieEditor.exe`. |
| `--noconfirm` | Overwrites previous build output without prompting. |
| `--icon "path/to/icon.ico"` | *(Optional)* Attaches a custom Windows desktop/taskbar application icon. |

---

## 🎨 Adding a Custom App Icon

If you have a `.ico` file (e.g. `icon.ico`), add the `--icon` parameter:

```powershell
pyinstaller --noconfirm --onedir --windowed --icon "icon.ico" --name "MovieEditor" --paths "src" src/main.py
```

---

## 🖥️ Graphical Interface Method (`auto-py-to-exe`)

If you prefer a point-and-click GUI instead of terminal commands:

1. **Install auto-py-to-exe:**
   ```powershell
   pip install auto-py-to-exe
   ```

2. **Launch the GUI:**
   ```powershell
   auto-py-to-exe
   ```

3. **Configure the settings in your browser:**
   - **Script Location:** Browse to `src/main.py`
   - **Onefile:** Select *One Directory* (recommended) or *One File*
   - **Console Window:** Select *Window Based (hide the console)*
   - **Advanced -> Additional Path (search path):** Add `src` (or the full path to `src/`)
   - **Icon (optional):** Browse to your `.ico` file
   - Click **CONVERT .PY TO .EXE**

---

## 🚀 1-Click Automated Build Script

You can create a PowerShell build script to clean up previous builds and compile in one go.

Run this directly in PowerShell:

```powershell
# Clean old build artifacts
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue build, dist

# Build the executable
pyinstaller --noconfirm --onedir --windowed --name "MovieEditor" --paths "src" src/main.py

Write-Host "`nBuild complete! Executable is at: dist/MovieEditor/MovieEditor.exe" -ForegroundColor Green
```

---

## 🛠️ Troubleshooting & Tips

### 1. App Crashes Immediately on Launch Without Error
If the executable closes instantly upon launch, re-build **without** the `--windowed` flag to view error messages in the terminal:

```powershell
# Build with console visible for debugging
pyinstaller --noconfirm --onedir --name "MovieEditor_Debug" --paths "src" src/main.py
```
Run `dist/MovieEditor_Debug/MovieEditor_Debug.exe` from PowerShell to see any missing module or runtime tracebacks.

### 2. MoviePy / FFmpeg Dependency
MoviePy automatically bundles `imageio_ffmpeg` binary during the PyInstaller build via `pyinstaller-hooks-contrib`. If FFmpeg is ever missing on a target machine, ensure `imageio-ffmpeg` is installed in your `.venv` before running PyInstaller (`pip install imageio-ffmpeg`).

### 3. Startup Speed Difference (One-File vs One-Folder)
- **`--onefile`**: On every launch, Windows extracts all DLLs, PyQt6 libraries, and Python runtimes to a temporary directory (`%TEMP%\_MEIxxxxxx`). This causes a 3–6 second delay on startup.
- **`--onedir`**: Files are pre-extracted in the folder, so the app opens instantly (< 0.5s). For video editing tools, `--onedir` (zipped for distribution) is strongly recommended.

### 4. Windows Defender / SmartScreen Warning
Unsigned executables built with PyInstaller can occasionally trigger Windows SmartScreen ("Windows protected your PC").
- Click **More info** -> **Run anyway**.
- For public distribution, signing the binary with a code signing certificate or adding it to your antivirus exclusion list resolves this.

---

## 🧹 Cleaning Up After Building
Build artifacts are automatically ignored by Git (configured in `.gitignore`). To manually delete build cache:

```powershell
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue build, dist, MovieEditor.spec
```
