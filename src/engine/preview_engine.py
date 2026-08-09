from collections import OrderedDict
import os
import threading
from typing import Any, Dict, List, Optional, Tuple
import warnings
import numpy as np
from PIL import Image
from moviepy import VideoFileClip

from models.clip import Clip
from models.project import Project


class PreviewEngine:
    """High-performance backend engine for decoding video frames and mixing multi-track audio.

    PreviewEngine performs on-demand extraction of RGB video frames and 16-bit PCM audio,
    utilizing thread-safe LRU caching and isolated readers so UI scrubbing and playback
    remain fast, smooth, and freeze-free. Strictly contains zero UI dependencies.

    Attributes:
        _loaded_media (Dict[str, VideoFileClip]): Cache of open MoviePy VideoFileClip handles.
        _metadata_cache (Dict[str, Dict[str, Any]]): Cache of video duration, framerate, and size.
        _frame_cache (OrderedDict[Tuple[str, int], np.ndarray]): LRU frame cache keyed by (file_path, quant_time).
        _audio_cache (Dict[str, Optional[np.ndarray]]): Cache of decoded float32 audio sound arrays.
        _cache_size (int): Maximum number of decoded RGB frames retained in the LRU cache.
        _lock (threading.Lock): Mutex ensuring thread-safe access to MoviePy readers and caches.
    """

    def __init__(self, cache_size: int = 120):
        """Initializes the PreviewEngine with configurable LRU cache capacity.

        Args:
            cache_size (int): Maximum frames to store in the decoded LRU cache (min 30). Defaults to 120.
        """
        self._loaded_media: Dict[str, VideoFileClip] = {}
        self._metadata_cache: Dict[str, Dict[str, Any]] = {}
        self._frame_cache: OrderedDict[Tuple[str, int], np.ndarray] = OrderedDict()
        self._audio_cache: Dict[str, Optional[np.ndarray]] = {}
        self._cache_size: int = max(30, int(cache_size))
        self._lock: threading.Lock = threading.Lock()

    def _get_media(self, file_path: str) -> Optional[VideoFileClip]:
        """Thread-safely gets or opens a VideoFileClip for the given filesystem path.

        Args:
            file_path (str): Filesystem path to the video file.

        Returns:
            Optional[VideoFileClip]: Open VideoFileClip instance or None if missing/corrupt.
        """
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
        """Queries metadata for a media file (duration, fps, size).

        Args:
            file_path (str): Filesystem path to the media file.

        Returns:
            Dict[str, Any]: Dictionary containing 'duration' (float in seconds),
                'fps' (float framerate), and 'size' ([width, height] in pixels).
        """
        if file_path in self._metadata_cache:
            return self._metadata_cache[file_path]

        # Handle static image files directly via PIL
        from models.clip import detect_media_type
        if detect_media_type(file_path) == "image" and os.path.exists(file_path):
            try:
                with Image.open(file_path) as img:
                    w, h = img.size
                    info = {"duration": 5.0, "fps": 30.0, "size": [w, h]}
                    self._metadata_cache[file_path] = info
                    return info
            except Exception as e:
                print(f"Engine Warning: Failed to read image metadata for {file_path}: {e}")

        media = self._get_media(file_path)
        if media:
            return self._metadata_cache.get(file_path, {
                "duration": float(getattr(media, "duration", 0.0)),
                "fps": float(getattr(media, "fps", 30.0)),
                "size": getattr(media, "size", [1920, 1080]),
            })
        return {"duration": 10.0, "fps": 30.0, "size": [1920, 1080]}

    def get_media_duration(self, file_path: str) -> float:
        """Returns the media duration in seconds for a video/audio file.

        Args:
            file_path (str): Filesystem path to the media file.

        Returns:
            float: Duration in seconds (defaults to 10.0 if file is inaccessible).
        """
        info = self.get_media_info(file_path)
        return float(info.get("duration", 10.0))

    def get_frame(self, clip: Clip, time_in_seconds: float) -> np.ndarray:
        """Decodes and returns a single frame for a Clip at a local timestamp.

        Utilizes an LRU memory cache to ensure repeated playback and scrubbing are instantaneous.
        Returns a solid black frame if the file is missing, broken, or empty.

        Args:
            clip (Clip): Clip model instance specifying media source and cut boundaries.
            time_in_seconds (float): Local timestamp in seconds relative to the start of the clip.

        Returns:
            np.ndarray: C-contiguous RGB array of shape (H, W, 3) with dtype uint8.
        """
        if not clip.file_path or not os.path.exists(clip.file_path):
            return np.zeros((1080, 1920, 3), dtype=np.uint8)

        # 1. Handle static images (return identical image regardless of timestamp)
        from models.clip import detect_media_type
        if clip.is_image or detect_media_type(clip.file_path) == "image":
            cache_key = (clip.file_path, 0)
            with self._lock:
                if cache_key in self._frame_cache:
                    frame = self._frame_cache[cache_key]
                    self._frame_cache.move_to_end(cache_key)
                    return frame

            try:
                with Image.open(clip.file_path) as img:
                    img_rgb = img.convert("RGB")
                    raw_frame = np.array(img_rgb, dtype=np.uint8)
                    with self._lock:
                        if len(self._frame_cache) >= self._cache_size:
                            self._frame_cache.popitem(last=False)
                        self._frame_cache[cache_key] = raw_frame
                    return raw_frame
            except Exception as e:
                print(f"Engine Warning: Failed to load image frame from {clip.file_path}: {e}")
                return np.zeros((1080, 1920, 3), dtype=np.uint8)

        # 2. Handle video stream decoding
        media = self._get_media(clip.file_path)
        if media is None:
            return np.zeros((1080, 1920, 3), dtype=np.uint8)

        actual_media_time = clip.source_start + time_in_seconds
        media_duration = float(getattr(media, "duration", 0.0) or 0.0)
        media_fps = float(getattr(media, "fps", 30.0) or 30.0)
        end_buffer = max(0.08, 2.0 / max(1.0, media_fps))
        max_safe_time = max(0.0, media_duration - end_buffer) if media_duration > 0.2 else media_duration
        safe_time = max(0.0, min(actual_media_time, max_safe_time))

        cache_key = (clip.file_path, int(round(safe_time * 100)))

        with self._lock:
            if cache_key in self._frame_cache:
                frame = self._frame_cache[cache_key]
                self._frame_cache.move_to_end(cache_key)
                return frame

        try:
            with self._lock:
                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore", category=UserWarning, module="moviepy")
                    raw_frame = media.get_frame(safe_time)

                if not isinstance(raw_frame, np.ndarray) or raw_frame.dtype != np.uint8:
                    raw_frame = np.ascontiguousarray(raw_frame, dtype=np.uint8)

                if len(self._frame_cache) >= self._cache_size:
                    self._frame_cache.popitem(last=False)
                self._frame_cache[cache_key] = raw_frame

            return raw_frame
        except Exception as e:
            print(f"Engine Warning: Failed to extract frame at {safe_time:.2f}s from {clip.file_path}: {e}")
            width, height = getattr(media, "size", (1920, 1080))
            return np.zeros((height, width, 3), dtype=np.uint8)

    def get_project_frame(self, project: Project, global_time: float) -> np.ndarray:
        """Extracts the composite frame at a master timeline timestamp across all tracks.

        Resolves top-down visual layering: finds the active top-most video clip and extracts its frame.
        If the playhead is over an empty gap, returns a solid black frame.

        Args:
            project (Project): Project model containing tracks and clip arrangement.
            global_time (float): Timeline timestamp in seconds.

        Returns:
            np.ndarray: C-contiguous RGB array of shape (H, W, 3) with dtype uint8.
        """
        match = project.find_clip_at(global_time)
        if match is not None:
            _, clip, local_time = match
            return self.get_frame(clip, local_time)

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
        """Extracts a sequence of thumbnail frames spanning the clip duration.

        Uses an isolated VideoFileClip instance to ensure thread safety without interfering
        with active playback decoders.

        Args:
            file_path (str): Filesystem path to the video file.
            source_start (float): Clip cut in-point timestamp in seconds. Defaults to 0.0.
            duration (float): Length of the clip segment in seconds. Defaults to 10.0.
            count (int): Number of thumbnail sample frames to extract. Defaults to 6.
            thumb_height (int): Target height in pixels for the generated thumbnails. Defaults to 36.

        Returns:
            List[np.ndarray]: List of thumbnail images as RGB numpy arrays of shape (thumb_height, thumb_width, 3).
        """
        thumbnails: List[np.ndarray] = []
        if not file_path or not os.path.exists(file_path) or duration <= 0:
            return thumbnails

        # Fast static image thumbnail extraction
        from models.clip import detect_media_type
        if detect_media_type(file_path) == "image":
            try:
                with Image.open(file_path) as img:
                    img_rgb = img.convert("RGB")
                    w, h = img_rgb.size
                    aspect = w / max(1, h)
                    thumb_w = max(16, int(thumb_height * aspect))
                    thumb_img = img_rgb.resize((thumb_w, thumb_height), Image.Resampling.BILINEAR)
                    thumb_arr = np.array(thumb_img, dtype=np.uint8)
                    return [thumb_arr] * max(1, min(count, 30))
            except Exception as e:
                print(f"Engine Warning: Failed to extract image thumbnail for {file_path}: {e}")
                return []

        isolated_clip: Optional[VideoFileClip] = None
        try:
            isolated_clip = VideoFileClip(file_path)
            media_duration = float(getattr(isolated_clip, "duration", 0.0) or duration)
            media_fps = float(getattr(isolated_clip, "fps", 30.0) or 30.0)
            end_buffer = max(0.08, 2.0 / max(1.0, media_fps))
            max_safe_time = max(0.0, media_duration - end_buffer) if media_duration > 0.2 else media_duration

            effective_duration = min(duration, max_safe_time - source_start)
            if effective_duration <= 0:
                effective_duration = min(duration, media_duration)

            count = max(1, min(count, 30))
            time_points = [
                source_start + (i + 0.5) * (effective_duration / count)
                for i in range(count)
            ]

            for t in time_points:
                safe_t = max(0.0, min(t, max_safe_time))
                try:
                    with warnings.catch_warnings():
                        warnings.filterwarnings("ignore", category=UserWarning, module="moviepy")
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
        """Formats a timestamp in seconds into standard NLE SMPTE timecode (HH:MM:SS:FF).

        Args:
            seconds (float): Timestamp in seconds.
            fps (float): Frame rate used to calculate frame numbers. Defaults to 30.0.

        Returns:
            str: SMPTE timecode string formatted as 'HH:MM:SS:FF'.
        """
        safe_secs = max(0.0, float(seconds))
        safe_fps = max(1.0, float(fps))
        total_frames = int(round(safe_secs * safe_fps))

        frames = int(total_frames % int(safe_fps))
        total_seconds = int(safe_secs)
        secs = total_seconds % 60
        mins = (total_seconds // 60) % 60
        hours = total_seconds // 3600

        return f"{hours:02d}:{mins:02d}:{secs:02d}:{frames:02d}"

    def get_playback_status(self, project: Project, global_time: float) -> Dict[str, Any]:
        """Calculates rich playback state metadata for UI timecodes and status indicators.

        Args:
            project (Project): Project data model containing tracks and clip arrangement.
            global_time (float): Current playback timestamp in seconds.

        Returns:
            Dict[str, Any]: Dictionary containing:
                - 'has_active_clip' (bool): True if playhead is currently over a video clip.
                - 'clip_name' (str): Name of active clip or 'No Active Clip'.
                - 'file_path' (str): Media path of active clip.
                - 'track_name' (str): Track layer name of active clip.
                - 'local_time' (float): Time offset inside the active clip.
                - 'global_time' (float): Master timeline timestamp.
                - 'clip_duration' (float): Active clip duration in seconds.
                - 'clip_frame' (int): Local frame index within active clip.
                - 'total_clip_frames' (int): Total frame count of active clip.
                - 'current_frame' (int): Master timeline frame index.
                - 'total_frames' (int): Total frame count of entire project.
                - 'timecode' (str): Formatted SMPTE timecode 'HH:MM:SS:FF'.
                - 'fps' (float): Master framerate.
                - 'resolution' (Tuple[int, int]): Project canvas resolution.
                - 'project_duration' (float): Master project duration in seconds.
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
        """Extracts and caches the full 2-channel float32 audio soundarray of a media file.

        Args:
            file_path (str): Filesystem path to the media file.
            sample_rate (int): Audio sampling rate in Hz. Defaults to 44100.

        Returns:
            Optional[np.ndarray]: Float32 NumPy array of shape (num_samples, 2)
                with normalized sample values in [-1.0, 1.0], or None if no audio exists.
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
        """Extracts and mixes audio samples across all tracks for a time window.

        Mixes multi-track audio layers into 16-bit signed integer little-endian stereo PCM bytes.

        Args:
            project (Project): Project model containing tracks and clip arrangement.
            start_time (float): Start timestamp in seconds on the master timeline.
            duration (float): Time window duration in seconds.
            sample_rate (int): Sampling rate in Hz. Defaults to 44100.

        Returns:
            bytes: Standard 16-bit 44.1kHz stereo signed little-endian PCM byte string.
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

    def close(self) -> None:
        """Releases all open video file handles and flushes memory caches."""
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

