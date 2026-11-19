
from ultralytics import YOLO
import cv2
import time
import subprocess
import imageio_ffmpeg
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = ROOT / "models" / "yolo11n.pt"

def point_inside_zone(point, polygon):
    """
    Returns True if a person's foot-point is inside
    the configured restricted polygon.
    """
    contour = polygon.reshape((-1, 1, 2)).astype("int32")

    return cv2.pointPolygonTest(
        contour, (float(point[0]), float(point[1])), False ) >=0


def run_detection(video_path, output_path, progress_callback=None, show_window=False, zone_points=None, monitoring_enabled=True, elevated_threshold=15, high_threshold=30):


    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"Model missing: {MODEL_PATH}")

    if elevated_threshold >= high_threshold:
        raise ValueError(
            "High threshold must be greater than elevated threshold."
        )    

    model = YOLO(str(MODEL_PATH))
    cap = cv2.VideoCapture(str(video_path))

    if not cap.isOpened():
        raise ValueError("Could not open video.")

    fps_video = cap.get(cv2.CAP_PROP_FPS) or 25
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

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
        raise RuntimeError("Could not create output video.")

    unique_ids = set()
    current_people = 0
    processing_fps = 0
    frame_count = 0
    prev = time.time()

    if zone_points is not None:
        zone_polygon = cv2.convexHull(
            __import__("numpy").array(
                zone_points,
                dtype="int32"
            )
        )
    else:
        zone_polygon = None

    active_intrusions = {}
    intrusion_events = []    


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
            current_people = 0
            current_ids = set()

            annoatated = results[0].plot(
                labels=True,
                boxes=True,
                conf=True
            )

            if (
                boxes is not None and boxes.id is not None
            ):
                ids = boxes.id.cpu().numpy().astype(int)

                coordinates = (boxes.xyxy.cpu().numpy()
                )
                current_people = len(ids)
                for tracking_id, box in zip(
                    ids,
                    coordinates
                ):
                    tracking_id = int(tracking_id)

                current_ids.add(tracking_id)
                unique_ids.add(tracking_id)
                
                unique_ids.update(int(i) for i in ids)

            annotated = results[0].plot(
                labels=True,
                boxes=True,
                conf=True
            )

            now = time.time()
            processing_fps = 1 / max(now - prev, 0.001)
            prev = now

            # CrowdShield information panel
            cv2.rectangle(
                annotated,
                (10, 10),
                (340, 155),
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
                (20, 80),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (255, 255, 255),
                2
            )

            cv2.putText(
                annotated,
                f"Total Tracked: {len(unique_ids)}",
                (20, 110),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (255, 255, 255),
                2
            )

            cv2.putText(
                annotated,
                f"FPS: {processing_fps:.1f}",
                (20, 140),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 0),
                2
            )

            writer.write(annotated)

            # Live OpenCV popup (backend-only mode)
            if show_window:
                cv2.imshow("CrowdShield AI", annotated)

                key = cv2.waitKey(1) & 0xFF

                if key == ord("q") or key == 27:
                    break

            if progress_callback and total_frames:
                progress_callback(frame_count / total_frames)

    finally:
        cap.release()
        writer.release()

        if show_window:
            cv2.destroyAllWindows()

    if not temp_output.exists() or temp_output.stat().st_size == 0:
        raise RuntimeError("Video processing produced an empty file.")

    # Convert to browser-compatible H.264
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    subprocess.run([
        ffmpeg,
        "-y",
        "-i", str(temp_output),
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_path)
    ], check=True)

    temp_output.unlink(missing_ok=True)

    return {
        "current_people": current_people,
        "total_people": len(unique_ids),
        "fps": round(processing_fps, 1),
        "frames_processed": frame_count
    }


# Direct backend execution
if __name__ == "__main__":

    video_path = ROOT / "uploads" / "metro1.mp4"
    output_path = ROOT / "outputs" / "metro1_processed.mp4"

    print("Starting CrowdShield AI...")

    result = run_detection(
        video_path,
        output_path,
        show_window=True
    )

    print("\nDetection completed!")
    print(result)
    print(f"Processed video saved at: {output_path}")

