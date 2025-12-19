from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from src.plugins.audio_io_plugin import AudioIOPlugin

router = APIRouter()
audio_plugin = AudioIOPlugin()

class SpeakRequest(BaseModel):
    text: str

@router.post("/audio/speak")
async def speak(request: SpeakRequest):
    """
    Stream TTS audio for the given text.
    Returns audio/mpeg stream.
    """
    return StreamingResponse(
        audio_plugin.synthesize(request.text),
        media_type="audio/mpeg"
    )
