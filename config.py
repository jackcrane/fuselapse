import sys


CHECK_REGIONS = [
    {"x_pct": 0.1006, "y_pct": 0.8083, "label": "positive"},
    {"x_pct": 0.8648, "y_pct": 0.8004, "label": "positive"},
    {"x_pct": 0.2264, "y_pct": 0.8617, "label": "negative"},
    {"x_pct": 0.7170, "y_pct": 0.8696, "label": "negative"},
]

CHECK_REGION_LINES = [
    (0, 2),
    (1, 3),
]

BOX_SIZE = 40
OUTPUT_FILE = "regions.json"
TIMELAPSE_OUTPUT_FILE = "timelapse.mp4"
TIMELAPSE_FRAMES_DIR = "frames"
MAX_SCREEN_RATIO = 0.82
LUMINANCE_THRESHOLD_PCT = 15
BACK_FRAME_OFFSET_COUNT = 10
TIMELAPSE_LENGTH_SECONDS = 30
SHOW_LUMINANCE_DEFAULT = "--debug-luminance" in sys.argv
