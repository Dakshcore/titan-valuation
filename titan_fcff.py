"""Titan Company: free cash flow to the firm (FCFF) DCF.

Uses the same revenue path, price date and cost of equity as titan_earnings.py, but values
the cash the business throws off after reinvesting in stores and working capital,
instead of its net income. Money is in Rs crore unless stated.
"""
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

from scipy.optimize import brentq

OUT = Path(__file__).parent

# Consolidated history from Screener.in (retrieved 1-Oct-2026), Rs crore, fiscal years to 31 March.
# Gold on loan is from ICICI Direct's Q4FY26 result update, which carries it as a current liability.
HISTORY = {
    #        sales,  PBT, interest, other inc, deprec, net block, CWIP, other assets, other liab, cash, borrowings, gold on loan
    2021: (21644, 1327, 203, 180, 375, 2523, 32, 11065, 3309, 560, 5638, None),
    2022: (28799, 2904, 218, 177, 399, 2544, 85, 18265, 4610, 1573, 7275, None),
    2023: (40575, 4447, 300, 306, 441, 2998, 144, 21363, 5802, 1343, 9367, None),
    2024: (51084, 4623, 619, 534, 584, 3709, 97, 25396, 6626, 1526, 15528, 5341),
    2025: (60456, 4535, 953, 487, 693, 4062, 105, 34490, 8244, 1584, 20777, 7810),
    2026: (87584, 6801, 1180, 450, 826, 6878, 163, 50014, 14237, 1917, 30621, 16070),
}
FIELDS = ("sales", "pbt", "interest", "other_income", "dep", "net_block", "cwip",
          "other_assets", "other_liab", "cash", "borrowings", "gold_loan")


def year(y):
    return dict(zip(FIELDS, HISTORY[y]))


def ebit(y):
    h = year(y)
    return h["pbt"] + h["interest"] - h["other_income"]


def capex(y):
    """Net block + CWIP growth plus depreciation (includes right-of-use assets for new store leases)."""
    h, p = year(y), year(y - 1)
    return h["net_block"] - p["net_block"] + h["cwip"] - p["cwip"] + h["dep"]


def nwc(y, gold_loan_is_debt):
    """Operating working capital: other assets less cash, less other liabilities (and gold on loan if operating)."""
    h = year(y)
    w = h["other_assets"] - h["cash"] - h["other_liab"]
    return w if gold_loan_is_debt else w - h["gold_loan"]


def avg_ratio(f, years):
    return sum(f(y) / year(y)["sales"] for y in years) / len(years)


FIVE_YEARS = range(2022, 2027)
GOLD_LOAN_YEARS = range(2024, 2027)   # the years with a gold-on-loan split

PRICE, PRICE_DAY = 4515.70, date(2026, 10, 1)   # NSE close, same as titan_earnings.py
SHARES = 890                                       # diluted, mn
TAX = 0.2517                                       # Indian corporate rate under the new regime
COST_OF_EQUITY = 0.1026                            # same as titan_earnings.py
GOLD_LOAN_FEE = 0.02   # my assumption for the yearly cost of gold on loan when it is treated as operating


@dataclass(frozen=True)
class Assumptions:
    gold_loan_is_debt: bool = False
    ebit_margin: float = avg_ratio(ebit, FIVE_YEARS)
    dep_pct: float = avg_ratio(lambda y: year(y)["dep"], FIVE_YEARS)
    capex_pct: float = avg_ratio(capex, FIVE_YEARS)
    terminal_growth: float = 0.06
    wacc: float | None = None        # None = build it from the capital structure
    nwc_pct: float | None = None     # None = FY2024-FY2026 average for the chosen gold-loan treatment


def growth_path():
    """FY2027-FY2042 revenue growth: analyst estimates to FY2029, then the S-curve fade in titan_earnings.py."""
    growth = [0.171936, 0.176092, 0.170382]
    for i in range(1, 14):
        x = i / 13
        growth.append(growth[2] + (0.06951 - growth[2]) * (3 * x**2 - 2 * x**3))
    return growth


def capital_structure(a):
    """Debt, net debt, pre-tax cost of debt and WACC at the FY2026 balance sheet and today's price."""
    h, p = year(2026), year(2025)
    if a.gold_loan_is_debt:
        debt, prior_debt, interest = h["borrowings"], p["borrowings"], h["interest"]
    else:
        debt = h["borrowings"] - h["gold_loan"]
        prior_debt = p["borrowings"] - p["gold_loan"]
        interest = h["interest"] - GOLD_LOAN_FEE * (h["gold_loan"] + p["gold_loan"]) / 2
    cost_of_debt = interest / ((debt + prior_debt) / 2)
    equity = PRICE * SHARES / 10                     # Rs crore
    wacc = (equity * COST_OF_EQUITY + debt * cost_of_debt * (1 - TAX)) / (equity + debt)
    return {"debt": debt, "net_debt": debt - h["cash"], "cost_of_debt": cost_of_debt,
            "debt_weight": debt / (equity + debt), "wacc": wacc if a.wacc is None else a.wacc}


def nwc_pct(a):
    return a.nwc_pct if a.nwc_pct is not None else avg_ratio(lambda y: nwc(y, a.gold_loan_is_debt), GOLD_LOAN_YEARS)


def gold_loan_fee_pct(a):
    if a.gold_loan_is_debt:
        return 0.0
    return GOLD_LOAN_FEE * avg_ratio(lambda y: year(y)["gold_loan"], GOLD_LOAN_YEARS)


