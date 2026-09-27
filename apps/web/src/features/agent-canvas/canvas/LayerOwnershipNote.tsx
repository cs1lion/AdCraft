/**
 * LayerOwnershipNote — the two locks, said out loud (V0.2 §14.13).
 *
 * The audio layer and the visual layer each own a channel, and a redo of one
 * cannot silently damage the other:
 *
 * - Audio (the mouth): the dialogue drives it. Re-applying lip-sync takes
 *   over the ACTION channel only — positions and facings survive (they
 *   inherit the interpolated pose, so the authored motion is untouched).
 * - Visual (the body): blocking and camera presets drive it. A frame inside
 *   a speech window keeps ``talk`` — the character walks WHILE talking, so a
 *   visual redo can never close the mouth.
 *
 * The protection is structural; this note makes it VISIBLE, because a lock
 * nobody knows about is indistinguishable from no lock. Where the author
 * wants to change something is also stated: change when the mouth opens by
 * re-doing the audio layer; change the motion by re-doing the visual one.
 */

export function LayerOwnershipNote() {
  return (
    <div className="layer-ownership" data-testid="layer-ownership-note">
      <span className="layer-ownership__title">层所有权（V0.2 §14.13）</span>
      <ul>
        <li data-testid="layer-ownership-audio">
          <strong>Audio 层（嘴）</strong>：台词驱动。重应用唇形只接管说话动作，
          位置与朝向原样保留——你的走位不会被踩碎。
        </li>
        <li data-testid="layer-ownership-visual">
          <strong>Visual 层（身体）</strong>：走位与运镜预设驱动。落在说话窗内的帧
          保留说话动作——边走边说，重排走位不会把嘴闭上。
        </li>
        <li data-testid="layer-ownership-redo">
          要改开口时机，重做 Audio 层（重应用唇形）；要改运动，重做 Visual 层
          （应用走位/运镜预设）。两层互不偷袭。
        </li>
      </ul>
    </div>
  );
}
