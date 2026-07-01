# routes/voice.py

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from auth_middleware import get_current_user
from logger import logger
import speech_recognition as sr
import tempfile
import os

router = APIRouter(prefix="/api/v1/voice", tags=["Voice"])

@router.post("/")
async def voice_complaint(
    audio: UploadFile = File(...),
    current_user: dict = Depends(get_current_user)
):
    # Save uploaded file with original extension
    ext = os.path.splitext(audio.filename)[1].lower()
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        tmp.write(await audio.read())
        tmp_path = tmp.name

    wav_path = tmp_path.replace(ext, ".wav")

    try:
        # Convert to wav if needed
        if ext != ".wav":
            from pydub import AudioSegment
            audio_seg = AudioSegment.from_file(tmp_path)
            audio_seg.export(wav_path, format="wav")
        else:
            wav_path = tmp_path

        # Convert speech to text
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_path) as source:
            audio_data = recognizer.record(source)
            text = recognizer.recognize_google(audio_data, language="en-IN")

        logger.info(f"Voice converted: {text}")

        return {
            "success": True,
            "text": text,
            "message": f"Recognized: {text}"
        }

    except sr.UnknownValueError:
        raise HTTPException(status_code=400, detail="Could not understand audio. Please speak clearly.")
    except sr.RequestError:
        raise HTTPException(status_code=503, detail="Speech recognition service unavailable.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        if os.path.exists(wav_path) and wav_path != tmp_path:
            os.unlink(wav_path)