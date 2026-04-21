"""Generate a Jarvis persona speech recording via Gemini TTS."""

import asyncio
import os
import struct
import sys
import wave
from datetime import datetime


JARVIS_SCRIPT = """\
Good {time_of_day}, sir. This is Jarvis, your personal artificial intelligence assistant, \
reporting for duty on {date_full}. \
A few noteworthy items for today. \
First, a general status update. All core systems are nominal. \
The OpenJarvis engine is fully operational, with local inference running on Ollama, \
and cloud capabilities standing by via the Gemini API. \
Second, some facts about today. It is {weekday}, the {day_ordinal} of {month} {year}. \
We are currently in week {week_number} of the year. \
{days_remaining} days remain until the end of {year}. \
Third, a word on readiness. Voice channels, tool integrations, and the agent execution \
pipeline are all online. The clap detection module is active and listening. \
Two sharp claps, and I will be at your service immediately. \
That will be all for now. Standing by for your instructions.\
"""


def _ordinal(n: int) -> str:
    if 11 <= n % 100 <= 13:
        return f"{n}th"
    return f"{n}{['th', 'st', 'nd', 'rd', 'th'][min(n % 10, 4)]}"


def _build_script() -> str:
    now = datetime.now()
    hour = now.hour
    if hour < 12:
        time_of_day = "morning"
    elif hour < 17:
        time_of_day = "afternoon"
    else:
        time_of_day = "evening"

    day_of_year = now.timetuple().tm_yday
    days_in_year = 366 if (now.year % 4 == 0 and (now.year % 100 != 0 or now.year % 400 == 0)) else 365
    days_remaining = days_in_year - day_of_year

    return JARVIS_SCRIPT.format(
        time_of_day=time_of_day,
        date_full=now.strftime("%B %d, %Y"),
        weekday=now.strftime("%A"),
        day_ordinal=_ordinal(now.day),
        month=now.strftime("%B"),
        year=now.year,
        week_number=now.isocalendar()[1],
        days_remaining=days_remaining,
    )


def _pcm_to_wav(pcm_data: bytes, sample_rate: int = 24000) -> bytes:
    """Wrap raw 16-bit mono PCM in a WAV container."""
    import io
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()


async def generate_jarvis_recording(output_path: str, voice: str = "Enceladus") -> str:
    """Generate the Jarvis speech recording and save as WAV."""
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        # Try loading from .env
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        if os.path.exists(env_path):
            for line in open(env_path):
                line = line.strip()
                if line.startswith("GEMINI_API_KEY="):
                    api_key = line.split("=", 1)[1].strip()
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY not set")

    script = _build_script()
    print("--- Jarvis Script ---")
    print(script)
    print("---------------------\n")

    print(f"Generating speech with voice '{voice}'...")
    client = genai.Client(api_key=api_key)
    response = await client.aio.models.generate_content(
        model="gemini-2.5-flash-preview-tts",
        contents=script,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=voice,
                    )
                )
            ),
        ),
    )

    audio_bytes = b""
    for part in response.candidates[0].content.parts:
        if part.inline_data and part.inline_data.data:
            audio_bytes += part.inline_data.data

    if not audio_bytes:
        raise RuntimeError("No audio data returned from Gemini TTS")

    wav_data = _pcm_to_wav(audio_bytes)

    with open(output_path, "wb") as f:
        f.write(wav_data)

    duration_sec = len(audio_bytes) / (24000 * 2)  # 24kHz 16-bit mono
    print(f"Audio saved: {output_path}")
    print(f"Duration:    {duration_sec:.1f}s")
    print(f"Size:        {len(wav_data):,} bytes")
    return output_path


if __name__ == "__main__":
    output = sys.argv[1] if len(sys.argv) > 1 else "assets/jarvis_briefing.wav"
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    asyncio.run(generate_jarvis_recording(output))
