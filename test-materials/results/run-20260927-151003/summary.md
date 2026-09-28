# 测试运行 run-20260927-151003

- 时间：2026-09-27T15:10:03.238705+00:00
- 后端：http://127.0.0.1:8000（local 套件不依赖）
- 结果：**PASS 40 / FAIL 0 / SKIP 0**
- 退出码：0

| 用例 | 套件 | 状态 | 耗时 | 标题 | 说明 |
|---|---|---|---|---|---|
| MD-01 | media | PASS | 0.13s | 视频真值校验 rep_fastcut_9x16_15s.mp4 | {"duration": 15.02322, "size": "540x960", "audio": true} |
| MD-02 | media | PASS | 0.13s | 视频真值校验 rep_luxury_16x9_30s.mp4 | {"duration": 30.02322, "size": "1280x720", "audio": true} |
| MD-03 | media | PASS | 0.12s | 视频真值校验 rep_dialogue_9x16_20s.mp4 | {"duration": 20.02322, "size": "540x960", "audio": true} |
| MD-04 | media | PASS | 0.13s | 视频真值校验 rep_textonly_1x1_10s.mp4 | {"duration": 10.02322, "size": "720x720", "audio": true} |
| MD-05 | media | PASS | 0.12s | 视频真值校验 rep_action_9x16_12s.mp4 | {"duration": 12.02322, "size": "540x960", "audio": true} |
| MD-06 | media | PASS | 0.12s | 视频真值校验 rep_silent_16x9_8s.mp4 | {"duration": 8.0, "size": "640x360", "audio": false} |
| MD-07 | media | PASS | 0.12s | 视频真值校验 rep_edge_4s_9x16.mp4 | {"duration": 4.02322, "size": "360x640", "audio": true} |
| MD-08 | media | PASS | 0.13s | 视频真值校验 rep_overlong_16x9_61s.mp4 | {"duration": 61.0, "size": "320x180", "audio": false} |
| MD-09 | media | PASS | 0.12s | 视频真值校验 rep_compare_9x16_16s.mp4 | {"duration": 16.02322, "size": "540x960", "audio": true} |
| MD-10 | media | PASS | 0.13s | 视频真值校验 rep_vlogtour_9x16_18s.mp4 | {"duration": 18.02322, "size": "540x960", "audio": true} |
| MD-11 | media | PASS | 0.12s | 视频真值校验 rep_tutorial_1x1_16s.mp4 | {"duration": 16.02322, "size": "720x720", "audio": true} |
| MD-12 | media | PASS | 0.13s | 视频真值校验 rep_beatsync_9x16_16s.mp4 | {"duration": 16.0, "size": "540x960", "audio": true} |
| MD-13 | media | PASS | 0.12s | 视频真值校验 s3d_refroom_16x9_8s.mp4 | {"duration": 8.0, "size": "960x540", "audio": true} |
| MD-14 | media | PASS | 0.12s | 视频真值校验 slice_ref_16x9_40s.mp4 | {"duration": 40.02322, "size": "480x270", "audio": true} |
| MD-I01 | media | PASS | 0.12s | 图片尺寸校验 s3d_room_800x600.png | "800x600" |
| MD-I02 | media | PASS | 0.12s | 图片尺寸校验 s3d_panorama_2048x1024.png | "2048x1024" |
| MD-I03 | media | PASS | 0.13s | 图片尺寸校验 s3d_corridor_depth_800x600.png | "800x600" |
| MD-I04 | media | PASS | 0.11s | 图片尺寸校验 ref_product_3x4_768x1024.png | "768x1024" |
| MD-I05 | media | PASS | 0.12s | 图片尺寸校验 ref_turnaround_3view_1536x512.png | "1536x512" |
| MD-I06 | media | PASS | 0.11s | 图片尺寸校验 ref_ultrawide_1024x288.png | "1024x288" |
| MD-I07 | media | PASS | 0.13s | 图片尺寸校验 s3d_orbit_1_512x512.png | "512x512" |
| MD-I08 | media | PASS | 0.12s | 图片尺寸校验 s3d_orbit_2_512x512.png | "512x512" |
| MD-I09 | media | PASS | 0.12s | 图片尺寸校验 s3d_orbit_3_512x512.png | "512x512" |
| MD-I10 | media | PASS | 0.12s | 图片尺寸校验 s3d_orbit_4_512x512.png | "512x512" |
| MD-I11 | media | PASS | 0.13s | 图片尺寸校验 s3d_orbit_5_512x512.png | "512x512" |
| MD-I12 | media | PASS | 0.12s | 图片尺寸校验 s3d_orbit_6_512x512.png | "512x512" |
| AD-01 | adreplica | PASS | 0.75s | 3 个正例导入并落槽正确 | {"valid_luxury_16x9.adreplica": {"slots": 6, "beats": 4, "applied": 3}, "valid_textonly_1x1.adreplica": {"slots": 6, "be |
| AD-02 | adreplica | PASS | 0.0s | 导出→再解析往返锁定 | "parse→export→parse 幂等" |
| AD-03 | adreplica | PASS | 0.0s | 反例被拒 invalid_hypit_host_slot.adreplica | "Unknown slot kind 'host' (known: character, product, script, style, voice, scene)" |
| AD-04 | adreplica | PASS | 0.0s | 反例被拒 invalid_ghost_anchor.adreplica | "Inline anchor @{gcap1} references unknown event" |
| AD-05 | adreplica | PASS | 0.0s | 反例被拒 invalid_unknown_event.adreplica | "Unknown event element <stinger> (known: broll, caption, sfx, mg, transition)" |
| AD-06 | adreplica | PASS | 0.0s | 反例被拒 invalid_version_2.adreplica | "Unsupported .adreplica version: '2' (supported: 1)" |
| BT-01 | beats | PASS | 0.32s | 节拍检测真值 beat_120bpm_20s.wav | "bpm=120.2 conf=1.0 beats=41" |
| BT-02 | beats | PASS | 0.15s | 节拍检测真值 beat_90bpm_20s.wav | "bpm=90.7 conf=1.0 beats=31" |
| BT-03 | beats | PASS | 0.16s | 节拍检测真值 beat_140bpm_accent_30s.wav | "bpm=139.7 conf=1.0 beats=71" |
| BT-04 | beats | PASS | 0.16s | 节拍检测真值 beat_60bpm_20s.wav | "bpm=60.1 conf=1.0 beats=21" |
| BT-05 | beats | PASS | 0.16s | 节拍检测真值 beat_170bpm_20s.wav | "bpm=84.7 conf=1.0 beats=29" |
| BT-06 | beats | PASS | 0.15s | 变速轨不崩溃且不误报真值 | "bpm=74.9" |
| BT-07 | beats | PASS | 0.13s | 过短轨报 too_short（<2s 下限） | "Audio must be at least 2 seconds for beat analysis." |
| BT-08 | beats | PASS | 0.14s | 静音轨报无稳定节拍 | "Could not detect a steady beat in the audio." |
