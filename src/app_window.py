import sys
from pathlib import Path

from PyQt5.QtCore import QObject, QThread, QTimer, Qt, pyqtSignal, pyqtSlot
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.config import (
    BACK_FRAME_OFFSET_COUNT,
    LUMINANCE_THRESHOLD_PCT,
    OUTPUT_FILE,
    SHOW_LUMINANCE_DEFAULT,
    TIMELAPSE_LENGTH_SECONDS,
    TIMELAPSE_OUTPUT_FILE,
    TIMELAPSE_PREVIEW_INTERVAL_MS,
)
from src.persistence import save_regions
from src.video_widget import VideoWidget


class TimelapseWorker(QObject):
    progress = pyqtSignal(float, int)
    finished = pyqtSignal(int, str)
    no_matches = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, builder, length_seconds, output_path):
        super().__init__()
        self.builder = builder
        self.length_seconds = length_seconds
        self.output_path = output_path

    @pyqtSlot()
    def run(self):
        try:
            frame_count, output_path = self.builder.create_timelapse(
                self.length_seconds,
                self.output_path,
                progress_callback=self.progress.emit,
            )
        except RuntimeError as error:
            self.failed.emit(str(error))
            return

        if frame_count == 0:
            self.no_matches.emit()
            return

        self.finished.emit(frame_count, str(output_path))


