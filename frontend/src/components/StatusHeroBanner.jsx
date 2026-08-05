/**
 * オフラインのときだけ表示する、状況説明バナー(決定事項29)。通常時は何も表示しない。
 *
 * 画面上のモードは「通常」「オフライン」の2つに統合されている。クラウド版アプリは
 * 通信状態の検知と案内表示までを担当し、実際のLoRa送信はT-Beam専用ページ
 * (決定事項28、このアプリとは別サイト)が担当するため、送信ボタン・送信処理は
 * ここには実装しない。オフライン中は以下の2段階を出し分ける:
 *   1. retrying: 「オフラインを検知しています」(0〜10秒、通常のAPI再試行中)
 *   2. lora-available: T-Beamの非常用Wi-Fiへの案内メッセージ(10秒経過後)
 */
export default function StatusHeroBanner({ networkMode, offlinePhase }) {
  if (networkMode !== "offline") return null;

  if (offlinePhase !== "lora-available") {
    return (
      <div className="status-hero offline">
        <strong>オフラインを検知しています</strong>
        <span>通常のAPIへの再接続を試みています。復旧すればそのまま通常状態に戻ります。</span>
      </div>
    );
  }

  return (
    <div className="status-hero offline lora-phase">
      <strong>オフラインです</strong>
      <span>
        緊急の場合はT-Beamの非常用Wi-Fi(TSUNAGU-Emergency)に接続し、別画面から報告してください。
      </span>
    </div>
  );
}
