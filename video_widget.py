import sys

import cv2

from PyQt5.QtCore import QSize, Qt
from PyQt5.QtGui import QColor, QImage, QPainter, QPen
from PyQt5.QtWidgets import QApplication, QWidget

from config import (
    BOX_SIZE,
    CHECK_REGION_LINES,
    CHECK_REGIONS,
    LUMINANCE_THRESHOLD_PCT,
    MAX_SCREEN_RATIO,
    SHOW_LUMINANCE_DEFAULT,
)
from triggers import TriggerMatcher


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
        self.trigger_matcher = TriggerMatcher(
            CHECK_REGION_LINES,
            self._get_region_threshold_states(),
        )

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

    def is_region_above_threshold(self, region):
        return self.get_region_luminance_pct(region) >= self.luminance_threshold_pct

    def _get_region_threshold_states(self):
        return [
            self.is_region_above_threshold(region) for region in self.regions
        ]

    def _print_matching_trigger_frames(self):
        current_states = self._get_region_threshold_states()
        for frame_number in self.trigger_matcher.get_matching_frames(
            self.current_frame, current_states
        ):
            print(frame_number)

    def _load_frame(self, frame_index):
        clamped_frame_index = max(0, min(self.total_frames - 1, frame_index))
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, clamped_frame_index)

        ret, frame = self.cap.read()
        if ret:
            self.current_frame = clamped_frame_index
            self.frame = frame

        return ret

    def _get_region_threshold_states_for_frame(self, frame_index):
        original_frame_index = self.current_frame
        original_frame = self.frame.copy()

        if not self._load_frame(frame_index):
            self.current_frame = original_frame_index
            self.frame = original_frame
            return None

        current_states = self._get_region_threshold_states()
        self.current_frame = original_frame_index
        self.frame = original_frame
        return current_states

    def find_matching_frame(self, direction):
        if direction not in (-1, 1):
            return None

        if direction == 1:
            if self.current_frame >= self.total_frames - 1:
                return None
            search_range = range(self.current_frame + 1, self.total_frames)
            previous_states = self._get_region_threshold_states()
            if previous_states is None:
                return None

            for frame_index in search_range:
                current_states = self._get_region_threshold_states_for_frame(frame_index)
                if current_states is None:
                    break

                if self.trigger_matcher.get_matches(
                    previous_states,
                    current_states,
                    frame_index,
                ):
                    return frame_index

                previous_states = current_states

            return None

        if self.current_frame <= 1:
            return None

        for frame_index in range(self.current_frame - 1, 0, -1):
            previous_states = self._get_region_threshold_states_for_frame(frame_index - 1)
            current_states = self._get_region_threshold_states_for_frame(frame_index)

            if previous_states is None or current_states is None:
                break

            if self.trigger_matcher.get_matches(
                previous_states,
                current_states,
                frame_index,
            ):
                return frame_index

        return None

    def set_frame(self, frame_index):
        if self._load_frame(frame_index):
            self._print_matching_trigger_frames()

        self.update()

    def set_show_luminance(self, enabled):
        self.show_luminance = enabled
        self.update()

    def set_luminance_threshold_pct(self, threshold_pct):
        self.luminance_threshold_pct = threshold_pct
        self.trigger_matcher.sync_states(self._get_region_threshold_states())
        self.update()

    def get_region_corners(self, region):
        x = region["x"]
        y = region["y"]
        return [
            (x, y),
            (x + BOX_SIZE, y),
            (x, y + BOX_SIZE),
            (x + BOX_SIZE, y + BOX_SIZE),
        ]

    def get_closest_region_corners(self, start_region, end_region):
        start_corners = self.get_region_corners(start_region)
        end_corners = self.get_region_corners(end_region)

        return min(
            (
                (start_corner, end_corner)
                for start_corner in start_corners
                for end_corner in end_corners
            ),
            key=lambda pair: (pair[0][0] - pair[1][0]) ** 2 + (pair[0][1] - pair[1][1]) ** 2,
        )

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

        line_pen = QPen(QColor(0, 0, 0))
        line_pen.setWidthF(1.5)
        painter.setPen(line_pen)
        for start_idx, end_idx in CHECK_REGION_LINES:
            start_region = self.regions[start_idx]
            end_region = self.regions[end_idx]
            start_corner, end_corner = self.get_closest_region_corners(start_region, end_region)
            painter.drawLine(
                int(start_corner[0] * self.scale),
                int(start_corner[1] * self.scale),
                int(end_corner[0] * self.scale),
                int(end_corner[1] * self.scale),
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
        self.trigger_matcher.sync_states(self._get_region_threshold_states())

    def get_regions_pct(self):
        return [
            {
                "x_pct": round(region["x"] / self.video_w, 4),
                "y_pct": round(region["y"] / self.video_h, 4),
                "label": region["label"],
            }
            for region in self.regions
        ]
