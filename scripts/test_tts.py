from f5_tts.api import F5TTS
import sounddevice as sd, numpy as np
tts = F5TTS(device='cuda')
wav, sr, _ = tts.infer(ref_file='voice_sample.wav', ref_text='In a quiet village where the sky brushes the fields in hues of gold, young Mia discovered a map leading to forgotten treasures. Little did she know, her cat Whiskers had ', gen_text='Hey, I was just thinking about you. What is going on? I am very very bored', speed=0.75)
wav = np.array(wav, dtype='float32')
wav = np.concatenate([wav, np.zeros(int(sr *      
  0.5))])
sd.play(wav, samplerate=sr); sd.wait(); print('done')
