import unittest

from backtester.engine import Bar, backtest


class EngineTests(unittest.TestCase):
    def bars(self, prices):
        return [Bar("2025-01-{:02d}".format(i + 1), p, p) for i, p in enumerate(prices)]

    def test_signal_fills_at_next_open(self):
        bars = self.bars([10, 11, 12, 13, 9, 8])
        _, _, trades = backtest(bars, fast=1, slow=2, commission=0, slippage_ticks=0)
        self.assertEqual([(t["date"], t["side"], t["price"]) for t in trades],
                         [("2025-01-03", "BUY", 12), ("2025-01-06", "SELL", 8)])

    def test_future_prices_cannot_change_earlier_results(self):
        bars = self.bars([10, 11, 12, 13, 14, 15])
        changed = bars[:4] + [Bar("2025-01-05", 100, 100), Bar("2025-01-06", 1, 1)]
        _, first, _ = backtest(bars, fast=1, slow=2)
        _, second, _ = backtest(changed, fast=1, slow=2)
        self.assertEqual(first[:4], second[:4])

    def test_costs_are_charged_on_entry_and_exit(self):
        bars = self.bars([10, 11, 12, 13, 9, 8])
        summary, _, trades = backtest(bars, fast=1, slow=2, initial_cash=1000,
                                     commission=2, slippage_ticks=1, multiplier=10, tick_size=0.25, margin_per_contract=100)
        expected_cash = 1000 + (8 - 12) * 10 - 2 * (2 + 0.25 * 10)
        self.assertAlmostEqual(summary["final_equity"], expected_cash)
        self.assertEqual(len(trades), 2)

    def test_flat_market_stays_in_cash(self):
        summary, _, trades = backtest(self.bars([10] * 6), fast=1, slow=2)
        self.assertEqual(summary["total_return"], 0)
        self.assertEqual(summary["max_drawdown"], 0)
        self.assertIsNone(summary["sharpe_zero_risk_free"])
        self.assertEqual(trades, [])

    def test_gap_profit_and_open_position_marked_to_market(self):
        bars = self.bars([10, 11, 12, 13])
        bars[-1] = Bar("2025-01-04", 20, 21)
        summary, _, _ = backtest(bars, fast=1, slow=2, multiplier=10,
                                commission=0, slippage_ticks=0)
        self.assertEqual(summary["final_equity"], 100000 + (21 - 12) * 10)
        self.assertEqual(summary["open_contracts"], 1)

    def test_insufficient_margin_stops_run(self):
        with self.assertRaisesRegex(ValueError, "margin"):
            backtest(self.bars([10, 11, 12, 13]), fast=1, slow=2, initial_cash=100)

    def test_invalid_data_and_configuration(self):
        with self.assertRaises(ValueError):
            backtest(self.bars([10, float("nan"), 12]), fast=1, slow=2)
        with self.assertRaises(ValueError):
            backtest(self.bars([10, 11, 12]), fast=2, slow=2)
        with self.assertRaises(ValueError):
            backtest([Bar("2025-01-01", 10, 10)] * 3, fast=1, slow=2)


if __name__ == "__main__":
    unittest.main()
