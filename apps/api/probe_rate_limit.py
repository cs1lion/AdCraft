"""Read what the provider actually says about its rate limit.

18 submissions at a 6.5s gap produced 5 task ids and 13 `HTTP 429
rate_limit_exceeded`.  A 6.5s gap is correct for 10 rpm, so either the key is on
a stricter free tier or the limit is per-something-else.  Guessing the number
and hard-coding it would be the same mistake as the `{5, 10}` duration fiction,
so this asks the provider directly: it replays one real submit-shaped request and
prints the response headers of whatever it gets back, especially
`X-RateLimit-*` / `Retry-After`.

Only one request is spent, and nothing is printed that identifies the key.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

API = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, API)
os.chdir(API)

from app.core.config import Settings                      # noqa: E402
from app.tools.seedance_adapter import VolcengineSeedanceAdapter  # noqa: E402

WF = "adwf_v2_03bb71a4c200d8a3"

# The smallest possible legal reference payload: one 1x1 JPEG as the storyboard
# reference, so the request is shaped like a real submit without spending much.
SEGMENT = {
    "order": 1,
    "shot_id": "probe_seg1",
    "scene_id": "shot1",
    "prompt": "probe: a single still frame of a seaside boardwalk at golden hour",
    "duration_seconds": 7,
    "input_assets": [
        {
            "asset_id": "probe-still",
            "role": "storyboard",
            "model_input_type": "data_url",
            "model_input_value": (
                "data:image/jpeg;base64,"
                "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsL"
                "DBkSEw8UHRofHh0aHBwcJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/"
                "wAALCAABAAEBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAACP/EABQQAQAAAAAA"
                "AAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AfwD/2Q=="
            ),
            "url": "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEAYABgAAD/2Q==",
            "semantic_type": "storyboard_image",
            "shot_id": "probe_seg1",
        }
    ],
    "input_asset_ids": ["probe-still"],
    "source_assets": ["probe-still"],
    "scene_reference_ids": [],
    "character_ids": [],
    "prop_ids": [],
}


def main() -> None:
    settings = Settings.from_env()
    adapter = VolcengineSeedanceAdapter(settings)
    payload = adapter.payload_for_segment(SEGMENT)

    url = os.environ.get("PROBE_VIDEO_ENDPOINT") or "https://api.agnes-ai.cn/v1/videos"
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    for key, value in (payload.get("headers") or {}).items():
        request.add_header(key, value)
    api_key = getattr(settings, "video_generation_api_key", None) or getattr(
        settings, "video_api_key", None
    )
    if api_key:
        request.add_header("Authorization", f"Bearer {api_key}")

    print(f"POST {url}")
    print(f"payload keys: {sorted(payload)}")
    print(f"model       : {payload.get('model')}")
    print(f"duration    : {payload.get('seconds')}")
    print()
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            print(f"HTTP {response.status} -- accepted")
            for key, value in response.headers.items():
                print(f"  {key}: {value}")
            print(json.dumps(json.loads(response.read()), ensure_ascii=False)[:400])
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code} -- {exc.reason}")
        for key, value in exc.headers.items():
            print(f"  {key}: {value}")
        text = exc.read().decode("utf-8", "replace")
        print()
        print(f"body ({len(text)} bytes): {text[:600]}")
    except Exception as exc:  # noqa: BLE001 - the point is the diagnosis
        print(f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
