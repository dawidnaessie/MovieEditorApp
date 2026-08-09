"""Pure mathematical unit tests for timeline spatial conversions and playhead clamping."""

import pytest
from ui.timeline_view import (
    PIXELS_PER_SECOND,
    calculate_clip_pixel_width,
    pixel_to_time,
    time_to_pixel,
)


def test_time_to_pixel():
    """Validates converting timeline seconds to canvas X coordinate."""
    header_w = 130
    pps = 25.0

    # 0.0s -> header_width (130)
    assert time_to_pixel(0.0, header_width=header_w, pixels_per_second=pps) == 130

    # 4.0s -> 130 + (4 * 25) = 230
    assert time_to_pixel(4.0, header_width=header_w, pixels_per_second=pps) == 230

    # Negative time -> clamped to 0s (130)
    assert time_to_pixel(-5.0, header_width=header_w, pixels_per_second=pps) == 130


def test_pixel_to_time_unclamped_and_clamped():
    """Validates converting canvas X coordinate back to timeline seconds."""
    header_w = 130
    pps = 25.0

    # X at header edge -> 0.0s
    assert pixel_to_time(130, header_width=header_w, pixels_per_second=pps) == 0.0

    # X inside header (< 130) -> 0.0s
    assert pixel_to_time(50, header_width=header_w, pixels_per_second=pps) == 0.0

    # X at 230 -> (230 - 130) / 25 = 4.0s
    assert pixel_to_time(230, header_width=header_w, pixels_per_second=pps) == 4.0

    # X with max_duration clamping (max 10.0s, X at 500 -> 14.8s clamped to 10.0s)
    assert pixel_to_time(500, header_width=header_w, pixels_per_second=pps, max_duration=10.0) == 10.0


def test_calculate_clip_pixel_width():
    """Validates clip width calculation and minimum width safety."""
    pps = 25.0
    min_w = 60

    # 10.0s duration -> 250px
    assert calculate_clip_pixel_width(10.0, pixels_per_second=pps, min_width=min_w) == 250

    # 0.5s duration -> 12.5px, enforced min_width 60px
    assert calculate_clip_pixel_width(0.5, pixels_per_second=pps, min_width=min_w) == 60

    # 0.0s duration -> enforced min_width 60px
    assert calculate_clip_pixel_width(0.0, pixels_per_second=pps, min_width=min_w) == 60