class App(QWidget):
    def __init__(self):
        super().__init__()
        self._is_closing = False
        self.timelapse_thread = None
        self.timelapse_worker = None
        self.pending_preview_progress_pct = None
        self.pending_preview_frame_index = None

        self.setWindowTitle("Fuselapse")
        self.setFocusPolicy(Qt.StrongFocus)

        video_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select video",
            "",
            "Video Files (*.mp4 *.mov *.avi *.mkv)",
        )
        if not video_path:
            sys.exit(0)

        self.video = VideoWidget(video_path)
        self.slider = self._build_slider()
        self.frame_label = QLabel()
        self.keyboard_help_label = QLabel("a/d shift 1 frame; A/D shift 10 frames")
        self.previous_match_btn = QPushButton("<< previous match")
        self.previous_match_btn.clicked.connect(self.go_to_previous_match)
        self.next_match_btn = QPushButton(">> next match")
        self.next_match_btn.clicked.connect(self.go_to_next_match)
        self.previous_offset_match_btn = QPushButton("<< previous offset match")
        self.previous_offset_match_btn.clicked.connect(self.go_to_previous_offset_match)
        self.next_offset_match_btn = QPushButton(">> next offset match")
        self.next_offset_match_btn.clicked.connect(self.go_to_next_offset_match)
        self.display_percentage_checkbox = self._build_luminance_checkbox()
        self.threshold_input = self._build_threshold_input()
        self.back_frame_offset_input = self._build_back_frame_offset_input()
        self.timelapse_length_input = self._build_timelapse_length_input()
        self.next_btn = QPushButton("Create Timelapse")
        self.next_btn.clicked.connect(self.create_timelapse)
        self.preview_timer = QTimer(self)
        self.preview_timer.setInterval(TIMELAPSE_PREVIEW_INTERVAL_MS)
        self.preview_timer.timeout.connect(self._flush_preview_progress)

        self._build_layout()
        self.update_frame_label()
        self.adjustSize()

    def _build_slider(self):
        slider = QSlider(Qt.Horizontal)
        slider.setMinimum(0)
        slider.setMaximum(self.video.total_frames - 1)
        slider.valueChanged.connect(self.on_slider_change)
        slider.setFocus()
        return slider

    def _build_luminance_checkbox(self):
        checkbox = QCheckBox("Display percentage")
        checkbox.setChecked(SHOW_LUMINANCE_DEFAULT)
        checkbox.toggled.connect(self.video.set_show_luminance)
        return checkbox

    def _build_threshold_input(self):
        spin_box = QSpinBox()
        spin_box.setRange(0, 100)
        spin_box.setValue(LUMINANCE_THRESHOLD_PCT)
        spin_box.setButtonSymbols(QSpinBox.NoButtons)
        spin_box.setFocusPolicy(Qt.ClickFocus)
        spin_box.setStyleSheet(
            """
            QSpinBox {
                border: 1px solid #666;
                background: #fff;
                color: #111;
                padding: 2px 2px;
            }
            """
        )
        spin_box.valueChanged.connect(self.video.set_luminance_threshold_pct)
        return spin_box

    def _build_back_frame_offset_input(self):
        spin_box = QSpinBox()
        spin_box.setRange(0, max(0, self.video.total_frames - 1))
        spin_box.setValue(BACK_FRAME_OFFSET_COUNT)
        spin_box.setButtonSymbols(QSpinBox.NoButtons)
        spin_box.setFocusPolicy(Qt.ClickFocus)
        spin_box.setStyleSheet(
            """
            QSpinBox {
                border: 1px solid #666;
                background: #fff;
                color: #111;
                padding: 2px 2px;
            }
            """
        )
        spin_box.valueChanged.connect(self.video.set_back_frame_offset_count)
        return spin_box

    def _build_timelapse_length_input(self):
        spin_box = QDoubleSpinBox()
        spin_box.setRange(0.1, 3600.0)
        spin_box.setDecimals(1)
        spin_box.setSingleStep(1.0)
        spin_box.setValue(TIMELAPSE_LENGTH_SECONDS)
        spin_box.setButtonSymbols(QSpinBox.NoButtons)
        spin_box.setFocusPolicy(Qt.ClickFocus)
        spin_box.setStyleSheet(
            """
            QDoubleSpinBox {
                border: 1px solid #666;
                background: #fff;
                color: #111;
                padding: 2px 2px;
            }
            """
        )
        return spin_box

    def _build_layout(self):
        slider_row = QHBoxLayout()
        slider_row.addWidget(self.slider)
        slider_row.addWidget(self.frame_label)

        help_row = QHBoxLayout()
        help_row.addWidget(self.keyboard_help_label)
        help_row.addStretch()
        help_row.addWidget(self.previous_match_btn)
        help_row.addWidget(self.next_match_btn)

        offset_row = QHBoxLayout()
        offset_row.addWidget(QLabel("Back frame offset count"))
        offset_row.addWidget(self.back_frame_offset_input)
        offset_row.addStretch()
        offset_row.addWidget(self.previous_offset_match_btn)
        offset_row.addWidget(self.next_offset_match_btn)

        controls_row = QHBoxLayout()
        controls_row.addWidget(self.display_percentage_checkbox)
        controls_row.addSpacing(30)
        controls_row.addWidget(QLabel("Threshold %"))
        controls_row.addWidget(self.threshold_input)
        controls_row.addStretch()
        controls_row.setSpacing(6)

        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setFrameShadow(QFrame.Sunken)

        layout = QVBoxLayout()
        layout.addWidget(self.video)
        layout.addLayout(slider_row)
        layout.addLayout(help_row)
        layout.addLayout(offset_row)
        layout.addLayout(controls_row)
        layout.addWidget(divider)
        timelapse_row = QHBoxLayout()
        timelapse_row.addWidget(QLabel("Timelapse length (s)"))
        timelapse_row.addWidget(self.timelapse_length_input)
        timelapse_row.addStretch()
        layout.addLayout(timelapse_row)
        layout.addWidget(self.next_btn)
        self.setLayout(layout)

    def step_frames(self, amount):
        next_frame = self.video.current_frame + amount
        self.video.set_frame(next_frame)

        self.slider.blockSignals(True)
        self.slider.setValue(self.video.current_frame)
        self.slider.blockSignals(False)

        self.update_frame_label()

    def on_slider_change(self, value):
        self.video.set_frame(value)
        self.update_frame_label()

    def jump_to_frame(self, frame_index):
        self.video.set_frame(frame_index)
        self.slider.blockSignals(True)
        self.slider.setValue(self.video.current_frame)
        self.slider.blockSignals(False)
        self.update_frame_label()

    def go_to_next_match(self):
        frame_index = self.video.find_matching_frame(1)
        if frame_index is not None:
            self.jump_to_frame(frame_index)

    def go_to_previous_match(self):
        frame_index = self.video.find_matching_frame(-1)
        if frame_index is not None:
            self.jump_to_frame(frame_index)

    def go_to_offset_match(self, direction):
        start_frame = min(
            self.video.current_frame + self.video.back_frame_offset_count,
            self.video.total_frames - 1,
        )
        frame_index = self.video.find_matching_frame(direction, start_frame=start_frame)
        if frame_index is None:
            return

        self.jump_to_frame(frame_index - self.video.back_frame_offset_count)

    def go_to_next_offset_match(self):
        self.go_to_offset_match(1)

    def go_to_previous_offset_match(self):
        self.go_to_offset_match(-1)

    def update_frame_label(self):
        self.frame_label.setText(
            f"{self.video.current_frame} / {self.video.total_frames - 1}"
        )

    def keyPressEvent(self, event):
        key = event.key()
        modifiers = event.modifiers()

        if key == Qt.Key_A:
            self.step_frames(-10 if modifiers & Qt.ShiftModifier else -1)
        elif key == Qt.Key_D:
            self.step_frames(10 if modifiers & Qt.ShiftModifier else 1)
        elif key == Qt.Key_Q:
            self.close()

    def create_timelapse(self):
        data = self.video.get_regions_pct()
        default_output_path = str(
            Path(self.video.video_path).with_name(TIMELAPSE_OUTPUT_FILE)
        )
        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Timelapse",
            default_output_path,
            "MP4 Video (*.mp4);;All Files (*)",
        )
        if not output_path:
            return

        if "." not in output_path.rsplit("/", 1)[-1]:
            output_path = f"{output_path}.mp4"

        save_regions(OUTPUT_FILE, data)
        self._set_timelapse_running(True)
        self.next_btn.setText("Create Timelapse (0%)")
        self.pending_preview_progress_pct = 0.0
        self.pending_preview_frame_index = self.video.current_frame
        self.video.set_progress_preview_enabled(True)
        self.preview_timer.start()

        self.timelapse_thread = QThread(self)
        self.timelapse_worker = TimelapseWorker(
            self.video.build_timelapse_builder(),
            self.timelapse_length_input.value(),
            output_path,
        )
        self.timelapse_worker.moveToThread(self.timelapse_thread)
        self.timelapse_thread.started.connect(self.timelapse_worker.run)
        self.timelapse_worker.progress.connect(self._update_timelapse_progress)
        self.timelapse_worker.finished.connect(self._on_timelapse_finished)
        self.timelapse_worker.no_matches.connect(self._on_timelapse_no_matches)
        self.timelapse_worker.failed.connect(self._on_timelapse_failed)
        self.timelapse_worker.finished.connect(self.timelapse_thread.quit)
        self.timelapse_worker.no_matches.connect(self.timelapse_thread.quit)
        self.timelapse_worker.failed.connect(self.timelapse_thread.quit)
        self.timelapse_thread.finished.connect(self._cleanup_timelapse_worker)
        self.timelapse_thread.start()

    def _set_timelapse_running(self, is_running):
        self.next_btn.setEnabled(not is_running)
        self.slider.setEnabled(not is_running)
        self.previous_match_btn.setEnabled(not is_running)
        self.next_match_btn.setEnabled(not is_running)
        self.previous_offset_match_btn.setEnabled(not is_running)
        self.next_offset_match_btn.setEnabled(not is_running)
        self.display_percentage_checkbox.setEnabled(not is_running)
        self.threshold_input.setEnabled(not is_running)
        self.back_frame_offset_input.setEnabled(not is_running)
        self.timelapse_length_input.setEnabled(not is_running)

    def _reset_timelapse_button(self):
        self.next_btn.setEnabled(True)
        self.next_btn.setText("Create Timelapse")

    def _finish_timelapse_ui(self):
        self._set_timelapse_running(False)
        self._reset_timelapse_button()
        self.preview_timer.stop()
        self.pending_preview_progress_pct = None
        self.pending_preview_frame_index = None
        self.video.set_progress_preview_enabled(False)

    def _cleanup_timelapse_worker(self):
        if self.timelapse_worker is not None:
            self.timelapse_worker.deleteLater()
            self.timelapse_worker = None
        if self.timelapse_thread is not None:
            self.timelapse_thread.deleteLater()
            self.timelapse_thread = None

    def _update_timelapse_progress(self, progress_pct, preview_frame_index):
        self.next_btn.setText(f"Create Timelapse ({progress_pct:.1f}%)")
        self.pending_preview_progress_pct = progress_pct
        if preview_frame_index >= 0:
            self.pending_preview_frame_index = preview_frame_index

    def _flush_preview_progress(self):
        if self.pending_preview_frame_index is None:
            return

        if self.video.show_preview_frame(self.pending_preview_frame_index):
            self.slider.blockSignals(True)
            self.slider.setValue(self.video.current_frame)
            self.slider.blockSignals(False)
            self.update_frame_label()

    def _on_timelapse_finished(self, frame_count, output_path):
        self._finish_timelapse_ui()
        QMessageBox.information(
            self,
            "Timelapse Created",
            f"Created timelapse with {frame_count} frames:\n{output_path}",
        )

    def _on_timelapse_no_matches(self):
        self._finish_timelapse_ui()
        QMessageBox.warning(
            self,
            "No Offset Matches",
            "No offset match frames were found from the current frame onward.",
        )

    def _on_timelapse_failed(self, message):
        self._finish_timelapse_ui()
        QMessageBox.critical(
            self,
            "Timelapse Creation Failed",
            message,
        )

    def closeEvent(self, event):
        if self.timelapse_thread is not None and self.timelapse_thread.isRunning():
            QMessageBox.information(
                self,
                "Timelapse In Progress",
                "Please wait for the timelapse to finish before closing the window.",
            )
            event.ignore()
            return

        if not self._is_closing:
            self._is_closing = True
            self.video.cleanup()
        super().closeEvent(event)
