from ultralytics import YOLO
import cv2

model = YOLO("yolov8n.pt")


def detect_image(image_path):

    image = cv2.imread(image_path)

    if image is None:
        return {
            "valid": False,
            "objects": [],
            "message": "Image could not be read"
        }

    results = model(image)

    detections = []

    for result in results:
        for box in result.boxes:

            confidence = float(box.conf[0])

            if confidence > 0.5:
                class_id = int(box.cls[0])
                class_name = model.names[class_id]

                detections.append({
                    "object_name": class_name,
                    "confidence": round(confidence, 2)
                })

    return {
        "valid": True,
        "objects": detections,
        "message": f"{len(detections)} object(s) detected in image"
    }