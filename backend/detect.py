from ultralytics import YOLO
import cv2
import time
import subprocess
import imageio_ffmpeg
import numpy as np

from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = ROOT / "models" / "yolo11n.pt"


def point_inside_zone(point, polygon):
    contour = np.array(
        polygon,
        dtype=np.int32
    ).reshape((-1, 1, 2))

    return cv2.pointPolygonTest(
        contour,
        (float(point[0]), float(point[1])),
        False
    ) >= 0


def run_detection(
    video_path,
    output_path,
    progress_callback=None,
    show_window=False,
    zone_points=None,
    monitoring_enabled=True,
    elevated_threshold=15,
    high_threshold=30
):

    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"Model missing: {MODEL_PATH}"
        )

    if elevated_threshold < 0 or high_threshold < 1:
        raise ValueError("Crowd thresholds must be positive.")

    if elevated_threshold >= high_threshold:
        raise ValueError(
            "High threshold must be greater than elevated threshold."
        )

    zone_polygon = None

    if monitoring_enabled and zone_points is not None:
        if len(zone_points) < 3:
            raise ValueError(
                "Restricted zone requires at least three points."
            )

        zone_polygon = np.array(
            zone_points,
            dtype=np.int32
        ).reshape((-1, 1, 2))

    model = YOLO(str(MODEL_PATH))

    cap = cv2.VideoCapture(str(video_path))

    if not cap.isOpened():
        raise ValueError("Could not open video.")

    fps_video = cap.get(cv2.CAP_PROP_FPS) or 25
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    output_path = Path(output_path)
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    temp_output = output_path.with_name(
        output_path.stem + "_temp.mp4"
    )

    writer = cv2.VideoWriter(
        str(temp_output),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps_video,
        (width, height)
    )

    if not writer.isOpened():
        cap.release()
        raise RuntimeError(
            "Could not create output video."
        )

    unique_ids = set()
    active_intrusions = {}
    intrusion_events = []

    current_people = 0
    processing_fps = 0
    frame_count = 0
    crowd_status = "NORMAL"

    previous_time = time.time()

    try:

        while True:

            success, frame = cap.read()

            if not success:
                break

            frame_count += 1

            results = model.track(
                frame,
                persist=True,
                tracker="bytetrack.yaml",
                imgsz=960,
                conf=0.20,
                iou=0.7,
                classes=[0],
                verbose=False
            )

            boxes = results[0].boxes
            annotated = results[0].plot(
                labels=True,
                boxes=True,
                conf=True
            )

            current_people = 0
            current_ids = set()

            if boxes is not None and boxes.id is not None:

                ids = boxes.id.cpu().numpy().astype(int)
                coordinates = boxes.xyxy.cpu().numpy()

                current_people = len(ids)

                for tracking_id, box in zip(ids, coordinates):

                    tracking_id = int(tracking_id)

                    current_ids.add(tracking_id)
                    unique_ids.add(tracking_id)

                    x1, y1, x2, y2 = map(int, box)

                    foot_point = (
                        (x1 + x2) // 2,
                        y2
                    )

                    inside_zone = False

                    if zone_polygon is not None:
                        inside_zone = point_inside_zone(
                            foot_point,
                            zone_polygon
                        )

                    if (
                        monitoring_enabled
                        and inside_zone
                        and tracking_id not in active_intrusions
                    ):

                        event = {
                            "tracking_id": tracking_id,
                            "entry_time": datetime.now().isoformat(
                                timespec="seconds"
                            ),
                            "exit_time": None,
                            "duration_seconds": 0,
                            "status": "ACTIVE",
                            "entry_frame": frame_count
                        }

                        active_intrusions[tracking_id] = event
                        intrusion_events.append(event)

                    if (
                        monitoring_enabled
                        and inside_zone
                        and tracking_id in active_intrusions
                    ):

                        event = active_intrusions[tracking_id]

                        event["duration_seconds"] = round(
                            (frame_count - event["entry_frame"])
                            / fps_video,
                            2
                        )

                        cv2.rectangle(
                            annotated,
                            (x1, y1),
                            (x2, y2),
                            (0, 165, 255),
                            3
                        )

                        cv2.putText(
                            annotated,
                            f"INTRUSION ID: {tracking_id}",
                            (x1, max(y1 - 12, 20)),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.65,
                            (0, 165, 255),
                            2
                        )

                    elif tracking_id in active_intrusions:

                        event = active_intrusions.pop(tracking_id)

                        event["exit_time"] = datetime.now().isoformat(
                            timespec="seconds"
                        )

                        event["duration_seconds"] = round(
                            (frame_count - event["entry_frame"])
                            / fps_video,
                            2
                        )

                        event["status"] = "EXITED"

            for tracking_id in list(active_intrusions.keys()):

                if tracking_id not in current_ids:

                    event = active_intrusions.pop(tracking_id)

                    event["exit_time"] = datetime.now().isoformat(
                        timespec="seconds"
                    )

                    event["duration_seconds"] = round(
                        (frame_count - event["entry_frame"])
                        / fps_video,
                        2
                    )

                    event["status"] = "EXITED"

            if zone_polygon is not None and monitoring_enabled:

                cv2.polylines(
                    annotated,
                    [zone_polygon],
                    True,
                    (0, 165, 255),
                    3
                )

                zone_label_point = tuple(
                    zone_polygon[0][0]
                )

                cv2.putText(
                    annotated,
                    "RESTRICTED AREA",
                    zone_label_point,
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 165, 255),
                    2
                )

            if current_people >= high_threshold:
                crowd_status = "HIGH"

            elif current_people >= elevated_threshold:
                crowd_status = "ELEVATED"

            else:
                crowd_status = "NORMAL"

            cv2.rectangle(
                annotated,
                (10, 10),
                (410, 205),
                (30, 30, 30),
                -1
            )

            cv2.putText(
                annotated,
                "CrowdShield AI",
                (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 255),
                2
            )

            cv2.putText(
                annotated,
                f"Current Crowd: {current_people}",
                (20, 75),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                2
            )

            cv2.putText(
                annotated,
                f"Total Tracked: {len(unique_ids)}",
                (20, 105),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                2
            )

            cv2.putText(
                annotated,
                f"Crowd Status: {crowd_status}",
                (20, 135),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 0),
                2
            )

            cv2.putText(
                annotated,
                f"Active Intrusions: {len(active_intrusions)}",
                (20, 165),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 165, 255),
                2
            )

            current_time = time.time()

            processing_fps = 1 / max(
                current_time - previous_time,
                0.001
            )

            previous_time = current_time

            writer.write(annotated)

            if show_window:

                cv2.imshow(
                    "CrowdShield AI",
                    annotated
                )

                key = cv2.waitKey(1) & 0xFF

                if key == ord("q") or key == 27:
                    break

            if progress_callback and total_frames:
                progress_callback(
                    frame_count / total_frames
                )

    finally:

        cap.release()
        writer.release()

        if show_window:
            cv2.destroyAllWindows()

    for event in intrusion_events:
        if event["status"] == "ACTIVE":
            event["duration_seconds"] = round(
                (frame_count - event["entry_frame"])
                / fps_video,
                2
            )

        event.pop("entry_frame", None)

    if not temp_output.exists() or temp_output.stat().st_size == 0:
        raise RuntimeError(
            "Video processing produced an empty file."
        )

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i", str(temp_output),
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(output_path)
        ],
        check=True
    )

    temp_output.unlink(missing_ok=True)

    return {
        "current_people": current_people,
        "total_people": len(unique_ids),
        "fps": round(processing_fps, 1),
        "frames_processed": frame_count,
        "crowd_status": crowd_status,
        "elevated_threshold": elevated_threshold,
        "high_threshold": high_threshold,
        "intrusion_events": intrusion_events,
        "active_intrusions": len(active_intrusions)
    }


if __name__ == "__main__":

    video_path = ROOT / "uploads" / "metro1.mp4"
    output_path = ROOT / "outputs" / "metro1_processed.mp4"

    print("Starting CrowdShield AI...")

    result = run_detection(
        video_path,
        output_path,
        show_window=True,
        zone_points=[
            [100, 100],
            [400, 100],
            [400, 350],
            [100, 350]
        ],
        monitoring_enabled=True,
        elevated_threshold=15,
        high_threshold=30
    )

    print("Detection completed!")
    print(result)
    print(f"Processed video saved at: {output_path}")
