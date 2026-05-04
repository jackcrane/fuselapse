import os
import sys
import subprocess
from pathlib import Path

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
    TIMELAPSE_FRAMES_DIR,
)
from triggers import TriggerMatcher


def get_ffmpeg_executable():
    bundled_root = getattr(sys, "_MEIPASS", None)
    executable_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"

    if bundled_root:
        bundled_ffmpeg = Path(bundled_root) / executable_name
        if bundled_ffmpeg.exists():
            return str(bundled_ffmpeg)

    return executable_name


class TimelapseBuilder:
    def __init__(
        self,
        video_path,
        regions,
        threshold_pct,
        back_frame_offset_count,
        start_frame,
        total_frames,
    ):
        self.video_path = video_path
        self.regions = [dict(region) for region in regions]
        self.threshold_pct = threshold_pct
        self.back_frame_offset_count = back_frame_offset_count
        self.start_frame = start_frame
        self.total_frames = total_frames
        self.frame_luminance_cache = {}
        self.trigger_matcher = TriggerMatcher(CHECK_REGION_LINES, [])

    def _emit_progress(self, callback, value):
        if callback is None:
            return
        callback(max(0.0, min(100.0, float(value))))

    def _compute_region_luminance_pct(self, frame, region):
        x1 = max(0, min(frame.shape[1], region["x"]))
        y1 = max(0, min(frame.shape[0], region["y"]))
        x2 = max(0, min(frame.shape[1], region["x"] + BOX_SIZE))
        y2 = max(0, min(frame.shape[0], region["y"] + BOX_SIZE))
        if x2 <= x1 or y2 <= y1:
            return 0

        roi = frame[y1:y2, x1:x2]
        avg_bgr = roi.mean(axis=(0, 1))
        max_channel = max(avg_bgr[0], avg_bgr[1], avg_bgr[2])
        min_channel = min(avg_bgr[0], avg_bgr[1], avg_bgr[2])
        return round(((max_channel + min_channel) / (2 * 255)) * 100)

    def _compute_frame_states(self, frame):
        return [
            self._compute_region_luminance_pct(frame, region) >= self.threshold_pct
            for region in self.regions
        ]

    def _get_frame_states(self, cap, frame_index):
        if frame_index in self.frame_luminance_cache:
            return self.frame_luminance_cache[frame_index]

        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ret, frame = cap.read()
        if not ret:
            return None

        states = self._compute_frame_states(frame)
        self.frame_luminance_cache[frame_index] = states
        return states

    def _find_matching_frame_forward(self, cap, start_frame, progress_callback=None):
        if start_frame >= self.total_frames - 1:
            return None

        previous_states = self._get_frame_states(cap, start_frame)
        if previous_states is None:
            return None

        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame + 1)
        for frame_index in range(start_frame + 1, self.total_frames):
            ret, frame = cap.read()
            if not ret:
                break

            current_states = self.frame_luminance_cache.get(frame_index)
            if current_states is None:
                current_states = self._compute_frame_states(frame)
                self.frame_luminance_cache[frame_index] = current_states

            self._emit_progress(
                progress_callback,
                5 + (65 * frame_index / max(1, self.total_frames - 1)),
            )

            if self.trigger_matcher.get_matches(
                previous_states,
                current_states,
                frame_index,
            ):
                return frame_index

            previous_states = current_states

        return None

    def _get_offset_match_frames(self, progress_callback=None):
        analysis_cap = cv2.VideoCapture(self.video_path)
        if not analysis_cap.isOpened():
            raise RuntimeError("Could not open video for timelapse analysis.")

        try:
            current_frame = max(0, min(self.total_frames - 1, self.start_frame))
            matched_frames = []
            self._emit_progress(progress_callback, 5)

            while True:
                search_start = min(
                    current_frame + self.back_frame_offset_count,
                    self.total_frames - 1,
                )
                frame_index = self._find_matching_frame_forward(
                    analysis_cap,
                    search_start,
                    progress_callback=progress_callback,
                )
                if frame_index is None:
                    break

                offset_match_frame = frame_index - self.back_frame_offset_count
                if offset_match_frame <= current_frame:
                    break

                matched_frames.append(offset_match_frame)
                current_frame = offset_match_frame

            return matched_frames
        finally:
            analysis_cap.release()

    def _clear_exported_frames(self, frames_dir):
        for frame_path in frames_dir.glob("timelapse_frame_*.png"):
            frame_path.unlink()

    def _write_timelapse_frames(self, frame_numbers, frames_dir, progress_callback=None):
        export_cap = cv2.VideoCapture(self.video_path)
        if not export_cap.isOpened():
            raise RuntimeError("Could not open video for timelapse export.")

        try:
            for export_index, frame_number in enumerate(frame_numbers, start=1):
                export_cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
                ret, frame = export_cap.read()
                if not ret:
                    raise RuntimeError(f"Could not read frame {frame_number}.")

                frame_path = frames_dir / f"timelapse_frame_{export_index:06d}.png"
                if not cv2.imwrite(str(frame_path), frame):
                    raise RuntimeError(f"Could not write {frame_path}.")

                self._emit_progress(
                    progress_callback,
                    70 + (25 * export_index / max(1, len(frame_numbers))),
                )
        finally:
            export_cap.release()

    def _run_ffmpeg(self, frames_dir, frame_count, length_seconds, output_path):
        fps = frame_count / max(length_seconds, 0.1)
        command = [
            get_ffmpeg_executable(),
            "-y",
            "-framerate",
            f"{fps:.6f}",
            "-i",
            str(frames_dir / "timelapse_frame_%06d.png"),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(output_path),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except FileNotFoundError as error:
            raise RuntimeError("ffmpeg is not installed or was not found in PATH.") from error
        except subprocess.CalledProcessError as error:
            message = error.stderr.strip() or error.stdout.strip() or str(error)
            raise RuntimeError(f"ffmpeg failed: {message}") from error

    def create_timelapse(self, length_seconds, output_path, progress_callback=None):
        output_path = Path(output_path)
        frame_numbers = self._get_offset_match_frames(progress_callback=progress_callback)
        if not frame_numbers:
            return 0, None

        frames_dir = output_path.parent / TIMELAPSE_FRAMES_DIR
        frames_dir.mkdir(exist_ok=True)
        self._clear_exported_frames(frames_dir)
        self._write_timelapse_frames(
            frame_numbers,
            frames_dir,
            progress_callback=progress_callback,
        )
        self._emit_progress(progress_callback, 95)
        self._run_ffmpeg(frames_dir, len(frame_numbers), length_seconds, output_path)
        self._emit_progress(progress_callback, 100)
        return len(frame_numbers), output_path


class VideoWidget(QWidget):
    def __init__(self, video_path):
        super().__init__()

        self.video_path = video_path
        self.cap = cv2.VideoCapture(video_path)
        self.analysis_cap = cv2.VideoCapture(video_path)
        self.preview_cap = cv2.VideoCapture(video_path)
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
        self.progress_preview_enabled = False
        self.luminance_threshold_pct = LUMINANCE_THRESHOLD_PCT
        self.back_frame_offset_count = BACK_FRAME_OFFSET_COUNT
        self.frame_luminance_cache = {}
        self.trigger_matcher = TriggerMatcher(
            CHECK_REGION_LINES,
            self._get_region_threshold_states(),
        )

    def cleanup(self):
        self.cap.release()
        self.analysis_cap.release()
        self.preview_cap.release()

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

    def _load_preview_frame(self, frame_index):
        clamped_frame_index = max(0, min(self.total_frames - 1, frame_index))
        self.preview_cap.set(cv2.CAP_PROP_POS_FRAMES, clamped_frame_index)

        ret, frame = self.preview_cap.read()
        if ret:
            self.current_frame = clamped_frame_index
            self.frame = frame

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

    def build_timelapse_builder(self):
        return TimelapseBuilder(
            video_path=self.video_path,
            regions=self.regions,
            threshold_pct=self.luminance_threshold_pct,
            back_frame_offset_count=self.back_frame_offset_count,
            start_frame=self.current_frame,
            total_frames=self.total_frames,
        )

    def set_frame(self, frame_index, emit_matches=True):
        if self._load_frame(frame_index):
            if emit_matches:
                self._print_matching_trigger_frames()

        self.update()

    def show_preview_frame(self, frame_index):
        if not self._load_preview_frame(frame_index):
            return False

        self.update()
        return True

    def set_progress_preview_enabled(self, enabled):
        self.progress_preview_enabled = enabled
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

        if self.progress_preview_enabled:
            return

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
