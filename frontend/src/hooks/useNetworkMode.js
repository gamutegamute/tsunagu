import { useEffect, useRef, useState } from "react";

/**
 * 通信状態(通常 / オフライン / 非常時)を管理するフック。
 *
 * 「通常」「オフライン」は、ブラウザの online/offline イベントに連動して自動で切り替わる。
 * 「非常時」はイベントでは自動的に切り替わらず、手動(ヘッダーのボタン)でのみ選択する
 * 想定になっている(検討中の項目A: 自動切り替え条件は未確定のため、現状は手動)。
 *
 * オンラインに復帰したタイミングで呼びたい処理(保留中の報告の再送など)は
 * onBackOnline に渡す。再レンダーのたびに新しい関数が渡されても最新のものを
 * 呼べるよう ref に保持している(useEffect の依存配列を空のままにするため)。
 */
export function useNetworkMode(onBackOnline) {
  const [networkMode, setNetworkMode] = useState(navigator.onLine ? "normal" : "offline");

  const onBackOnlineRef = useRef(onBackOnline);
  onBackOnlineRef.current = onBackOnline;

  useEffect(() => {
    function handleOnline() {
      setNetworkMode("normal");
      onBackOnlineRef.current();
    }
    function handleOffline() {
      setNetworkMode("offline");
    }

    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, []);

  return [networkMode, setNetworkMode];
}
