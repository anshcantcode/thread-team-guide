"""Download and warm up the local English recognizer without recording a microphone."""
from pathlib import Path
from faster_whisper import WhisperModel

root=Path(__file__).resolve().parent.parent
model=WhisperModel('base.en',device='cpu',compute_type='int8',cpu_threads=4,download_root=str(root/'.runtime/whisper'))
print('Local base.en speech model is ready. No microphone was used.')
