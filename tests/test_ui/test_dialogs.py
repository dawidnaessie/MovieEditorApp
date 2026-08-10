"""Unit tests for UI dialog components including SetTimeDialog."""

import os
import sys
import pytest
from PyQt6.QtWidgets import QApplication

from ui.dialogs import SetTimeDialog


@pytest.fixture(scope="session")
def qapp():
    """Provides or initializes a persistent QApplication instance."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


def test_set_time_dialog_initialization_and_prefill(qapp):
    """Validates SetTimeDialog initializes and pre-fills spinboxes with provided start/end values."""
    dialog = SetTimeDialog(start_time=2.5, end_time=14.8)
    dialog.show()
    assert dialog.spin_start.value() == 2.5
    assert dialog.spin_end.value() == 14.8
    assert dialog.start_time == 2.5
    assert dialog.end_time == 14.8
    assert dialog.get_times() == (2.5, 14.8)
    assert "12.30 seconds" in dialog.lbl_duration_info.text()
    assert dialog.lbl_error.isHidden() is True
    dialog.close()


def test_set_time_dialog_accept_and_modify(qapp):
    """Validates modifying spinbox values and accepting dialog returns updated times."""
    dialog = SetTimeDialog(start_time=0.0, end_time=10.0)
    dialog.show()
    dialog.spin_start.setValue(4.0)
    dialog.spin_end.setValue(18.25)
    assert dialog.get_times() == (4.0, 18.25)
    assert "14.25 seconds" in dialog.lbl_duration_info.text()

    # Simulate accept
    dialog.accept()
    assert dialog.result() == 1  # QDialog.DialogCode.Accepted
    assert dialog.lbl_error.isHidden() is True
    dialog.close()


def test_set_time_dialog_validation_end_less_than_start(qapp):
    """Validates dialog prevents acceptance and shows error banner when end <= start."""
    dialog = SetTimeDialog(start_time=10.0, end_time=5.0)
    dialog.show()
    assert "Invalid range" in dialog.lbl_duration_info.text()

    # Attempt to accept with invalid range
    dialog.accept()
    assert dialog.result() == 0  # Did not accept
    assert dialog.lbl_error.isHidden() is False
    assert "strictly greater than start time" in dialog.lbl_error.text()

    # Fix values
    dialog.spin_end.setValue(15.0)
    assert dialog.lbl_error.isHidden() is True  # Clears on value change

    dialog.accept()
    assert dialog.result() == 1
    dialog.close()


def test_set_time_dialog_validation_equal_times(qapp):
    """Validates dialog prevents acceptance when start == end."""
    dialog = SetTimeDialog(start_time=5.0, end_time=5.0)
    dialog.show()
    dialog.accept()
    assert dialog.result() == 0
    assert dialog.lbl_error.isHidden() is False
    dialog.close()
