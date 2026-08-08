import os
import sys

from app.config import get_settings
from app.db import reset_demo_dataset


def main() -> None:
    settings = get_settings()

    if settings.app_env == "production":
        print(
            "拒否: APP_ENV=production ではデモデータのリセットを実行できません。",
            file=sys.stderr,
        )
        sys.exit(1)

    if os.getenv("DEMO_SEED", "false").lower() != "true":
        print(
            "拒否: DEMO_SEED=true が設定されていないため、リセット後にデモデータが再投入されません。"
            " 実行前に環境変数 DEMO_SEED=true を設定してください。",
            file=sys.stderr,
        )
        sys.exit(1)

    reset_demo_dataset()
    print("デモデータをリセットしました(shelters/observations/emergency_packetsを初期化し、デモデータを再投入)。")


if __name__ == "__main__":
    main()
