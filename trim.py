import soundfile as sf; import numpy as np; wav, sr = sf.read('voice_sample.wav'); trimmed = wav[:sr*11]; sf.write('voice_sample.wav', trimmed, sr); print(f'Trimmed to {len(trimmed)/sr:.1f}s')