def value(a=Assumptions(), growth=None):
    """Value per share in Rs, with the workings."""
    growth = growth or growth_path()
    cs = capital_structure(a)
    wacc, g, w = cs["wacc"], a.terminal_growth, nwc_pct(a)
    assert wacc > g, "WACC must exceed terminal growth"
    stub = (date(2027, 3, 31) - PRICE_DAY).days / 365
    margin = a.ebit_margin - gold_loan_fee_pct(a)

    sales, prior_nwc = year(2026)["sales"], nwc(2026, a.gold_loan_is_debt)
    rows, pv_explicit = [], 0.0
    for t, gr in enumerate(growth, start=1):
        sales *= 1 + gr
        nopat = sales * margin * (1 - TAX)
        reinvest = sales * (a.capex_pct - a.dep_pct) + (sales * w - prior_nwc)
        prior_nwc = sales * w
        fcff = nopat - reinvest
        period = stub + (t - 1)
        factor = 1 / (1 + wacc) ** period
        pv_explicit += fcff * (stub if t == 1 else 1) * factor
        rows.append({"fy": 2026 + t, "sales": sales, "nopat": nopat, "reinvestment": reinvest,
                     "fcff": fcff, "factor": factor})

    next_sales = sales * (1 + g)
    fcff_next = next_sales * margin * (1 - TAX) - next_sales * (a.capex_pct - a.dep_pct) - (next_sales - sales) * w
    terminal = fcff_next / (wacc - g)
    pv_terminal = terminal * rows[-1]["factor"]
    ev = pv_explicit + pv_terminal
    equity = ev - cs["net_debt"]
    ebitda_last = sales * (margin + a.dep_pct)
    return {"per_share": equity / SHARES * 10, "ev": ev, "equity": equity, "pv_explicit": pv_explicit,
            "pv_terminal": pv_terminal, "tv_share": pv_terminal / ev, "terminal_ev_ebitda": terminal / ebitda_last,
            "wacc": wacc, "nwc_pct": w, "ebit_margin": margin, "stub": stub, "rows": rows, **cs}


def implied(field, a=Assumptions(), lo=0.0, hi=0.5):
    """The value of one assumption that makes the DCF equal today's price."""
    return brentq(lambda x: value(replace(a, **{field: x}))["per_share"] - PRICE, lo, hi)


def main():
    import matplotlib.pyplot as plt

    base, alt = value(), value(Assumptions(gold_loan_is_debt=True))
    print(f"Price: Rs {PRICE:,.2f} (NSE close, {PRICE_DAY:%d-%b-%Y})")
    print(f"EBIT margin {base['ebit_margin']:.2%} after the gold-loan fee, capex {Assumptions().capex_pct:.2%} "
          f"and D&A {Assumptions().dep_pct:.2%} of sales, working capital {base['nwc_pct']:.1%} of sales")
    print(f"WACC {base['wacc']:.2%} (debt {base['debt_weight']:.1%} at {base['cost_of_debt']:.2%} pre-tax), "
          f"terminal growth {Assumptions().terminal_growth:.1%}")
    print(f"\nFCFF DCF value per share:     Rs {base['per_share']:,.0f} ({base['per_share'] / PRICE - 1:+.1%} vs price)")
    print(f"  EV Rs {base['ev']:,.0f} cr = explicit Rs {base['pv_explicit']:,.0f} cr + terminal Rs {base['pv_terminal']:,.0f} cr "
          f"({base['tv_share']:.1%}); net debt Rs {base['net_debt']:,.0f} cr")
    print(f"  Terminal value = {base['terminal_ev_ebitda']:.1f}x FY2042 EBITDA")
    print(f"Gold on loan treated as debt:  Rs {alt['per_share']:,.0f} (WACC {alt['wacc']:.2%}, "
          f"working capital {alt['nwc_pct']:.1%} of sales)")

    print("\nWhat the price implies (one assumption at a time):")
    print(f"  EBIT margin before the gold-loan fee: {implied('ebit_margin'):.1%}")
    print(f"  Terminal growth:                      {implied('terminal_growth', lo=0.0, hi=base['wacc'] - 1e-4):.2%}")
    print(f"  WACC:                                 {implied('wacc', lo=0.065, hi=0.2):.2%}")

    print("\nValue per share (Rs): WACC (rows) x terminal growth (columns)")
    gs = [0.05, 0.055, 0.06, 0.065, 0.07]
    print("         " + "".join(f"{g:>9.1%}" for g in gs))
    for r in [base["wacc"] + d for d in (-0.01, -0.005, 0, 0.005, 0.01)]:
        print(f"{r:>8.2%} " + "".join(f"{value(Assumptions(wacc=r, terminal_growth=g))['per_share']:>9,.0f}" for g in gs))

    rows = base["rows"]
    years = [r["fy"] for r in rows]
    plt.figure(figsize=(9, 4.5))
    plt.bar(years, [r["nopat"] for r in rows], color="lightgray", label="After-tax operating profit (NOPAT)")
    plt.bar(years, [r["fcff"] for r in rows], color="seagreen", label="Free cash flow (FCFF)")
    plt.xlabel("Fiscal year (ends 31 March)")
    plt.ylabel("Rs crore")
    plt.title(f"Titan: working capital and stores absorb most profit while growth is high\n"
              f"FCFF DCF Rs {base['per_share']:,.0f} a share vs price Rs {PRICE:,.0f} ({PRICE_DAY:%d %b %Y})")
    plt.legend()
    plt.tight_layout()
    plt.savefig(OUT / "titan_fcff.png", dpi=200)
    plt.show()


if __name__ == "__main__":
    main()
