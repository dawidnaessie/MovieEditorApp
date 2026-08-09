from collections import OrderedDict
import os
import threading
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
from PIL import Image
from moviepy import VideoFileClip

from models.clip import Clip
from models.project import Project


class PreviewEngine:
    """
    Handles extracting video frames, generating filmstrip thumbnails,
    and querying media metadata without freezing the UI.
    Strictly free of UI code (no PyQt).
    """

    def __init__(self, cache_size: int = 120):
        # Cache loaded video file clips
        self._loaded_media: Dict[str, VideoFileClip] = {}
        # Media metadata cache
        self._metadata_cache: Dict[str, Dict[str, Any]] = {}
        # Decoded RGB frame LRU cache: (file_path, quant_time) -> np.ndarray
        self._frame_cache: OrderedDict[Tuple[str, int], np.ndarray] = OrderedDict()
        # Audio soundarray cache: file_path -> (num_samples, 2) float32 array
        self._audio_cache: Dict[str, Optional[np.ndarray]] = {}
        self._cache_size = max(30, cache_size)
        self._lock = threading.Lock()


    def _get_media(self, file_path: str) -> Optional[VideoFileClip]:
        """Thread-safely gets or loads a VideoFileClip for the given path."""
        if not file_path or not os.path.exists(file_path):
            return None

        with self._lock:
            if file_path not in self._loaded_media:
                try:
                    clip = VideoFileClip(file_path)
                    self._loaded_media[file_path] = clip
                    self._metadata_cache[file_path] = {
                        "duration": float(getattr(clip, "duration", 0.0) or 0.0),
                        "fps": float(getattr(clip, "fps", 30.0) or 30.0),
                        "size": getattr(clip, "size", [1920, 1080]) or [1920, 1080],
                    }
                except Exception as e:
                    print(f"Engine Error: Could not load media {file_path}: {e}")
                    return None
            return self._loaded_media.get(file_path)

    def get_media_info(self, file_path: str) -> Dict[str, Any]:
        """Returns video metadata (duration, fps, size) for a file."""
        if file_path in self._metadata_cache:
            return self._metadata_cache[file_path]

        media = self._get_media(file_path)
        if media:
            return self._metadata_cache.get(file_path, {
                "duration": float(getattr(media, "duration", 0.0)),
                "fps": float(getattr(media, "fps", 30.0)),
                "size": getattr(media, "size", [1920, 1080]),
            })
        return {"duration": 10.0, "fps": 30.0, "size": [1920, 1080]}

    def get_media_duration(self, file_path: str) -> float:
        """Returns the media duration in seconds for a video file."""
        info = self.get_media_info(file_path)
        return float(info.get("duration", 10.0))

    def get_frame(self, clip: Clip, time_in_seconds: float) -> np.ndarray:
        """
        Reads a video file and returns a single frame as a raw RGB numpy array (H, W, 3).
        Uses an LRU cache to make scrubbing and re-playing instant.
        Returns a solid black frame if file is missing, broken, or empty.
        """
        media = self._get_media(clip.file_path)
        if media is None:
            return np.zeros((1080, 1920, 3), dtype=np.uint8)

        # Account for clip cut offset
        actual_media_time = clip.source_start + time_in_seconds
        media_duration = float(getattr(media, "duration", 0.0) or 0.0)
        # Avoid reading past the final frame buffer by safety margin of 0.04s (approx 1 frame)
        max_safe_time = max(0.0, media_duration - 0.04) if media_duration > 0.1 else media_duration
        safe_time = max(0.0, min(actual_media_time, max_safe_time))

        # Quantize timestamp to 10ms bucket for caching
        cache_key = (clip.file_path, int(round(safe_time * 100)))

        with self._lock:
            if cache_key in self._frame_cache:
                frame = self._frame_cache[cache_key]
                self._frame_cache.move_to_end(cache_key)
                return frame

        # Extract frame via MoviePy
        try:
            with self._lock:
                raw_frame = media.get_frame(safe_time)
                if not isinstance(raw_frame, np.ndarray) or raw_frame.dtype != np.uint8:
                    raw_frame = np.ascontiguousarray(raw_frame, dtype=np.uint8)

                if len(self._frame_cache) >= self._cache_size:
                    self._frame_cache.popitem(last=False)
                self._frame_cache[cache_key] = raw_frame

            return raw_frame
        except Exception as e:
            width, height = getattr(media, "size", (1920, 1080))
            return np.zeros((height, width, 3), dtype=np.uint8)


    def get_project_frame(self, project: Project, global_time: float) -> np.ndarray:
        """
        Extracts the frame at global_time across all tracks in a Project.
        1. Loops through project.tracks to find which Clip exists at global_time.
        2. Calculates the local time for that clip.
        3. Extracts and returns the frame for that specific clip.
        4. If no clip exists at global_time, returns a clean black frame.
        """
        match = project.find_clip_at(global_time)
        if match is not None:
            _, clip, local_time = match
            return self.get_frame(clip, local_time)

        # Return solid black frame if playhead is over an empty gap
        width, height = project.resolution if hasattr(project, "resolution") else (1920, 1080)
        return np.zeros((height, width, 3), dtype=np.uint8)

    def extract_clip_thumbnails(
        self,
        file_path: str,
        source_start: float = 0.0,
        duration: float = 10.0,
        count: int = 6,
        thumb_height: int = 36,
    ) -> List[np.ndarray]:
        """
        Extracts a sequence of small thumbnail frames spanning the clip duration
        for rendering the timeline filmstrip under the clip name.
        Uses an isolated clip reader to ensure complete thread-safety with active playback.
        """
        thumbnails: List[np.ndarray] = []
        if not file_path or not os.path.exists(file_path) or duration <= 0:
            return thumbnails

        isolated_clip: Optional[VideoFileClip] = None
        try:
            isolated_clip = VideoFileClip(file_path)
            media_duration = float(getattr(isolated_clip, "duration", 0.0) or duration)
            effective_duration = min(duration, media_duration - source_start)
            if effective_duration <= 0:
                effective_duration = duration

            count = max(1, min(count, 30))
            time_points = [
                source_start + (i + 0.5) * (effective_duration / count)
                for i in range(count)
            ]

            for t in time_points:
                safe_t = max(0.0, min(t, media_duration))
                try:
                    frame = isolated_clip.get_frame(safe_t)
                    if frame is not None and frame.size > 0:
                        h, w = frame.shape[:2]
                        aspect = w / max(1, h)
                        thumb_w = max(16, int(thumb_height * aspect))
                        img = Image.fromarray(frame)
                        img_thumb = img.resize((thumb_w, thumb_height), Image.Resampling.BILINEAR)
                        thumbnails.append(np.array(img_thumb, dtype=np.uint8))
                except Exception as e:
                    print(f"Engine Warning: Failed thumbnail frame at {safe_t:.2f}s: {e}")
                    blank = np.zeros((thumb_height, int(thumb_height * 16 / 9), 3), dtype=np.uint8)
                    thumbnails.append(blank)
        except Exception as e:
            print(f"Engine Warning: Failed to extract thumbnails for {file_path}: {e}")
        finally:
            if isolated_clip is not None:
                try:
                    isolated_clip.close()
                except Exception:
                    pass

        return thumbnails


    @staticmethod
    def format_timecode(seconds: float, fps: float = 30.0) -> str:
        """Formats seconds into standard NLE SMPTE timecode (HH:MM:SS:FF)."""
        safe_secs = max(0.0, seconds)
        safe_fps = max(1.0, fps)
        total_frames = int(round(safe_secs * safe_fps))

        frames = int(total_frames % int(safe_fps))
        total_seconds = int(safe_secs)
        secs = total_seconds % 60
        mins = (total_seconds // 60) % 60
        hours = total_seconds // 3600

        return f"{hours:02d}:{mins:02d}:{secs:02d}:{frames:02d}"

    def get_playback_status(self, project: Project, global_time: float) -> Dict[str, Any]:
        """
        Returns rich metadata regarding the current playback position for UI status indicators:
        - Active video name and track
        - Master timeline frame counter / total project frames
        - Local clip frame counter / total clip frames
        - Formatted SMPTE timecode
        - Track name, resolution, and framerate
        """
        fps = float(project.fps if hasattr(project, "fps") else 30.0)
        total_project_duration = project.get_total_duration()
        global_frame = int(round(global_time * fps)) + 1
        total_project_frames = max(1, int(round(total_project_duration * fps)))

        match = project.find_clip_at(global_time)

        if match is not None:
            track, clip, local_time = match
            clip_frame = clip.time_to_frame(local_time, fps=fps) + 1
            total_clip_frames = clip.frame_count(fps=fps)
            return {
                "has_active_clip": True,
                "clip_name": clip.name,
                "file_path": clip.file_path,
                "track_name": track.name,
                "local_time": local_time,
                "global_time": global_time,
                "clip_duration": clip.duration,
                "clip_frame": clip_frame,
                "total_clip_frames": total_clip_frames,
                "current_frame": global_frame,
                "total_frames": total_project_frames,
                "timecode": self.format_timecode(global_time, fps=fps),
                "fps": fps,
                "resolution": project.resolution,
                "project_duration": total_project_duration,
            }

        return {
            "has_active_clip": False,
            "clip_name": "No Active Clip",
            "file_path": "",
            "track_name": "None",
            "local_time": 0.0,
            "global_time": global_time,
            "clip_duration": 0.0,
            "clip_frame": 0,
            "total_clip_frames": 0,
            "current_frame": global_frame,
            "total_frames": total_project_frames,
            "timecode": self.format_timecode(global_time, fps=fps),
            "fps": fps,
            "resolution": project.resolution,
            "project_duration": total_project_duration,
        }

    def get_media_audio_array(self, file_path: str, sample_rate: int = 44100) -> Optional[np.ndarray]:
        """
        Extracts and caches the full 2-channel float32 audio soundarray of a video/audio file.
        Returns np.ndarray of shape (num_samples, 2) with values in [-1.0, 1.0], or None if no audio.
        """
        if not file_path or not os.path.exists(file_path):
            return None

        with self._lock:
            if file_path in self._audio_cache:
                return self._audio_cache[file_path]

        audio_arr: Optional[np.ndarray] = None
        media = self._get_media(file_path)
        if media is not None and getattr(media, "audio", None) is not None:
            try:
                raw_sound = media.audio.to_soundarray(fps=sample_rate)
                if raw_sound is not None and raw_sound.size > 0:
                    if raw_sound.ndim == 1:
                        raw_sound = np.column_stack([raw_sound, raw_sound])
                    elif raw_sound.shape[1] == 1:
                        raw_sound = np.repeat(raw_sound, 2, axis=1)
                    audio_arr = raw_sound.astype(np.float32)
            except Exception as e:
                print(f"Engine Warning: Could not extract audio from {file_path}: {e}")
                audio_arr = None

        with self._lock:
            self._audio_cache[file_path] = audio_arr

        return audio_arr

    def get_project_audio_pcm(
        self,
        project: Project,
        start_time: float,
        duration: float,
        sample_rate: int = 44100,
    ) -> bytes:
        """
        Extracts and mixes audio samples across all active video and audio tracks for the time window
        [start_time, start_time + duration].
        Returns standard 16-bit 44.1kHz stereo signed little-endian PCM bytes.
        """
        if duration <= 0:
            return b""

        total_samples = max(1, int(round(duration * sample_rate)))
        composite = np.zeros((total_samples, 2), dtype=np.float32)

        active_clips = project.find_all_audio_clips_at(start_time, duration)
        for track, clip, overlap_start, overlap_end in active_clips:
            audio_arr = self.get_media_audio_array(clip.file_path, sample_rate=sample_rate)
            if audio_arr is None or audio_arr.shape[0] == 0:
                continue

            clip_src_start = clip.source_start + (overlap_start - clip.timeline_position)
            clip_src_end = clip_src_start + (overlap_end - overlap_start)

            src_start_idx = max(0, int(round(clip_src_start * sample_rate)))
            src_end_idx = min(audio_arr.shape[0], int(round(clip_src_end * sample_rate)))
            if src_start_idx >= src_end_idx:
                continue

            src_chunk = audio_arr[src_start_idx:src_end_idx]

            dst_start_idx = max(0, int(round((overlap_start - start_time) * sample_rate)))
            dst_end_idx = min(total_samples, dst_start_idx + src_chunk.shape[0])

            chunk_len = dst_end_idx - dst_start_idx
            if chunk_len > 0:
                composite[dst_start_idx:dst_end_idx] += src_chunk[:chunk_len]

        np.clip(composite, -1.0, 1.0, out=composite)
        pcm16 = (composite * 32767.0).astype(np.int16)
        return pcm16.tobytes()

    def close(self):
        """Release all open video file handles and empty frame & audio caches."""
        with self._lock:
            for path, media in list(self._loaded_media.items()):
                try:
                    media.close()
                except Exception:
                    pass
            self._loaded_media.clear()
            self._metadata_cache.clear()
            self._frame_cache.clear()
            self._audio_cache.clear()

