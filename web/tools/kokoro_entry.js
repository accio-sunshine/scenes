// Browser bundle for the Scene Simulator: Kokoro 82M text-to-speech (kokoro-js, Apache-2.0; its phonemizer is eSpeak NG,
// GNU GPL). The model (onnx-community/Kokoro-82M-v1.0-ONNX, q8, ~90 MB) comes from Hugging Face on first use and is cached
// by the browser; onnxruntime-web's wasm is served from vendor/ort/ (not a CDN).
// window.SceneKokoro.speak(text, voice) -> Promise<{audio: Float32Array, sampling_rate: number}> (24 kHz mono).
import { KokoroTTS, env } from "kokoro-js";
let tts = null;
window.SceneKokoro = {
  engine: "Kokoro 82M (kokoro-js), Apache-2.0; phonemes by eSpeak NG, GNU GPL",
  model: "onnx-community/Kokoro-82M-v1.0-ONNX",
  load(progress) {
    if (!tts) {
      env.wasmPaths = new URL("vendor/ort/", document.baseURI).href;
      tts = KokoroTTS.from_pretrained(this.model, { dtype: "q8", device: "wasm", progress_callback: progress });
      tts.catch(() => { tts = null; });
    }
    return tts;
  },
  async voices() { return Object.keys((await this.load()).voices); },
  async speak(text, voice) {
    const a = await (await this.load()).generate(text, { voice });
    return { audio: a.audio, sampling_rate: a.sampling_rate };
  },
};
