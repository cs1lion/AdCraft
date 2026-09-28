# 素材来源与许可（SOURCES）

> 建立：2026-09-28
> 用途：实机演示素材的可追溯来源记录。
> **纪律**：任何新增素材必须先登记到这里，`license` 列不得留空或写"待定"就投入演示。

---

## 1. 网络可达性实测（本机，2026-09-28）

选素材前先看这张表——**不是所有素材站都可达**，避免下次白跑。

| 站点 | 结果 | 说明 |
|---|---|---|
| `test-videos.co.uk` | ✅ 200 | 可下载，真实剪辑结构的开源短片片段 |
| `download.samplelib.com` | ✅ 200 | 可下载，高码率样片，**下载慢**（5.5MB 约需 4–5 分钟） |
| `picsum.photos` | ✅ 200 | 可下载，真实照片，支持 `?seed=` 固定种子 |
| `placehold.co` | ✅ 200 | 占位图，可作降级方案 |
| `dummyimage.com` | ✅ 200 | 占位图 |
| `images.unsplash.com` | ✅ 200（首页） | 具体图片 URL 未验证 |
| `videos.pexels.com` | ❌ 403 | 被拒 |
| `cdn.pixabay.com` | ❌ 403 | 被拒 |
| `commons.wikimedia.org` | ❌ 超时 | 不可达 |
| `upload.wikimedia.org` | ❌ 超时 | 不可达 |
| `archive.org` | ❌ 超时 | 不可达 |
| `youtube.com` | ❌ 超时 | 不可达 |

**推论**：本机处于受限网络环境，**不要在计划里依赖 Wikimedia / archive.org / YouTube**。
需要更多素材时，优先走 `test-videos.co.uk` 与 `picsum.photos`。

---

## 2. 视频素材（`videos/replica-reference/`）

| 文件 | 来源 URL | 规格（ffprobe 实测） | 音轨 | license | 确认状态 |
|---|---|---|---|---|---|
| `bigbuckbunny-720p-10s.mp4` | `https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/720/Big_Buck_Bunny_720_10s_1MB.mp4` | 1280×720 / 10.0s / 969 KB | ❌ 无 | 见下注 | ⚠️ 待确认 |
| `bigbuckbunny-360p-10s.mp4` | `https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/360/Big_Buck_Bunny_360_10s_1MB.mp4` | 640×360 / 10.0s / 991 KB | ❌ 无 | 见下注 | ⚠️ 待确认 |
| `jellyfish-360p-10s.mp4` | `https://test-videos.co.uk/vids/jellyfish/mp4/h264/360/Jellyfish_360_10s_1MB.mp4` | 640×360 / 10.0s / 1.05 MB | ❌ 无 | 见下注 | ⚠️ 待确认 |
| `samplelib-10s.mp4` | `https://download.samplelib.com/mp4/sample-10s.mp4` | 1920×1080 / 10.2s / 5.49 MB | ✅ 有 | 见下注 | ⚠️ 待确认 |
| `samplelib-5s.mp4` | `https://download.samplelib.com/mp4/sample-5s.mp4` | 1920×1080 / 5.8s / 2.85 MB | ✅ 有 | 见下注 | ⚠️ 待确认 |

> **注（许可）**：
> - Big Buck Bunny / Jellyfish 是 Blender Foundation 开源电影片段，通常为 **CC-BY**，
>   但本次未能访问 `commons.wikimedia.org` 核对原始许可页 → **对外使用前必须人工确认**。
> - SampleLib 站点声明样片可自由使用，但其**商用条款未逐条核对**。
> - **内部技术演示**用途风险低；**对外发布/商用前必须完成确认**。
> - 若需要绝对干净的许可素材，仓库内 `test-materials/` 有全部 ffmpeg 合成的零版权素材，
>   可作为兜底。

### 各视频的演示用途

| 文件 | 适合验什么 |
|---|---|
| `bigbuckbunny-720p-10s.mp4` | **首选拉片复刻输入**：真实动画短片，有真实运镜与剪辑节奏，拆解报告可读性最好 |
| `bigbuckbunny-360p-10s.mp4` | 同片低分辨率版 → 验分辨率差分下的拆解稳定性 |
| `jellyfish-360p-10s.mp4` | 水下高饱和画面 → 验色彩分析；与 BBB 形成风格对照 |
| `samplelib-5s.mp4` | 1080p 短片 → L0 冒烟/快速冒烟（5 秒，最省时间） |
| `samplelib-10s.mp4` | 1080p **带音轨** → 验「参考视频带声音」的转录与拆解路径 |

