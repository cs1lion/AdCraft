"""Render a SceneScript and look at the pictures.

The point of this is composition, which no assertion in the repo can judge: the
camera fix made renders real, and the first real look at the jinghai script
showed every shot dominated by foreground geometry. That is a DATA problem, and
data problems are fixed by looking, not by testing.

So: render, sample the shot starts/ends from the delivered MP4, build a contact
sheet, and report how much of each frame the subject actually occupies. The last
number is the one that matters — a wide shot where the character is 0.3% of the
pixels is a wide shot of a pillar.
"""

import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

API = "http://127.0.0.1:8020"
SCRIPT = Path(sys.argv[1])
LABEL = sys.argv[2] if len(sys.argv) > 2 else SCRIPT.stem
OUT = Path(r"C:\Users\18712\AppData\Local\Temp\opencode\compositions") / LABEL
OUT.mkdir(parents=True, exist_ok=True)


def render(scene: dict) -> dict:
    body = json.dumps({
        "scene_script": scene,
        "render_video": True,
        "extract_keyframes": False,
        "timeout_seconds": 600,
    }).encode()
    request = urllib.request.Request(
        API + "/api/v1/scene-3d/render", data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=900) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        return {"success": False, "error": error.read().decode()[:800]}


def sample_and_measure(video: Path, shots: list[dict], subject_rgb: tuple[int, int, int]) -> None:
    from PIL import Image

    picks: list[tuple[str, int]] = []
    for shot in shots:
        for name, frame in (("start", shot["start_frame"]), ("end", shot["end_frame"] - 1)):
            picks.append((f"{shot['id']}_{name}", frame))

    sampled: list[tuple[str, Path]] = []
    for name, frame in picks:
        target = OUT / f"{name}_f{frame:04d}.png"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(video),
             "-vf", f"select=eq(n\\,{frame})", "-vsync", "0", "-frames:v", "1", str(target)],
            check=False, capture_output=True,
        )
        if target.exists():
            sampled.append((name, target))

    if not sampled:
        print("no frames sampled")
        return

    listing = OUT / "sheet.txt"
    listing.write_text(
        "\n".join(f"file '{p.as_posix()}'\nduration 1" for _, p in sampled), encoding="utf-8"
    )
    sheet = OUT / "contact_sheet.png"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
         "-vf", "scale=440:-1,tile=3x2", "-frames:v", "1", str(sheet)],
        check=False, capture_output=True,
    )

    print(f"\n{'sample':<22}{'colors':>8}{'subject_px':>12}{'subject_%':>11}")
    for name, path in sampled:
        image = Image.open(path).convert("RGB")
        colors = image.getcolors(maxcolors=1 << 20)
        # "Subject" = pixels close to the character's authored colour. Proximate
        # rather than exact: the renderer shades it, so an exact match finds
        # nothing and reports every scene as having no character in it.
        target = subject_rgb
        subject = 0
        for count, (r, g, b) in colors:
            if abs(r - target[0]) + abs(g - target[1]) + abs(b - target[2]) < 150:
                subject += count
        total = image.width * image.height
        print(f"{name:<22}{len(colors):>8}{subject:>12}{100 * subject / total:>10.2f}%")
    print(f"\ncontact sheet: {sheet}")


def main() -> int:
    scene = json.loads(SCRIPT.read_text(encoding="utf-8"))
    result = render(scene)
    if not result.get("success"):
        print("RENDER FAILED:", json.dumps(result, ensure_ascii=False)[:900])
        return 1
    print(f"rendered {result['frame_count']} frames in {result['duration_seconds']:.1f}s "
          f"-> {result['video_path']}")
    video = Path(result["video_path"])
    colour = scene["characters"][1]["appearance"].get("color", "#ffffff")
    rgb = tuple(int(colour[i:i + 2], 16) for i in (1, 3, 5))
    sample_and_measure(video, scene["shots"], rgb)
    return 0


if __name__ == "__main__":
    sys.exit(main())