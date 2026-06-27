import os
import cv2
from PIL import Image
import piexif


def convert_to_degrees(value):
    d = value[0][0] / value[0][1]
    m = value[1][0] / value[1][1]
    s = value[2][0] / value[2][1]
    return d + (m / 60.0) + (s / 3600.0)


def check_image_authenticity(image_path):

    score = 0
    checks = {}

    # ── EXIF + GPS + Date + AI Flag ──────────────────────────
    try:
        img = Image.open(image_path)
        exif_bytes = img.info.get("exif", b"")

        if exif_bytes:
            exif_data = piexif.load(exif_bytes)

            # Camera check
            has_camera = piexif.ImageIFD.Make in exif_data.get("0th", {})
            checks["has_exif"] = has_camera
            if has_camera:
                score += 2

            # GPS check
            gps = exif_data.get("GPS", {})
            if gps:
                checks["has_gps"] = True
                try:
                    lat = convert_to_degrees(gps[piexif.GPSIFD.GPSLatitude])
                    lon = convert_to_degrees(gps[piexif.GPSIFD.GPSLongitude])
                    checks["latitude"] = round(lat, 6)
                    checks["longitude"] = round(lon, 6)
                    score += 1
                except:
                    checks["latitude"] = None
                    checks["longitude"] = None
            else:
                checks["has_gps"] = False

            # Date taken check
            try:
                date_taken = exif_data["Exif"].get(
                    piexif.ExifIFD.DateTimeOriginal
                )
                checks["date_taken"] = (
                    date_taken.decode()
                    if isinstance(date_taken, bytes)
                    else str(date_taken)
                )
            except:
                checks["date_taken"] = None

            # AI image flag
            checks["possible_ai_image"] = False

        else:
            checks["has_exif"] = False
            checks["has_gps"] = False
            checks["date_taken"] = None

            # No EXIF = possibly AI generated or WhatsApp/Instagram stripped
            # ⚠️ Note: Many real photos lose EXIF when sent via WhatsApp/Instagram
            checks["possible_ai_image"] = True

    except Exception as e:
        checks["has_exif"] = False
        checks["has_gps"] = False
        checks["date_taken"] = None
        checks["possible_ai_image"] = True
        print("EXIF Error:", e)

    # ── Blur Check ───────────────────────────────────────────
    try:
        image = cv2.imread(image_path)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        blur_score = cv2.Laplacian(gray, cv2.CV_64F).var()
        checks["blur_score"] = round(blur_score, 2)

        if 10 < blur_score < 2000:
            checks["blur_ok"] = True
            score += 2
        else:
            checks["blur_ok"] = False

    except Exception as e:
        checks["blur_score"] = 0
        checks["blur_ok"] = False
        print("Blur Error:", e)

    # ── File Size Check ──────────────────────────────────────
    try:
        file_size = os.path.getsize(image_path)
        checks["file_size_kb"] = round(file_size / 1024, 2)

        if file_size > 100 * 1024:
            checks["size_ok"] = True
            score += 1
        else:
            checks["size_ok"] = False

    except Exception as e:
        checks["size_ok"] = False
        print("Size Error:", e)

    # ── Final Decision ───────────────────────────────────────
    is_real = score >= 3

    return {
        "is_real": is_real,
        "score": f"{score}/6",
        "checks": checks,
        "message": "Real photo ✅" if is_real else "Possibly fake image ⚠️"
    }