> 🔴 **注意**：BBB / Jellyfish 三条**都没有音轨**。这正好覆盖"静音参考视频"场景
> （对应 `test-materials/fixtures/videos/rep_silent_16x9_8s.mp4` 的真实版本），
> 但若要验词级转录路径，**必须用 `samplelib-10s.mp4`**。

---

## 3. 图片素材（`images/`）

来源：`https://picsum.photos/seed/<seed>/<w>/<h>`（Lorem Picsum，图片源自 Unsplash）

| 文件 | 分类 | 尺寸 | 大小 | seed |
|---|---|---|---|---|
| `product/product-bottle-01.jpg` | 商品 | 768×1024 | 116 KB | `adcraft-product-01` |
| `product/product-bottle-02.jpg` | 商品 | 768×1024 | 90 KB | `adcraft-product-02` |
| `product/product-box-03.jpg` | 商品 | 1024×768 | 98 KB | `adcraft-product-03` |
| `character/character-01.jpg` | 角色 | 768×1024 | 38 KB | `adcraft-char-01` |
| `character/character-02.jpg` | 角色 | 768×1024 | 38 KB | `adcraft-char-02` |
| `scene/scene-indoor-01.jpg` | 场景 | 1280×720 | 90 KB | `adcraft-scene-01` |
| `scene/scene-street-02.jpg` | 场景 | 1280×720 | 70 KB | `adcraft-scene-02` |
| `scene/scene-closeup-03.jpg` | 场景特写 | 1280×720 | 77 KB | `adcraft-scene-03` |

| 许可 | 确认状态 |
|---|---|
| Lorem Picsum 使用 Unsplash 图片，Unsplash License 允许免费使用（含商用），需保留作者署名信息 | ⚠️ 具体作者未记录，对外发布前需补 |

> **固定 seed 的意义**：同一 seed 永远返回同一张图，演示可复现。
> 不要在演示当天换 seed，否则两次演示素材不一致、无法对比。

---

## 4. 文案脚本（`scripts/`）

全部原创虚构，见 `scripts/README.md`。无第三方依赖。

---

## 5. 音频（`audio/`）

**当前为空。**

需要时可用 `test-materials/fixtures/audio/` 中 ffmpeg 合成的节拍轨
（120/90/140/60 BPM + 静音 + 过短负例），它们是零版权且带机器可读真值
（`test-materials/truth.json`），比下载的真实音乐更适合自动化断言。

---

## 6. 下载脚本（可复现）

```powershell
# 视频
$d = "demo-materials/videos/replica-reference"
curl.exe -L -o "$d/bigbuckbunny-720p-10s.mp4" "https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/720/Big_Buck_Bunny_720_10s_1MB.mp4"
curl.exe -L -o "$d/bigbuckbunny-360p-10s.mp4" "https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/360/Big_Buck_Bunny_360_10s_1MB.mp4"
curl.exe -L -o "$d/jellyfish-360p-10s.mp4"       "https://test-videos.co.uk/vids/jellyfish/mp4/h264/360/Jellyfish_360_10s_1MB.mp4"
curl.exe -L --max-time 480 -o "$d/samplelib-10s.mp4" "https://download.samplelib.com/mp4/sample-10s.mp4"
curl.exe -L --max-time 480 -o "$d/samplelib-5s.mp4"  "https://download.samplelib.com/mp4/sample-5s.mp4"

# 图片（seed 必须与本表一致）
curl.exe -L -o "demo-materials/images/product/product-bottle-01.jpg" "https://picsum.photos/seed/adcraft-product-01/768/1024"
# ... 其余同理
```

**踩坑记录**：
1. `samplelib` 站点**不支持断点续传**（`curl -C -` 无效），大文件必须一次性下完，超时要从头再来。
2. 本机网络偏慢，5.5 MB 文件实测需 4–5 分钟；下载后**务必用 ffprobe 校验**，
   截断文件的特征是 `moov atom not found`。
