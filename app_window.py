import sys

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from config import (
    BACK_FRAME_OFFSET_COUNT,
    LUMINANCE_THRESHOLD_PCT,
    OUTPUT_FILE,
    SHOW_LUMINANCE_DEFAULT,
)
from persistence import save_regions
from video_widget import VideoWidget


class App(QWidget):
    def __init__(self):
        super().__init__()
        self._is_closing = False

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
        self.next_btn = QPushButton("Next")
        self.next_btn.clicked.connect(self.save_and_exit)

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

    def save_and_exit(self):
        data = self.video.get_regions_pct()
        save_regions(OUTPUT_FILE, data)
        print("Saved:", data)
        self.close()

    def closeEvent(self, event):
        if not self._is_closing:
            self._is_closing = True
            self.video.cleanup()
        super().closeEvent(event)
