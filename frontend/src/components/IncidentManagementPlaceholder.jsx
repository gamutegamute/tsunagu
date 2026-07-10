/**
 * 「インシデント管理」タブの中身。
 * 対応確認・承認フローはまだこのアプリに実装されていないため、
 * タブの切り替え自体は動くが、中身は準備中である旨だけを表示している。
 */
export default function IncidentManagementPlaceholder() {
  return (
    <div className="incident-placeholder">
      <p>インシデント管理機能は準備中です。</p>
      <p className="incident-placeholder-note">
        現場からの「対応済みにする」申請の確認・承認フローは、今後のアップデートで実装予定です。
      </p>
    </div>
  );
}
