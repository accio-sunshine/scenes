"""Build robot_acoustic.html from src/ (engine + page template + the voices as base64).

Run from robot-audio/web:  python build.py
"""
import argparse
import base64
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                       # robot-audio/

PY_FILES = [
    {"title": "Conversation: baby crying", "files": [
        ("Mic 1 alone", "sim_conversation_out/conversation_baby_mic1.wav"),
        ("Beamformer at the man", "sim_conversation_out/conversation_baby_beam_male.wav"),
        ("Beamformer at the woman", "sim_conversation_out/conversation_baby_beam_female.wav")]},
    {"title": "Conversation: baby + fan", "files": [
        ("Mic 1 alone", "sim_conversation_out/conversation_baby_fan_mic1.wav"),
        ("Beamformer at the man", "sim_conversation_out/conversation_baby_fan_beam_male.wav"),
        ("Beamformer at the woman", "sim_conversation_out/conversation_baby_fan_beam_female.wav"),
        ("At the man, learned robot noise", "sim_conversation_out/conversation_baby_fan_beam_male_learned.wav"),
        ("At the woman, learned robot noise", "sim_conversation_out/conversation_baby_fan_beam_female_learned.wav")]},
    {"title": "Conversation: baby + robot moving (with footsteps)", "files": [
        ("Mic 1 alone", "sim_conversation_out/conversation_baby_robot_mic1.wav"),
        ("Beamformer at the man", "sim_conversation_out/conversation_baby_robot_beam_male.wav"),
        ("Beamformer at the woman", "sim_conversation_out/conversation_baby_robot_beam_female.wav"),
        ("At the man, learned robot noise", "sim_conversation_out/conversation_baby_robot_beam_male_learned.wav"),
        ("At the woman, learned robot noise", "sim_conversation_out/conversation_baby_robot_beam_female_learned.wav")]},
    {"title": "Clean voices", "files": [
        ("Man, clean", "sim_conversation_out/clean_male.wav"),
        ("Woman, clean", "sim_conversation_out/clean_female.wav"),
        ("Baby, clean", "sim_conversation_out/clean_baby.wav")]},
    {"title": "Robot noises, one at a time (mic 1)", "files": [
        ("Cooling fan", "sim_noise_out/noise_fan_mic1.wav"),
        ("Neck servo", "sim_noise_out/noise_neck_mic1.wav"),
        ("Shoulder servos", "sim_noise_out/noise_shoulders_mic1.wav"),
        ("Footsteps", "sim_noise_out/noise_footsteps_mic1.wav"),
        ("Brake clicks", "sim_noise_out/noise_clicks_mic1.wav"),
        ("Electrical hum", "sim_noise_out/noise_hum_mic1.wav")]},
    {"title": "Robot noise scenes (sim_8mic_robot_noise.py)", "files": [
        (f"{label}: {kind}", f"sim_noise_out/{scene}_{suffix}.wav")
        for scene, label in [("speech_only", "Speech only"), ("fan", "Fan"), ("fan_neck", "Fan + neck"),
                             ("walking", "Walking"), ("everything", "Everything")]
        for suffix, kind in [("mic1", "mic 1"), ("mpdr", "MPDR"), ("mvdr_ego", "MVDR + learned robot noise")]]},
]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "robot_acoustic.html"),
                    help="output page (default web/robot_acoustic.html); use a scratch path to avoid overwriting the published page")
    ap.add_argument("--no-published-map", action="store_true", help="do not rewrite src/published_files.json")
    args = ap.parse_args(argv)
    tpl = open(os.path.join(HERE, "src", "robot_acoustic.template.html"), encoding="utf-8").read()
    # engine.js (audio engine) then scenarios.js (scenario table + ambient-noise generators) share one scope
    engine = "\n".join(open(os.path.join(HERE, "src", f), encoding="utf-8").read() for f in ("engine.js", "scenarios.js"))
    voices = {k: base64.b64encode(open(os.path.join(ROOT, "voices", f"{k}.wav"), "rb").read()).decode()
              for k in ("male", "female", "baby")}
    files = [{"title": g["title"], "files": [{"label": l, "path": p} for l, p in g["files"]]} for g in PY_FILES]
    for g in files:
        for f in g["files"]:
            assert os.path.exists(os.path.join(ROOT, f["path"])), f["path"]
    out = (tpl.replace("/*ENGINE*/", engine)
              .replace("/*VOICES*/", json.dumps(voices))
              .replace("/*PYFILES*/", json.dumps(files)))
    path = args.out
    open(path, "w", encoding="utf-8").write(out)
    print(f"Wrote {path} ({len(out) / 1e6:.2f} MB)")
    if not args.no_published_map:
        # published-file map for the artifact: audio/<path> -> robot-audio/<path>
        json.dump({f"audio/{f['path']}": os.path.join("robot-audio", f["path"]) for g in files for f in g["files"]},
                  open(os.path.join(HERE, "src", "published_files.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
