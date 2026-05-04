import sys
import json
import cv2

from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QFileDialog,
    QSlider,
    QLabel,
)
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QImage, QPainter, QColor, QPen


# ===== CONFIG =====
CHECK_REGIONS = [
    {"x_pct": 0.1006, "y_pct": 0.8083, "label": "positive"},  # positive check
    {"x_pct": 0.8648, "y_pct": 0.8004, "label": "positive"},  # positive check
    {"x_pct": 0.2264, "y_pct": 0.8617, "label": "negative"},  # negative check
    {"x_pct": 0.7170, "y_pct": 0.8696, "label": "negative"},  # negative check
]

BOX_SIZE = 40
OUTPUT_FILE = "regions.json"
MAX_SCREEN_RATIO = 0.82
LUMINANCE_THRESHOLD_PCT = 15
DEBUG_LUMINANCE = "--debug-luminance" in sys.argv


class VideoWidget(QWidget):
    def __init__(self, video_path):
        super().__init__()

        self.cap = cv2.VideoCapture(video_path)
        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))

        ret, frame = self.cap.read()
        if not ret:
            sys.exit(1)

        self.frame = frame
        self.video_h, self.video_w = frame.shape[:2]

        screen = QApplication.primaryScreen().availableGeometry()
        max_w = int(screen.width() * MAX_SCREEN_RATIO)
        max_h = int(screen.height() * MAX_SCREEN_RATIO)

        self.scale = min(max_w / self.video_w, max_h / self.video_h, 1.0)

        self.display_w = int(self.video_w * self.scale)
        self.display_h = int(self.video_h * self.scale)

        self.setFixedSize(QSize(self.display_w, self.display_h))

        self.regions = [
            {
                "x": int(r["x_pct"] * self.video_w),
                "y": int(r["y_pct"] * self.video_h),
                "label": r["label"],
            }
            for r in CHECK_REGIONS
        ]

        self.current_frame = 0
        self.dragging_idx = None

    def get_region_bounds(self, region):
        x1 = max(0, min(self.video_w, region["x"]))
        y1 = max(0, min(self.video_h, region["y"]))
        x2 = max(0, min(self.video_w, region["x"] + BOX_SIZE))
        y2 = max(0, min(self.video_h, region["y"] + BOX_SIZE))
        return x1, y1, x2, y2

    def get_region_luminance_pct(self, region):
        x1, y1, x2, y2 = self.get_region_bounds(region)
        if x2 <= x1 or y2 <= y1:
            return 0

        roi = self.frame[y1:y2, x1:x2]
        avg_bgr = roi.mean(axis=(0, 1))
        avg_rgb = QColor(
            int(avg_bgr[2]),
            int(avg_bgr[1]),
            int(avg_bgr[0]),
        )
        return round(avg_rgb.lightnessF() * 100)

    def set_frame(self, frame_index):
        self.current_frame = max(0, min(self.total_frames - 1, frame_index))
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, self.current_frame)

        ret, frame = self.cap.read()
        if ret:
            self.frame = frame

        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)

        rgb = cv2.cvtColor(self.frame, cv2.COLOR_BGR2RGB)

        img = QImage(
            rgb.data,
            self.video_w,
            self.video_h,
            rgb.strides[0],
            QImage.Format_RGB888,
        )

        painter.drawImage(
            0,
            0,
            img.scaled(
                self.display_w,
                self.display_h,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            ),
        )

        for r in self.regions:
            color = QColor(0, 255, 0) if r["label"] == "positive" else QColor(255, 0, 0)
            painter.setPen(QPen(color, 2))

            draw_x = int(r["x"] * self.scale)
            draw_y = int(r["y"] * self.scale)
            draw_size = int(BOX_SIZE * self.scale)
            luminance_pct = self.get_region_luminance_pct(r)

            if luminance_pct < LUMINANCE_THRESHOLD_PCT:
                fill_color = QColor(color)
                fill_color.setAlphaF(0.5)
                painter.fillRect(draw_x, draw_y, draw_size, draw_size, fill_color)

            painter.drawRect(draw_x, draw_y, draw_size, draw_size)

            if DEBUG_LUMINANCE:
                text_rect = img.rect()
                text_rect.setX(draw_x)
                text_rect.setY(draw_y)
                text_rect.setWidth(draw_size)
                text_rect.setHeight(draw_size)

                painter.fillRect(text_rect, QColor(0, 0, 0, 200))
                painter.setPen(QPen(QColor(255, 255, 255)))
                painter.drawText(text_rect, Qt.AlignCenter, f"{luminance_pct}%")

    def mousePressEvent(self, event):
        x = int(event.x() / self.scale)
        y = int(event.y() / self.scale)

        for i, r in enumerate(self.regions):
            if r["x"] <= x <= r["x"] + BOX_SIZE and r["y"] <= y <= r["y"] + BOX_SIZE:
                self.dragging_idx = i
                return

    def mouseMoveEvent(self, event):
        if self.dragging_idx is not None:
            x = int(event.x() / self.scale)
            y = int(event.y() / self.scale)

            self.regions[self.dragging_idx]["x"] = x - BOX_SIZE // 2
            self.regions[self.dragging_idx]["y"] = y - BOX_SIZE // 2

            self.update()

    def mouseReleaseEvent(self, event):
        self.dragging_idx = None

    def get_regions_pct(self):
        return [
            {
                "x_pct": round(r["x"] / self.video_w, 4),
                "y_pct": round(r["y"] / self.video_h, 4),
                "label": r["label"],
            }
            for r in self.regions
        ]


class App(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Video Tool")
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

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setMinimum(0)
        self.slider.setMaximum(self.video.total_frames - 1)
        self.slider.valueChanged.connect(self.on_slider_change)

        self.frame_label = QLabel()
        self.update_frame_label()

        slider_row = QHBoxLayout()
        slider_row.addWidget(self.slider)
        slider_row.addWidget(self.frame_label)

        self.next_btn = QPushButton("Next")
        self.next_btn.clicked.connect(self.save_and_exit)

        layout = QVBoxLayout()
        layout.addWidget(self.video)
        layout.addLayout(slider_row)
        layout.addWidget(self.next_btn)

        self.setLayout(layout)
        self.adjustSize()

    def step_frames(self, amount):
        next_frame = self.video.current_frame + amount
        self.video.set_frame(next_frame)

        self.slider.blockSignals(True)
        self.slider.setValue(self.video.current_frame)
        self.slider.blockSignals(False)

        self.update_frame_label()

    def on_slider_change(self, val):
        self.video.set_frame(val)
        self.update_frame_label()

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
            QApplication.quit()

    def save_and_exit(self):
        data = self.video.get_regions_pct()

        with open(OUTPUT_FILE, "w") as f:
            json.dump(data, f, indent=2)

        print("Saved:", data)
        QApplication.quit()


if __name__ == "__main__":
    app = QApplication(sys.argv)

    window = App()
    window.show()
    window.raise_()
    window.activateWindow()

    sys.exit(app.exec_())
