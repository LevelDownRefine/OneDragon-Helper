"""助手独立更新器入口；应用规则随冻结的入口提供。"""

from updater.worker import main

from src.update.policy import POLICY

if __name__ == "__main__":
    raise SystemExit(main(POLICY))
