#!/usr/bin/env python3
"""Hailo-10H live object detection demo using a USB webcam.

Runs YOLOv8m on the Hailo NPU and displays bounding boxes via OpenCV.
Press 'q' to quit.

Usage:
    DISPLAY=:0 python3 /opt/goodmorning/pi/hailo-webcam-demo.py
"""

import os
import time

# Force V4L2 backend — GStreamer grabs the device and fails on USB webcams
os.environ["OPENCV_VIDEOIO_PRIORITY_V4L2"] = "990"
os.environ["OPENCV_VIDEOIO_PRIORITY_GSTREAMER"] = "0"

import cv2  # noqa: E402
import numpy as np
from hailo_platform import VDevice

# COCO class names (80 classes)
COCO_CLASSES = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck",
    "boat", "traffic light", "fire hydrant", "stop sign", "parking meter", "bench",
    "bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra",
    "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
    "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove",
    "skateboard", "surfboard", "tennis racket", "bottle", "wine glass", "cup",
    "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
    "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse",
    "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
    "refrigerator", "book", "clock", "vase", "scissors", "teddy bear",
    "hair drier", "toothbrush",
]

np.random.seed(42)
COLORS = np.random.randint(0, 255, size=(len(COCO_CLASSES), 3), dtype=np.uint8)

MODEL_PATH = "/usr/share/hailo-models/yolov8m_h10.hef"
INPUT_SIZE = 640
SCORE_THRESHOLD = 0.45
CAMERA_INDEX = 0
CAMERA_WIDTH = 1280
CAMERA_HEIGHT = 720


def preprocess(frame):
    """Resize and letterbox frame to INPUT_SIZE x INPUT_SIZE."""
    h, w = frame.shape[:2]
    scale = min(INPUT_SIZE / w, INPUT_SIZE / h)
    new_w, new_h = int(w * scale), int(h * scale)
    resized = cv2.resize(frame, (new_w, new_h))

    padded = np.full((INPUT_SIZE, INPUT_SIZE, 3), 114, dtype=np.uint8)
    y_off = (INPUT_SIZE - new_h) // 2
    x_off = (INPUT_SIZE - new_w) // 2
    padded[y_off:y_off + new_h, x_off:x_off + new_w] = resized
    return padded, scale, x_off, y_off


def postprocess(nms_output, scale, x_off, y_off, orig_w, orig_h):
    """Parse NMS output (80, 5, 100) -> list of (x1, y1, x2, y2, score, class_id).

    NMS output format (tf_format=True): [classes, bbox_params, max_detections]
    bbox_params: [y_min, x_min, y_max, x_max, score] — normalized to [0, 1].
    """
    detections = []
    for class_id in range(nms_output.shape[0]):
        scores = nms_output[class_id, 4, :]
        mask = scores > SCORE_THRESHOLD
        if not np.any(mask):
            continue

        for det_idx in np.where(mask)[0]:
            score = scores[det_idx]
            y_min = nms_output[class_id, 0, det_idx] * INPUT_SIZE
            x_min = nms_output[class_id, 1, det_idx] * INPUT_SIZE
            y_max = nms_output[class_id, 2, det_idx] * INPUT_SIZE
            x_max = nms_output[class_id, 3, det_idx] * INPUT_SIZE

            x1 = int(np.clip((x_min - x_off) / scale, 0, orig_w))
            y1 = int(np.clip((y_min - y_off) / scale, 0, orig_h))
            x2 = int(np.clip((x_max - x_off) / scale, 0, orig_w))
            y2 = int(np.clip((y_max - y_off) / scale, 0, orig_h))

            detections.append((x1, y1, x2, y2, float(score), class_id))

    return detections


def draw(frame, detections, fps):
    """Draw bounding boxes, labels, and FPS on frame."""
    for x1, y1, x2, y2, score, cid in detections:
        color = tuple(int(c) for c in COLORS[cid])
        label = f"{COCO_CLASSES[cid]} {score:.0%}"

        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)
        cv2.rectangle(frame, (x1, y1 - th - 8), (x1 + tw, y1), color, -1)
        cv2.putText(frame, label, (x1, y1 - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)

    info = f"{len(detections)} objects | {fps:.1f} FPS"
    cv2.putText(frame, info, (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2, cv2.LINE_AA)
    return frame


def main():
    print(f"Loading model: {MODEL_PATH}")

    with VDevice() as device:
        model = device.create_infer_model(MODEL_PATH)
        in_name = model.input().name
        out_name = model.output().name
        out_shape = model.output().shape

        print("Configuring inference pipeline...")
        configured = model.configure()

        print(f"Opening camera {CAMERA_INDEX} at {CAMERA_WIDTH}x{CAMERA_HEIGHT}...")
        cap = cv2.VideoCapture("/dev/video0", cv2.CAP_V4L2)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter.fourcc(*"MJPG"))

        if not cap.isOpened():
            print("ERROR: Could not open camera")
            return

        print("Running — press 'q' to quit")
        fps = 0.0

        while True:
            t0 = time.monotonic()

            ret, frame = cap.read()
            if not ret:
                break

            orig_h, orig_w = frame.shape[:2]
            preprocessed, scale, x_off, y_off = preprocess(frame)

            # Allocate buffers and run inference
            output_buf = np.empty(out_shape, dtype=np.float32)
            bindings = configured.create_bindings(
                input_buffers={in_name: preprocessed},
                output_buffers={out_name: output_buf},
            )
            configured.run([bindings], 10000)

            nms_output = bindings.output().get_buffer(tf_format=True)
            detections = postprocess(nms_output, scale, x_off, y_off, orig_w, orig_h)
            frame = draw(frame, detections, fps)

            cv2.imshow("Hailo-10H Object Detection", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

            fps = 1.0 / (time.monotonic() - t0)

        cap.release()
        cv2.destroyAllWindows()
        print("Done.")


if __name__ == "__main__":
    main()
