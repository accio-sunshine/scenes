// Browser bundle for the Scene Simulator: meSpeak (eSpeak, GPL) with its English config and en-us voice built in.
// window.SceneTTS.speak(text, {variant, pitch, speed}) -> Uint8Array of a 22.05 kHz 16-bit mono WAV.
var m = require("mespeak");
m.loadConfig(require("mespeak/src/mespeak_config.json"));
m.loadVoice(require("mespeak/voices/en/en-us.json"));
window.SceneTTS = {
  speak: function (text, o) {
    o = o || {};
    var d = m.speak(text, { rawdata: "array", variant: o.variant || "m3", pitch: o.pitch == null ? 50 : o.pitch, speed: o.speed || 160 });
    return d ? new Uint8Array(d) : null;
  },
  engine: "meSpeak 2.0.2 (eSpeak), GNU GPL",
};
