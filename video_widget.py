import sys

import cv2

from PyQt5.QtCore import QSize, Qt
from PyQt5.QtGui import QColor, QImage, QPainter, QPen
from PyQt5.QtWidgets import QApplication, QWidget

from config import (
    BACK_FRAME_OFFSET_COUNT,
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

        self.video_path = video_path
        self.cap = cv2.VideoCapture(video_path)
        self.analysis_cap = cv2.VideoCapture(video_path)
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
        self.back_frame_offset_count = BACK_FRAME_OFFSET_COUNT
        self.frame_luminance_cache = {}
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

    def _compute_region_luminance_pct(self, frame, region):
        x1, y1, x2, y2 = self.get_region_bounds(region)
        if x2 <= x1 or y2 <= y1:
            return 0

        roi = frame[y1:y2, x1:x2]
        avg_bgr = roi.mean(axis=(0, 1))
        max_channel = max(avg_bgr[0], avg_bgr[1], avg_bgr[2])
        min_channel = min(avg_bgr[0], avg_bgr[1], avg_bgr[2])
        return round(((max_channel + min_channel) / (2 * 255)) * 100)

    def _compute_frame_luminance_pcts(self, frame):
        return [
            self._compute_region_luminance_pct(frame, region)
            for region in self.regions
        ]

    def _cache_current_frame_luminance_pcts(self):
        luminance_pcts = self._compute_frame_luminance_pcts(self.frame)
        self.frame_luminance_cache[self.current_frame] = luminance_pcts
        return luminance_pcts

    def _get_frame_luminance_pcts(self, frame_index):
        if frame_index in self.frame_luminance_cache:
            return self.frame_luminance_cache[frame_index]

        clamped_frame_index = max(0, min(self.total_frames - 1, frame_index))
        self.analysis_cap.set(cv2.CAP_PROP_POS_FRAMES, clamped_frame_index)
        ret, frame = self.analysis_cap.read()
        if not ret:
            return None

        luminance_pcts = self._compute_frame_luminance_pcts(frame)
        self.frame_luminance_cache[clamped_frame_index] = luminance_pcts
        return luminance_pcts

    def _get_current_frame_luminance_pcts(self):
        return self.frame_luminance_cache.get(self.current_frame) or self._cache_current_frame_luminance_pcts()

    def _populate_frame_luminance_cache_range(self, start_frame, end_frame):
        start_frame = max(0, start_frame)
        end_frame = min(self.total_frames - 1, end_frame)
        if start_frame > end_frame:
            return

        missing_frames = [
            frame_index
            for frame_index in range(start_frame, end_frame + 1)
            if frame_index not in self.frame_luminance_cache
        ]
        if not missing_frames:
            return

        self.analysis_cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        for frame_index in range(start_frame, end_frame + 1):
            ret, frame = self.analysis_cap.read()
            if not ret:
                break

            if frame_index not in self.frame_luminance_cache:
                self.frame_luminance_cache[frame_index] = self._compute_frame_luminance_pcts(frame)

    def is_region_above_threshold(self, region):
        return self._compute_region_luminance_pct(self.frame, region) >= self.luminance_threshold_pct

    def _get_region_threshold_states(self):
        return [
            luminance_pct >= self.luminance_threshold_pct
            for luminance_pct in self._get_current_frame_luminance_pcts()
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
            self._cache_current_frame_luminance_pcts()

        return ret

    def _get_region_threshold_states_for_frame(self, frame_index):
        luminance_pcts = self._get_frame_luminance_pcts(frame_index)
        if luminance_pcts is None:
            return None

        return [
            luminance_pct >= self.luminance_threshold_pct
            for luminance_pct in luminance_pcts
        ]

    def find_matching_frame(self, direction, start_frame=None):
        if direction not in (-1, 1):
            return None

        if start_frame is None:
            start_frame = self.current_frame

        start_frame = max(0, min(self.total_frames - 1, start_frame))

        if direction == 1:
            if start_frame >= self.total_frames - 1:
                return None
            previous_states = self._get_region_threshold_states_for_frame(start_frame)
            if previous_states is None:
                return None

            self.analysis_cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame + 1)
            for frame_index in range(start_frame + 1, self.total_frames):
                ret, frame = self.analysis_cap.read()
                if not ret:
                    break
                luminance_pcts = self.frame_luminance_cache.get(frame_index)
                if luminance_pcts is None:
                    luminance_pcts = self._compute_frame_luminance_pcts(frame)
                    self.frame_luminance_cache[frame_index] = luminance_pcts
                current_states = [
                    luminance_pct >= self.luminance_threshold_pct
                    for luminance_pct in luminance_pcts
                ]

                if self.trigger_matcher.get_matches(
                    previous_states,
                    current_states,
                    frame_index,
                ):
                    return frame_index

                previous_states = current_states

            return None

        if start_frame <= 1:
            return None

        self._populate_frame_luminance_cache_range(0, start_frame)
        for frame_index in range(start_frame - 1, 0, -1):
            previous_luminance_pcts = self._get_frame_luminance_pcts(frame_index - 1)
            current_luminance_pcts = self._get_frame_luminance_pcts(frame_index)

            if previous_luminance_pcts is None or current_luminance_pcts is None:
                break

            previous_states = [
                luminance_pct >= self.luminance_threshold_pct
                for luminance_pct in previous_luminance_pcts
            ]
            current_states = [
                luminance_pct >= self.luminance_threshold_pct
                for luminance_pct in current_luminance_pcts
            ]

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

    def set_back_frame_offset_count(self, offset_count):
        self.back_frame_offset_count = offset_count

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

        current_luminance_pcts = self._get_current_frame_luminance_pcts()
        for index, region in enumerate(self.regions):
            color = (
                QColor(0, 255, 0)
                if region["label"] == "positive"
                else QColor(255, 0, 0)
            )
            painter.setPen(QPen(color, 2))

            draw_x = int(region["x"] * self.scale)
            draw_y = int(region["y"] * self.scale)
            draw_size = int(BOX_SIZE * self.scale)
            luminance_pct = current_luminance_pcts[index]

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
        self.frame_luminance_cache.clear()
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
