/**
 * 「非常時の最低限情報」パネル。
 * 直前に非常時パケットを組み立てた場合はその1件を、そうでなければ
 * これまでのEmergency Packets一覧(JSON)を表示する。
 */
export default function PacketsPanel({ lastPacket, emergencyPackets }) {
  return (
    <section className="panel packets-panel">
      <h2>非常時の最低限情報</h2>
      {lastPacket && <pre>{lastPacket}</pre>}
      {!lastPacket && <pre>{JSON.stringify(emergencyPackets, null, 2) || "送信履歴はまだありません。"}</pre>}
    </section>
  );
}
