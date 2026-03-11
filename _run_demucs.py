"""
Wrapper script to run demucs with torchaudio.save monkey-patched
to use soundfile instead of torchcodec (which is broken on Windows).
Usage: python _run_demucs.py --two-stems vocals -n htdemucs -o <outdir> <input>
"""
import sys
import soundfile as sf
import torch
import torchaudio

def _save_soundfile(filepath, src, sample_rate, **kwargs):
    """soundfile-based replacement for torchaudio.save"""
    if src.dim() == 1:
        src = src.unsqueeze(0)
    # soundfile expects (samples, channels)
    data = src.cpu().numpy().T
    sf.write(filepath, data, sample_rate)

# Monkey-patch torchaudio.save
torchaudio.save = _save_soundfile

# Now run demucs main with the remaining arguments
from demucs.separate import main
sys.argv = [sys.argv[0]] + sys.argv[1:]
main()
