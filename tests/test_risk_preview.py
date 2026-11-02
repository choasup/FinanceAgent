"""仓位风控页的纯预览助手。不启动 Streamlit，不连接券商。"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import position_agent.preview as preview
from position_agent.core import QueueBroker
from position_agent.preview import (
    limits_from_values,
    preview_demo,
    preview_kill,
    preview_pingan_unconfigured,
    preview_targets,
)
from quant.execution import route_targets


class RiskPreviewTests(unittest.TestCase):
    def test_route_targets_is_the_execution_entrypoint(self):
        self.assertIs(preview.route_targets, route_targets)

    def test_advice_passes_without_queueing(self):
        calls = []
        real = QueueBroker.submit

        def wrapped(self, order):
            calls.append(order.id)
            return real(self, order)

        with patch.object(QueueBroker, "submit", wrapped):
            rows = preview_targets(
                {"AAPL": "0.20"},
                mode="advice",
                equity="10000",
                prices={"AAPL": "100"},
            )
        self.assertEqual(calls, [])
        self.assertEqual(rows[0]["mode"], "advice")
        self.assertEqual(rows[0]["symbol"], "AAPL")
        self.assertEqual(rows[0]["weight"], "0.20")
        self.assertEqual(rows[0]["size"], "20")
        self.assertEqual(rows[0]["state"], "validated")
        self.assertEqual(rows[0]["codes"], [])
        self.assertTrue(rows[0]["passed"])
        self.assertFalse(rows[0]["queued_local"])

    def test_auto_enqueues_local_queue_only(self):
        calls = []
        real = QueueBroker.submit

        def wrapped(self, order):
            calls.append(order.id)
            return real(self, order)

        with patch("position_agent.preview.route_targets", wraps=route_targets) as routed:
            with patch.object(QueueBroker, "submit", wrapped):
                rows = preview_targets(
                    {"AAPL": "0.20"},
                    mode="auto",
                    equity="10000",
                    prices={"AAPL": "100"},
                )
        self.assertEqual(len(calls), 1)
        self.assertIsNone(routed.call_args.kwargs["broker"])
        self.assertNotIn("allow_live", routed.call_args.kwargs)
        self.assertEqual(rows[0]["state"], "submitted")
        self.assertTrue(rows[0]["queued_local"])
        self.assertEqual(rows[0]["codes"], [])

    def test_tighter_limit_is_enforced_by_gate(self):
        limits = limits_from_values("100", "1", "0.10", "500")
        rows = preview_targets(
            {"AAPL": "0.20"},
            mode="advice",
            equity="10000",
            prices={"AAPL": "100"},
            limits=limits,
        )
        self.assertEqual(rows[0]["state"], "rejected")
        self.assertIn("MAX_SYMBOL_WEIGHT", rows[0]["codes"])
        self.assertFalse(rows[0]["queued_local"])
        with self.assertRaises(ValueError):
            limits_from_values("0", "1", "0.25", "500")

    def test_overweight_rejected_with_gate_code(self):
        calls = []

        def wrapped(self, order):
            calls.append(order.id)
            raise AssertionError("rejected orders must not reach the broker")

        with patch.object(QueueBroker, "submit", wrapped):
            rows = preview_targets(
                {"MSFT": "0.50"},
                mode="auto",
                equity="10000",
                prices={"MSFT": "200"},
            )
        self.assertEqual(calls, [])
        self.assertEqual(rows[0]["state"], "rejected")
        self.assertIn("MAX_SYMBOL_WEIGHT", rows[0]["codes"])
        self.assertFalse(rows[0]["passed"])
        self.assertFalse(rows[0]["queued_local"])

    def test_demo_matches_paper_signals(self):
        rows = preview_demo("advice")
        self.assertEqual([row["symbol"] for row in rows], ["AAPL", "MSFT"])
        self.assertEqual(rows[0]["state"], "validated")
        self.assertEqual(rows[0]["weight"], "0.20")
        self.assertEqual(rows[1]["state"], "rejected")
        self.assertIn("MAX_SYMBOL_WEIGHT", rows[1]["codes"])
        self.assertTrue(all(not row["queued_local"] for row in rows))

    def test_kill_rejects_everything(self):
        rows = preview_demo("kill")
        self.assertGreaterEqual(len(rows), 2)
        self.assertTrue(all(row["state"] == "rejected" for row in rows))
        self.assertTrue(all("KILL_SWITCH" in row["codes"] for row in rows))
        self.assertTrue(all(not row["queued_local"] for row in rows))

        killed = preview_kill(
            {"AAPL": "0.20"},
            equity="10000",
            prices={"AAPL": "100"},
            allow_live=True,
            broker="futu",
        )
        self.assertEqual(killed[0]["mode"], "kill")
        self.assertEqual(killed[0]["state"], "rejected")
        self.assertIn("KILL_SWITCH", killed[0]["codes"])
        self.assertFalse(killed[0]["queued_local"])

    def test_confirm_waits_without_submit(self):
        calls = []
        real = QueueBroker.submit

        def wrapped(self, order):
            calls.append(order.id)
            return real(self, order)

        with patch.object(QueueBroker, "submit", wrapped):
            rows = preview_targets(
                {"AAPL": "0.20"},
                mode="confirm",
                equity="10000",
                prices={"AAPL": "100"},
            )
        self.assertEqual(calls, [])
        self.assertEqual(rows[0]["state"], "pending_confirm")
        self.assertTrue(rows[0]["passed"])
        self.assertFalse(rows[0]["queued_local"])

    def test_pingan_without_bridge(self):
        sentinel = "http://127.0.0.1:9/bridge"
        with patch.dict(os.environ, {"PINGAN_QMT_BRIDGE_URL": sentinel}):
            with patch("position_agent.brokers.pingan.urlopen") as opened:
                rows = preview_pingan_unconfigured()
            opened.assert_not_called()
            self.assertEqual(os.environ.get("PINGAN_QMT_BRIDGE_URL"), sentinel)
        self.assertEqual(rows[0]["symbol"], "AAPL")
        self.assertEqual(rows[0]["state"], "rejected")
        self.assertIn("BROKER_NOT_CONFIGURED", rows[0]["codes"])
        self.assertFalse(rows[0]["queued_local"])

    def test_console_page_is_wired_without_live_switches(self):
        app = Path(__file__).resolve().parents[1].joinpath("app.py").read_text(encoding="utf-8")
        preview = Path(__file__).resolve().parents[1].joinpath("position_agent", "preview.py").read_text(encoding="utf-8")
        self.assertIn("仓位风控", app)
        self.assertIn("render_position_risk", app)
        for banned in ("allow_live", "FUTU_TRD_ENV", "LONGBRIDGE_PAPERTRADING", "FUTU REAL"):
            self.assertNotIn(banned, app)
        self.assertNotIn("allow_live=True", preview)
        self.assertNotIn("FUTU_TRD_ENV", preview)
        self.assertNotIn("LONGBRIDGE_PAPERTRADING", preview)


if __name__ == "__main__":
    unittest.main()
