import { Link } from "react-router-dom";

/**
 * Field Reportヘッダーに置く、送信履歴・インシデントへの控えめな導線(決定事項22)。
 * 常時表示の下部タブのような大掛かりな構成は避け、アイコンボタンのみとする。
 */
export default function FieldReportNavButtons() {
  return (
    <div className="field-report-nav-buttons">
      <Link to="/history" className="icon-nav-button" aria-label="送信履歴">
        🕘
      </Link>
      <Link to="/incident" className="icon-nav-button" aria-label="インシデント">
        ⚠
      </Link>
    </div>
  );
}
