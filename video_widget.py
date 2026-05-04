import sys

import cv2

from PyQt5.QtCore import QSize, Qt
from PyQt5.QtGui import QColor, QImage, QPainter, QPen
from PyQt5.QtWidgets import QApplication, QWidget

from config import (
    BOX_SIZE,
    CHECK_REGIONS,
    LUMINANCE_THRESHOLD_PCT,
    MAX_SCREEN_RATIO,
    SHOW_LUMINANCE_DEFAULT,
)


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
                "x": int(region["x_pct"] * self.video_w),
                "y": int(region["y_pct"] * self.video_h),
                "label": region["label"],
            }
            for region in CHECK_REGIONS
        ]

        self.current_frame = 0
        self.dragging_idx = None
        self.show_luminance = SHOW_LUMINANCE_DEFAULT
        self.luminance_threshold_pct = LUMINANCE_THRESHOLD_PCT

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
        avg_rgb = QColor(int(avg_bgr[2]), int(avg_bgr[1]), int(avg_bgr[0]))
        return round(avg_rgb.lightnessF() * 100)

    def set_frame(self, frame_index):
        self.current_frame = max(0, min(self.total_frames - 1, frame_index))
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, self.current_frame)

        ret, frame = self.cap.read()
        if ret:
            self.frame = frame

        self.update()

    def set_show_luminance(self, enabled):
        self.show_luminance = enabled
        self.update()

    def set_luminance_threshold_pct(self, threshold_pct):
        self.luminance_threshold_pct = threshold_pct
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)

        rgb = cv2.cvtColor(self.frame, cv2.COLOR_BGR2RGB)
        image = QImage(
            rgb.data,
            self.video_w,
            self.video_h,
            rgb.strides[0],
            QImage.Format_RGB888,
        )

        painter.drawImage(
            0,
            0,
            image.scaled(
                self.display_w,
                self.display_h,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            ),
        )

        for region in self.regions:
            color = (
                QColor(0, 255, 0)
                if region["label"] == "positive"
                else QColor(255, 0, 0)
            )
            painter.setPen(QPen(color, 2))

            draw_x = int(region["x"] * self.scale)
            draw_y = int(region["y"] * self.scale)
            draw_size = int(BOX_SIZE * self.scale)
            luminance_pct = self.get_region_luminance_pct(region)

            if luminance_pct < self.luminance_threshold_pct:
                fill_color = QColor(color)
                fill_color.setAlphaF(0.5)
                painter.fillRect(draw_x, draw_y, draw_size, draw_size, fill_color)

            painter.drawRect(draw_x, draw_y, draw_size, draw_size)

            if self.show_luminance:
                text_rect = image.rect()
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

        for index, region in enumerate(self.regions):
            if region["x"] <= x <= region["x"] + BOX_SIZE and region["y"] <= y <= region["y"] + BOX_SIZE:
                self.dragging_idx = index
                return

    def mouseMoveEvent(self, event):
        if self.dragging_idx is None:
            return

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
                "x_pct": round(region["x"] / self.video_w, 4),
                "y_pct": round(region["y"] / self.video_h, 4),
                "label": region["label"],
            }
            for region in self.regions
        ]
