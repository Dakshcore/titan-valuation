import unittest
from dataclasses import replace

import titan_earnings
import titan_fcff as f


class EarningsModelTest(unittest.TestCase):
    def test_base_case_matches_published_value(self):
        self.assertAlmostEqual(titan_earnings.earnings_value(titan_earnings.growth), 4057.51, places=2)

    def test_higher_discount_rate_lowers_value(self):
        g = titan_earnings.growth
        self.assertLess(titan_earnings.earnings_value(g, discount_rate=0.11), titan_earnings.earnings_value(g))


class FcffModelTest(unittest.TestCase):
    def test_growth_path_matches_earnings_model(self):
        for a, b in zip(f.growth_path(), titan_earnings.growth):
            self.assertAlmostEqual(a, b, places=12)

    def test_history_ratios(self):
        self.assertAlmostEqual(f.ebit(2026), 6801 + 1180 - 450)
        self.assertAlmostEqual(f.capex(2026), (6878 - 4062) + (163 - 105) + 826)
        self.assertAlmostEqual(f.nwc(2026, gold_loan_is_debt=True), 50014 - 1917 - 14237)
        self.assertAlmostEqual(f.nwc(2026, gold_loan_is_debt=False), 50014 - 1917 - 14237 - 16070)

    def test_base_case(self):
        v = f.value()
        self.assertAlmostEqual(v["per_share"], 2131, delta=1)
        self.assertAlmostEqual(v["net_debt"], 30621 - 16070 - 1917)
        self.assertAlmostEqual(v["equity"], v["ev"] - v["net_debt"])
        self.assertAlmostEqual(v["ev"], v["pv_explicit"] + v["pv_terminal"])

    def test_wacc_is_a_weighted_average(self):
        cs = f.capital_structure(f.Assumptions())
        self.assertGreater(cs["wacc"], cs["cost_of_debt"] * (1 - f.TAX))
        self.assertLess(cs["wacc"], f.COST_OF_EQUITY)

    def test_terminal_value_is_gordon_growth(self):
        # With no growth, no reinvestment and a flat margin, every FCFF equals NOPAT and the
        # terminal value is NOPAT / WACC.
        a = f.Assumptions(terminal_growth=0.0, capex_pct=0.0, dep_pct=0.0, wacc=0.1, gold_loan_is_debt=True,
                          nwc_pct=f.nwc(2026, True) / f.year(2026)["sales"])
        v = f.value(a, growth=[0.0] * 16)
        nopat = f.year(2026)["sales"] * a.ebit_margin * (1 - f.TAX)
        self.assertAlmostEqual(v["pv_terminal"], nopat / 0.1 * v["rows"][-1]["factor"], places=4)

    def test_gold_loan_as_debt_is_lower(self):
        self.assertLess(f.value(f.Assumptions(gold_loan_is_debt=True))["per_share"], f.value()["per_share"])

    def test_implied_margin_reproduces_price(self):
        m = f.implied("ebit_margin")
        self.assertAlmostEqual(f.value(replace(f.Assumptions(), ebit_margin=m))["per_share"], f.PRICE, places=4)

    def test_value_rises_with_growth_and_falls_with_wacc(self):
        base = f.value()["per_share"]
        self.assertGreater(f.value(f.Assumptions(terminal_growth=0.065))["per_share"], base)
        self.assertLess(f.value(f.Assumptions(wacc=0.11))["per_share"], base)


if __name__ == "__main__":
    unittest.main()
