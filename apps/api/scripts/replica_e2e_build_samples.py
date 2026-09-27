"""构建拉片复刻 E2E 样例素材（无版权依赖：全部 ffmpeg 合成）。

产物（默认输出到仓库根 e2e_output/replica_e2e/）：
- sample_ad_4shots.mp4   12s 竖屏 4 镜头广告样片（每镜不同主色 + 屏上
  英文文字 + zoompan 运镜 + 不同频率正弦音轨——给拆解器提供切点/屏上
  文字/节奏的可读信号）
- sample_product.png / sample_host.png  参考图占位（商品 / 人物）
- sample_brief.txt       复刻目标文案（作为 user_description / replica_goal）
- sample_handwritten.adreplica  手写 .adreplica 文档（测试导入重编译路径）

用法：uv run python scripts/replica_e2e_build_samples.py [输出目录]
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT = REPO_ROOT / "e2e_output" / "replica_e2e"

FONT = r"'C\:/Windows/Fonts/arial.ttf'"
W, H, FPS, SHOT_SECONDS = 540, 960, 25, 3

SHOTS = [
    # (主色, 屏上文字, 正弦频率 Hz, 文字颜色)
    # 注意：本机 ffmpeg 的 drawtext 会把裸 % 当文本扩展序列起始并静默输出
    # 空文本——样例文案避免使用 %。
    ("0x8a1f2f", "HALF PRICE SALE", 440, "white"),
    ("0x1f3a8a", "NEW PRODUCT", 660, "white"),
    ("0x1f6b3a", "DAY 7 RESULT", 880, "white"),
    ("0x5a2a7a", "BUY NOW", 220, "yellow"),
]


def _run(command: list[str]) -> None:
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(
            f"command failed: {' '.join(command[:6])}...\n{completed.stderr[-800:]}"
        )


def build_video(out_dir: Path) -> Path:
    shot_paths: list[Path] = []
    for index, (color, text, freq, text_color) in enumerate(SHOTS, start=1):
        shot_path = out_dir / f"_shot{index}.mp4"
        # drawtext 文本扩展里 % 是转义字符（%% → %），不转义会静默吞字
        text_escaped = text.replace("%", "%%").replace(":", r"\:").replace("'", r"\'")
        vf = (
            f"drawtext=fontfile={FONT}:text='{text_escaped}':fontsize=60:"
            f"fontcolor={text_color}:x=(w-tw)/2:y=(h-th)/2:borderw=3:bordercolor=black,"
            "zoompan=z='min(1+0.002*on,1.6)':d=1:s="
            f"{W}x{H}:fps={FPS}"
        )
        _run(
            [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", f"color=c={color}:s={W}x{H}:d={SHOT_SECONDS}:r={FPS}",
                "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={SHOT_SECONDS}",
                "-vf", vf,
                "-af", "volume=0.4",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                "-shortest",
                str(shot_path),
            ]
        )
        shot_paths.append(shot_path)

    concat_list = out_dir / "_concat.txt"
    concat_list.write_text(
        "\n".join(f"file '{p.as_posix()}'" for p in shot_paths), encoding="utf-8"
    )
    final = out_dir / "sample_ad_4shots.mp4"
    _run(
        [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
            "-c", "copy", str(final),
        ]
    )
    for shot in shot_paths:
        shot.unlink()
    concat_list.unlink()
    return final


def build_images(out_dir: Path) -> tuple[Path, Path]:
    product = out_dir / "sample_product.png"
    _run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "gradients=s=800x800:c0=0x22223a:c1=0x6a5acd:d=1",
            "-vf", (
                f"drawtext=fontfile={FONT}:text='PRODUCT':fontsize=72:"
                "fontcolor=white:x=(w-tw)/2:y=(h-th)/2:borderw=3:bordercolor=black"
            ),
            "-frames:v", "1", str(product),
        ]
    )
    host = out_dir / "sample_host.png"
    _run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "gradients=s=800x800:c0=0x3a2a1a:c1=0xd2a679:d=1",
            "-vf", (
                f"drawbox=x=300:y=200:w=200:h=200:color=white@0.9:t=fill,"
                f"drawbox=x=340:y=120:w=120:h=120:color=white@0.9:t=fill,"
                f"drawtext=fontfile={FONT}:text='HOST':fontsize=48:"
                "fontcolor=white:x=(w-tw)/2:y=640:borderw=3:bordercolor=black"
            ),
            "-frames:v", "1", str(host),
        ]
    )
    return product, host


BRIEF = """复刻目标：换商品不换结构。
原片是一条 12 秒的四段式促销广告：折扣钩子（HALF PRICE SALE）→ 新品展示
（NEW PRODUCT）→ 效果证明（DAY 7 RESULT）→ 行动号召（BUY NOW）。
要求：保留镜头顺序与节奏，屏上文字改为新商品卖点，人物与商品替换为
资产库中的样例（sample_host.png / sample_product.png），结尾 CTA 保留。
"""

HANDWRITTEN_ADREPLICA = """<advideo version="1" kind="replica-blueprint" aspect="9:16" duration="12">
  <meta source="" format="handwritten-sample">
    <goal>手写样例：验证导入重编译路径</goal>
    <reading>四段式促销结构，屏上文字驱动。</reading>
  </meta>
  <cast>
    <slot kind="character" label="人物" source="原片主播" replace-with="sample_host.png" />
    <slot kind="product" label="商品" source="原片商品" replace-with="sample_product.png" />
    <slot kind="script" label="台词" source="" replace-with="" />
    <slot kind="style" label="风格" source="" replace-with="" />
    <slot kind="voice" label="声音" source="" replace-with="" />
  </cast>
  <script>
    <beat id="b1" role="hook" dur="0-3">折扣钩子</beat>
    <beat id="b2" role="proof" dur="3-6">新品展示</beat>
  </script>
  <timeline>
    <shot id="s1" size="medium" motion="zoom-in" start="0" dur="3" cut="cut" text="HALF PRICE SALE" recreate="" during="b1">折扣字幕铺满画面</shot>
    <shot id="s2" size="closeup" motion="static" start="3" dur="3" cut="cut" text="" recreate="同机位换商品" during="b2">商品特写</shot>
  </timeline>
  <events>
    <caption id="b1_caption" during="b1" trigger="折扣词" keep="true">SALE 字样全程挂字幕</caption>
    <sfx id="b2_whoosh" during="b2" trigger="商品出场" keep="true">出场 whoosh</sfx>
  </events>
  <rhythm avg-shot="3" curve="平直" cuts="0,3" />
  <systems captions="底部大字" music="促销电子">
    <graphics>价格贴：提到折扣时弹入</graphics>
  </systems>
  <constraints>
    <constraint>手写样例文档，仅用于导入路径验证</constraint>
  </constraints>
</advideo>
"""


def main() -> None:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    out_dir.mkdir(parents=True, exist_ok=True)
    video = build_video(out_dir)
    product, host = build_images(out_dir)
    (out_dir / "sample_brief.txt").write_text(BRIEF, encoding="utf-8")
    (out_dir / "sample_handwritten.adreplica").write_text(
        HANDWRITTEN_ADREPLICA, encoding="utf-8"
    )
    print(f"samples written to {out_dir}:")
    for path in (video, product, host):
        print(f"  {path.name}  {path.stat().st_size} bytes")


if __name__ == "__main__":
    main()
