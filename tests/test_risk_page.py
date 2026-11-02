"""Streamlit 仓位风控页接线。没有装 streamlit 时跳过。"""

from __future__ import annotations

import unittest
from pathlib import Path

try:
    from streamlit.testing.v1 import AppTest
except ImportError:  # pragma: no cover
    AppTest = None

APP = Path(__file__).resolve().parents[1] / "app.py"


def _open_risk():
    app = AppTest.from_file(APP, default_timeout=40)
    app.run()
    app.sidebar.radio[0].set_value("🛡️ 仓位风控")
    app.run()
    return app


def _click(app, label: str) -> None:
    for button in app.button:
        if button.label == label:
            button.click()
            return
    raise AssertionError(f"missing button {label}")


@unittest.skipIf(AppTest is None, "streamlit is not installed")
class RiskPageTests(unittest.TestCase):
    def test_three_blocks_preview_kill_and_pingan(self):
        app = _open_risk()
        self.assertFalse(list(app.exception))
        titles = [item.value for item in app.subheader]
        self.assertEqual(
            titles,
            ["1. 设定规则 / 模式", "2. 模拟下单预览", "3. 一键 Kill"],
        )

        _click(app, "预览通过 / 拒绝")
        app.run()
        self.assertFalse(list(app.exception))
        frame = app.dataframe[0].value
        self.assertEqual(list(frame["结果"]), ["通过", "拒绝"])
        self.assertEqual(list(frame["状态"]), ["validated", "rejected"])
        self.assertIn("MAX_SYMBOL_WEIGHT", frame.loc[1, "issues.code"])
        self.assertNotIn("submitted", list(frame["状态"]))

        _click(app, "拒绝全部")
        app.run()
        self.assertFalse(list(app.exception))
        killed = app.dataframe[0].value
        self.assertTrue((killed["结果"] == "拒绝").all())
        self.assertTrue(killed["issues.code"].str.contains("KILL_SWITCH").all())
        self.assertTrue((killed["模式"] == "kill").all())

        _click(app, "演示平安未配置桥")
        app.run()
        self.assertFalse(list(app.exception))
        pingan = app.dataframe[-1].value
        self.assertIn("BROKER_NOT_CONFIGURED", pingan.loc[0, "issues.code"])
        self.assertEqual(pingan.loc[0, "状态"], "rejected")


if __name__ == "__main__":
    unittest.main()
