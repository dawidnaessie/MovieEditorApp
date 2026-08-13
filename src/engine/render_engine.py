"""Production video rendering and export engine using MoviePy.

Compiles multi-track video projects (video clips, static images, and audio tracks)
into final master video files in MP4 or WebM formats with non-blocking progress tracking.
Strictly free of UI widget code (conforming to docs/ai_agents/engine_expert.md).
"""

import os
import threading
from typing import Callable, List, Optional, Tuple
from proglog import ProgressBarLogger

import numpy as np
from moviepy import (
    AudioFileClip,
    ColorClip,
    CompositeAudioClip,
    CompositeVideoClip,
    ImageClip,
    VideoFileClip,
)
import moviepy.video.fx as vfx
from PIL import Image
from PyQt6.QtCore import QObject, QRunnable, pyqtSignal, pyqtSlot

from models.clip import Clip, detect_media_type
from models.project import Project


class RenderWorkerSignals(QObject):
    """PyQt signal container for background rendering progress and completion."""

    progress_updated = pyqtSignal(float, str)  # (percent 0.0-100.0, status_text)
    rendering_finished = pyqtSignal(bool, str)  # (success, message_or_path)


class RenderProgressCallbackLogger(ProgressBarLogger):
    """Custom proglog logger that forwards MoviePy render progress percentages."""

    def __init__(
        self,
        progress_callback: Optional[Callable[[float, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ):
        super().__init__()
        self.progress_callback = progress_callback
        self.cancel_check = cancel_check
        self.last_percent = -1.0

    def callback(self, **changes):
        if self.cancel_check and self.cancel_check():
            raise InterruptedError("Rendering was cancelled by user.")

    def bars_callback(self, bar, attr, value, old_value=None):
        if self.cancel_check and self.cancel_check():
            raise InterruptedError("Rendering was cancelled by user.")

        if bar in ("t", "frame") and attr == "index":
            total = self.bars.get(bar, {}).get("total", 1)
            if total and total > 0:
                percent = min(100.0, max(0.0, (value / total) * 100.0))
                if abs(percent - self.last_percent) >= 0.5:
                    self.last_percent = percent
                    if self.progress_callback:
                        self.progress_callback(percent, f"Rendering frames: {value}/{total} ({percent:.1f}%)")


def _apply_clip_timing(moviepy_clip, start_time: float, duration: float):
    """Applies start time and duration in a way compatible with MoviePy 1.x and 2.x."""
    clip = moviepy_clip
    if hasattr(clip, "with_start"):
        clip = clip.with_start(start_time)
    elif hasattr(clip, "set_start"):
        clip = clip.set_start(start_time)

    if hasattr(clip, "with_duration"):
        clip = clip.with_duration(duration)
    elif hasattr(clip, "set_duration"):
        clip = clip.set_duration(duration)
    return clip


class RenderEngine:
    """Production rendering engine for compiling multi-track video projects into master media files."""

    def __init__(self):
        self._lock = threading.Lock()
        self.is_cancelled = False

    def cancel(self) -> None:
        """Flags the active rendering process for cancellation."""
        self.is_cancelled = True

    def render_project(
        self,
        project: Project,
        output_path: str,
        export_format: str = "mp4",
        resolution: Optional[Tuple[int, int]] = None,
        fps: Optional[float] = None,
        progress_callback: Optional[Callable[[float, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> bool:
        """Stitches all video and audio tracks in a Project into a rendered export file.

        Args:
            project (Project): Project data model containing tracks and clip arrangement.
            output_path (str): Filesystem path where the rendered video will be saved.
            export_format (str): 'mp4' (H.264/AAC) or 'webm' (VP8/VP9/Vorbis). Defaults to 'mp4'.
            resolution (Optional[Tuple[int, int]]): Target (width, height) or None for project resolution.
            fps (Optional[float]): Output frame rate or None for project fps.
            progress_callback (Optional[Callable[[float, str], None]]): Callback for percentage and status.
            cancel_check (Optional[Callable[[], bool]]): Function returning True if render is aborted.

        Returns:
            bool: True if render succeeded, False if failed or cancelled.
        """
        self.is_cancelled = False
        target_resolution = resolution or project.resolution
        target_fps = float(fps or project.fps or 30.0)
        total_duration = project.get_total_duration()

        if total_duration <= 0:
            if progress_callback:
                progress_callback(0.0, "Cannot export empty timeline.")
            return False

        # Ensure output directory exists
        out_dir = os.path.dirname(output_path)
        if out_dir and not os.path.exists(out_dir):
            os.makedirs(out_dir, exist_ok=True)

        if progress_callback:
            progress_callback(0.0, "Preparing media composition...")

        loaded_handles: List[any] = []
        video_clips: List[any] = []
        audio_clips: List[any] = []

        try:
            # 1. Base black canvas clip covering the entire timeline
            base_bg = ColorClip(
                size=target_resolution,
                color=(0, 0, 0),
                duration=total_duration,
            )
            base_bg = _apply_clip_timing(base_bg, 0.0, total_duration)
            video_clips.append(base_bg)
            loaded_handles.append(base_bg)

            # 2. Build visual track clips (in track order, lower tracks first, higher tracks over top)
            for track in project.tracks:
                if track.track_type == "video":
                    for clip_model in track.clips:
                        if not clip_model.file_path or not os.path.exists(clip_model.file_path):
                            continue

                        media_type = clip_model.media_type or detect_media_type(clip_model.file_path)

                        if media_type == "image":
                            img_clip = ImageClip(clip_model.file_path)
                            img_clip = _apply_clip_timing(img_clip, clip_model.timeline_position, clip_model.duration)

                            # Apply rotation and flip effects
                            rot = int(getattr(clip_model, "rotation", 0)) % 360
                            flip_h = bool(getattr(clip_model, "flip_horizontal", False))
                            flip_v = bool(getattr(clip_model, "flip_vertical", False))

                            img_effects = []
                            if rot == 90:
                                img_effects.append(vfx.Rotate(270, expand=True))
                            elif rot == 180:
                                img_effects.append(vfx.Rotate(180, expand=True))
                            elif rot == 270:
                                img_effects.append(vfx.Rotate(90, expand=True))

                            if flip_h:
                                img_effects.append(vfx.MirrorX())
                            if flip_v:
                                img_effects.append(vfx.MirrorY())

                            if img_effects:
                                try:
                                    img_clip = img_clip.with_effects(img_effects)
                                except Exception as e:
                                    print(f"RenderEngine Warning: Failed to apply effects to image: {e}")

                            if hasattr(img_clip, "resized"):
                                img_clip = img_clip.resized(target_resolution)
                            elif hasattr(img_clip, "resize"):
                                img_clip = img_clip.resize(target_resolution)
                            video_clips.append(img_clip)
                            loaded_handles.append(img_clip)

                        else:  # Video clip
                            v_clip = VideoFileClip(clip_model.file_path)
                            loaded_handles.append(v_clip)

                            # Subclip the trimmed active segment
                            src_start = max(0.0, clip_model.source_start)
                            src_range = max(0.0, clip_model.source_end - clip_model.source_start)
                            src_end = min(getattr(v_clip, "duration", 0.0) or clip_model.source_end, clip_model.source_end)
                            if src_end <= src_start:
                                src_end = src_start + (src_range if src_range > 0 else clip_model.duration)

                            if hasattr(v_clip, "subclipped"):
                                segment = v_clip.subclipped(src_start, src_end)
                            elif hasattr(v_clip, "subclip"):
                                segment = v_clip.subclip(src_start, src_end)
                            else:
                                segment = v_clip

                            # If clip is extended / slowed down or sped up, apply speed scaling
                            target_dur = clip_model.duration
                            eff_src_dur = max(0.05, float(getattr(segment, "duration", 0.0) or (src_end - src_start)))
                            if target_dur > 0 and abs(target_dur - eff_src_dur) > 0.05:
                                speed_factor = eff_src_dur / target_dur
                                try:
                                    from moviepy.video.fx import MultiplySpeed
                                    segment = segment.with_effects([MultiplySpeed(speed_factor)])
                                except Exception:
                                    try:
                                        if hasattr(segment, "with_speed_scaled"):
                                            segment = segment.with_speed_scaled(speed_factor)
                                    except Exception:
                                        pass

                            # Apply rotation and flip effects
                            rot = int(getattr(clip_model, "rotation", 0)) % 360
                            flip_h = bool(getattr(clip_model, "flip_horizontal", False))
                            flip_v = bool(getattr(clip_model, "flip_vertical", False))

                            vid_effects = []
                            if rot == 90:
                                vid_effects.append(vfx.Rotate(270, expand=True))
                            elif rot == 180:
                                vid_effects.append(vfx.Rotate(180, expand=True))
                            elif rot == 270:
                                vid_effects.append(vfx.Rotate(90, expand=True))

                            if flip_h:
                                vid_effects.append(vfx.MirrorX())
                            if flip_v:
                                vid_effects.append(vfx.MirrorY())

                            if vid_effects:
                                try:
                                    segment = segment.with_effects(vid_effects)
                                except Exception as e:
                                    print(f"RenderEngine Warning: Failed to apply effects to video: {e}")

                            # Apply track volume / mute to video audio if present
                            if getattr(segment, "audio", None) is not None:
                                if getattr(track, "is_muted", False) or getattr(track, "volume", 1.0) <= 0.0:
                                    if hasattr(segment, "without_audio"):
                                        segment = segment.without_audio()
                                    else:
                                        segment.audio = None
                                elif abs(float(getattr(track, "volume", 1.0)) - 1.0) > 1e-4:
                                    vol = float(track.volume)
                                    try:
                                        from moviepy.audio.fx import MultiplyVolume
                                        segment = segment.with_audio(segment.audio.with_effects([MultiplyVolume(vol)]))
                                    except Exception:
                                        try:
                                            if hasattr(segment.audio, "with_volume_scaled"):
                                                segment = segment.with_audio(segment.audio.with_volume_scaled(vol))
                                            elif hasattr(segment.audio, "volumex"):
                                                segment = segment.with_audio(segment.audio.volumex(vol))
                                        except Exception:
                                            pass

                            segment = _apply_clip_timing(segment, clip_model.timeline_position, clip_model.duration)
                            if hasattr(segment, "resized"):
                                segment = segment.resized(target_resolution)
                            elif hasattr(segment, "resize"):
                                segment = segment.resize(target_resolution)

                            video_clips.append(segment)
                            loaded_handles.append(segment)

                elif track.track_type == "audio":
                    for clip_model in track.clips:
                        if not clip_model.file_path or not os.path.exists(clip_model.file_path):
                            continue

                        try:
                            a_clip = AudioFileClip(clip_model.file_path)
                            loaded_handles.append(a_clip)
                            src_start = max(0.0, clip_model.source_start)
                            src_end = clip_model.source_end if clip_model.source_end > src_start else src_start + clip_model.duration

                            if hasattr(a_clip, "subclipped"):
                                a_seg = a_clip.subclipped(src_start, src_end)
                            elif hasattr(a_clip, "subclip"):
                                a_seg = a_clip.subclip(src_start, src_end)
                            else:
                                a_seg = a_clip

                            # Apply track volume / mute
                            if getattr(track, "is_muted", False) or getattr(track, "volume", 1.0) <= 0.0:
                                try:
                                    from moviepy.audio.fx import MultiplyVolume
                                    a_seg = a_seg.with_effects([MultiplyVolume(0.0)])
                                except Exception:
                                    try:
                                        if hasattr(a_seg, "with_volume_scaled"):
                                            a_seg = a_seg.with_volume_scaled(0.0)
                                        elif hasattr(a_seg, "volumex"):
                                            a_seg = a_seg.volumex(0.0)
                                    except Exception:
                                        pass
                            elif abs(float(getattr(track, "volume", 1.0)) - 1.0) > 1e-4:
                                vol = float(track.volume)
                                try:
                                    from moviepy.audio.fx import MultiplyVolume
                                    a_seg = a_seg.with_effects([MultiplyVolume(vol)])
                                except Exception:
                                    try:
                                        if hasattr(a_seg, "with_volume_scaled"):
                                            a_seg = a_seg.with_volume_scaled(vol)
                                        elif hasattr(a_seg, "volumex"):
                                            a_seg = a_seg.volumex(vol)
                                    except Exception:
                                        pass

                            a_seg = _apply_clip_timing(a_seg, clip_model.timeline_position, clip_model.duration)
                            audio_clips.append(a_seg)
                            loaded_handles.append(a_seg)
                        except Exception as e:
                            print(f"RenderEngine Warning: Could not load audio {clip_model.file_path}: {e}")

            # 3. Create master composite
            composite = CompositeVideoClip(video_clips, size=target_resolution)
            composite = _apply_clip_timing(composite, 0.0, total_duration)
            loaded_handles.append(composite)

            if audio_clips:
                all_audios = list(audio_clips)
                if composite.audio is not None:
                    all_audios.insert(0, composite.audio)
                composite_audio = CompositeAudioClip(all_audios)
                composite_audio = _apply_clip_timing(composite_audio, 0.0, total_duration)
                if hasattr(composite, "with_audio"):
                    composite = composite.with_audio(composite_audio)
                elif hasattr(composite, "set_audio"):
                    composite = composite.set_audio(composite_audio)
                loaded_handles.append(composite_audio)

            # 4. Configure codecs based on format
            logger = RenderProgressCallbackLogger(
                progress_callback=progress_callback,
                cancel_check=cancel_check or (lambda: self.is_cancelled),
            )

            fmt = export_format.lower().strip().replace(".", "")
            if fmt == "webm":
                video_codec = "libvpx-vp9"
                audio_codec = "libvorbis"
                ffmpeg_params = ["-b:v", "3M"]
            else:  # mp4
                video_codec = "libx264"
                audio_codec = "aac"
                ffmpeg_params = ["-pix_fmt", "yuv420p"]

            if progress_callback:
                progress_callback(5.0, "Encoding video frames...")

            try:
                composite.write_videofile(
                    output_path,
                    fps=target_fps,
                    codec=video_codec,
                    audio_codec=audio_codec,
                    ffmpeg_params=ffmpeg_params,
                    logger=logger,
                )
            except InterruptedError:
                if os.path.exists(output_path):
                    try:
                        os.remove(output_path)
                    except Exception:
                        pass
                return False
            except Exception as e:
                # Fallback for WebM codec if libvpx-vp9 is missing
                if fmt == "webm":
                    composite.write_videofile(
                        output_path,
                        fps=target_fps,
                        codec="libvpx",
                        audio_codec="libvorbis",
                        logger=logger,
                    )
                else:
                    raise e

            if progress_callback:
                progress_callback(100.0, "Export complete!")
            return True

        except Exception as e:
            print(f"RenderEngine Error: Rendering failed: {e}")
            if progress_callback:
                progress_callback(0.0, f"Export failed: {e}")
            return False

        finally:
            for handle in loaded_handles:
                try:
                    if hasattr(handle, "close"):
                        handle.close()
                except Exception:
                    pass


class RenderWorker(QRunnable):
    """Background runnable worker for non-blocking video exports in PyQt6."""

    def __init__(
        self,
        engine: RenderEngine,
        project: Project,
        output_path: str,
        export_format: str = "mp4",
        resolution: Optional[Tuple[int, int]] = None,
        fps: Optional[float] = None,
    ):
        super().__init__()
        self.setAutoDelete(True)
        self.engine = engine
        self.project = project
        self.output_path = output_path
        self.export_format = export_format
        self.resolution = resolution
        self.fps = fps
        self.signals = RenderWorkerSignals()
        self.is_cancelled = False

    def cancel(self) -> None:
        """Cancels background rendering."""
        self.is_cancelled = True
        self.engine.cancel()

    @pyqtSlot()
    def run(self) -> None:
        """Executes rendering and emits Qt completion signals."""
        def on_progress(percent: float, status_msg: str):
            if not self.is_cancelled:
                self.signals.progress_updated.emit(percent, status_msg)

        success = self.engine.render_project(
            project=self.project,
            output_path=self.output_path,
            export_format=self.export_format,
            resolution=self.resolution,
            fps=self.fps,
            progress_callback=on_progress,
            cancel_check=lambda: self.is_cancelled,
        )

        if not self.is_cancelled:
            self.signals.rendering_finished.emit(success, self.output_path if success else "Export failed or cancelled.")
