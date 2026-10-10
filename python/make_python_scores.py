"""
make_python_scores.py  -  run the Python cross-check on every scene's default settings and store the scores for the page.

For each scene (Home, Factory, Hospital, Automobile and the four Custom classic tests) it exports the scene with the
page's engine (node web/tools/export_scene.js), scores it with score_scene.py and writes web/src/python_scores.json,
which build.py puts into the page as the "Python" lines. Re-run it after changing a scenario or the engine, then
rebuild the page (cd web && python build.py).

Run (repo root):  python python/make_python_scores.py [scene ...]
"""
import datetime
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import score_scene  # noqa: E402

SCENES = ["home", "factory", "hospital", "automobile", "baby", "fan", "robot", "quiet"]
OUT = os.path.join(ROOT, "web", "src", "python_scores.json")


def main(argv=None):
    names = (argv if argv is not None else sys.argv[1:]) or SCENES
    data = json.load(open(OUT)) if os.path.exists(OUT) else {"scenes": {}}
    with tempfile.TemporaryDirectory() as tmp:
        for name in names:
            d = os.path.join(tmp, name)
            subprocess.run(["node", os.path.join(ROOT, "web", "tools", "export_scene.js"), name, d], check=True)
            scores, info = score_scene.score(score_scene.Scene(d))
            page = json.load(open(os.path.join(d, "page_scores.json")))
            data["scenes"][name] = {"scores": {k: round(v, 2) for k, v in scores.items()}, "info": info,
                                    "page_at_run": {k: round(v, 2) for k, v in page.items()}}
            worst = max(abs(page[k] - v) for k, v in scores.items() if k in page)
            print(f"{name}: {len(scores)} scores, largest page-Python difference {worst:.1f} dB, {info['total_seconds']} s")
    data["note"] = ("Python cross-check (python/score_scene.py: pyroomacoustics image-source room + the original Python "
                    "STFT/MPDR code) on each scene's default settings. Keys match the page's scores.")
    data["updated"] = datetime.date.today().isoformat()
    json.dump(data, open(OUT, "w"), indent=1)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
