from datetime import date
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import yfinance as yf
from scipy.optimize import brentq

OUT = Path(__file__).parent   # charts are saved next to this script

revenue_2026 = 875.84
LIVE_PRICE = False   # False reproduces the published numbers (Rs 4,515.70 on 1-Oct-2026)
price, price_day = 4515.70, date(2026, 10, 1)
if LIVE_PRICE:
    try:
        history = yf.Ticker("TITAN.NS").history(period="5d")["Close"]
        price = history.iloc[-1]
        price_day = history.index[-1].date()
    except Exception:
        print("Live price unavailable; using Rs 4,515.70 on 1-Oct-2026")
price_date = price_day.strftime("%d-%b-%Y")
shares = 890
stub = (date(2027, 3, 31) - price_day).days / 365   # part of FY27 left after the price date
assert 0 < stub <= 1, "price date is outside FY27; roll the model forward"
growth = [0.171936, 0.176092, 0.170382]   # FY27-FY29
fade_start = growth[-1]
fade_end = 0.06951
for i in range(1, 14):                     # FY30-FY42 fade smoothly to the long-run rate
    x = i / 13
    weight = 3 * x**2 - 2 * x**3
    growth.append(fade_start + (fade_end - fade_start) * weight)
def earnings_value(growth, margin_start=0.067105625, margin_end=0.06628,
              discount_rate=0.1026, exit_pe=26.52265):
    """Value per share in Rs for one set of assumptions."""
    revenue = revenue_2026
    total_pv = 0
    years = len(growth)
    for t in range(1, years + 1):
        revenue = revenue * (1 + growth[t - 1])
        x = t / years
        margin = margin_start + (margin_end - margin_start) * (3 * x**2 - 2 * x**3)
        net_income = revenue * margin
        share_of_year = stub if t == 1 else 1
        period = stub + (t - 1)
        total_pv += net_income * share_of_year / (1 + discount_rate) ** period
    terminal_value = net_income * exit_pe / (1 + discount_rate) ** period
    equity_value = total_pv + terminal_value
    return equity_value / shares * 1000


def main():
    print(f"Price: Rs {price:,.2f} (close on {price_date})")
    base_value = earnings_value(growth)
    print(f"Value per share (discounted earnings): Rs {base_value:,.2f}")

    # Monte Carlo. The spreads below are my own assumptions, not market data.
    GROWTH_SD, MARGIN_SD, RATE_SD, PE_SD = 0.02, 0.005, 0.0075, 3
    rng = np.random.default_rng(42)
    values = []
    for _ in range(10000):
        shift = rng.normal(0, GROWTH_SD)
        margin_end = rng.normal(0.06628, MARGIN_SD)
        rate = rng.normal(0.1026, RATE_SD)
        pe = rng.normal(26.52265, PE_SD)
        new_growth = [g + shift for g in growth]
        values.append(earnings_value(new_growth, margin_end=margin_end,
                                discount_rate=rate, exit_pe=pe))
    values = np.array(values)
    print(f"\nMonte Carlo, 10,000 scenarios. Assumed spreads (1 sd): growth +/-{GROWTH_SD:.0%} pts every year, "
          f"FY2042 margin +/-{MARGIN_SD:.1%}, discount rate +/-{RATE_SD:.2%}, exit P/E +/-{PE_SD}x")
    print(f"Median value:          Rs {np.median(values):,.0f}")
    print(f"90% of scenarios:      Rs {np.percentile(values, 5):,.0f} to Rs {np.percentile(values, 95):,.0f}")
    print(f"Chance value > price:  {np.mean(values > price):.0%} (depends on the assumed spreads above)")

    plt.figure(figsize=(9, 5))
    plt.hist(values, bins=60, color="gray")
    plt.axvline(price, color="red", label=f"Price Rs {price:,.0f} ({price_date})")
    plt.axvline(base_value, color="blue", label=f"Base case Rs {base_value:,.0f}")
    plt.xlabel("Value per share, discounted earnings (Rs)")
    plt.ylabel("Number of scenarios")
    plt.title("Titan: 10,000 discounted-earnings scenarios")
    plt.figtext(0.5, 0.005, f"Assumed spreads (1 sd): growth ±{GROWTH_SD:.0%} pts/yr, FY2042 margin ±{MARGIN_SD:.1%}, "
                f"discount rate ±{RATE_SD:.2%}, exit P/E ±{PE_SD}x", ha="center", fontsize=8, color="dimgray")
    plt.legend()
    plt.tight_layout(rect=(0, 0.03, 1, 1))
    plt.savefig(OUT / "titan_monte_carlo.png", dpi=200)
    plt.show()

    def gap(g):
        return earnings_value([g] * 16) - price

    implied_growth = brentq(gap, 0.0, 0.40)
    print(f"\nGrowth needed every year to justify Rs {price:,.0f}: {implied_growth:.1%}")

    tests = [
        ("Revenue growth (+/- 2 pts)",   earnings_value([g - 0.02 for g in growth]),            earnings_value([g + 0.02 for g in growth])),
        ("FY2042 margin (+/- 0.5 pts)",  earnings_value(growth, margin_end=0.06628 - 0.005),    earnings_value(growth, margin_end=0.06628 + 0.005)),
        ("Discount rate (+/- 0.75 pts)", earnings_value(growth, discount_rate=0.1026 - 0.0075), earnings_value(growth, discount_rate=0.1026 + 0.0075)),
        ("Exit P/E (+/- 3x)",            earnings_value(growth, exit_pe=26.52265 - 3),          earnings_value(growth, exit_pe=26.52265 + 3)),
    ]


    def swing(test):
        name, low, high = test
        return abs(high - low)


    tests.sort(key=swing)

    print("\nWhat moves the value most (biggest first):")
    for name, low, high in reversed(tests):
        print(f"  {name:<30} Rs {min(low, high):,.0f} to Rs {max(low, high):,.0f}   swing Rs {abs(high - low):,.0f}")

    plt.figure(figsize=(9, 4))
    for i, (name, low, high) in enumerate(tests):
        down = min(low, high) - base_value
        up = max(low, high) - base_value
        plt.barh(i, down, left=base_value, color="indianred")
        plt.barh(i, up, left=base_value, color="seagreen")
        plt.text(min(low, high), i, f"Rs {min(low, high):,.0f} ", va="center", ha="right")
        plt.text(max(low, high), i, f" Rs {max(low, high):,.0f}", va="center", ha="left")
    plt.axvline(base_value, color="black", linewidth=1)
    plt.margins(x=0.2)
    plt.yticks(range(len(tests)), [t[0] for t in tests])
    plt.xlabel("Value per share, discounted earnings (Rs)")
    plt.title(f"What moves Titan's value? (base case Rs {base_value:,.0f}; price Rs {price:,.0f} on {price_date})")
    plt.tight_layout()
    plt.savefig(OUT / "titan_tornado.png", dpi=200)
    plt.show()


if __name__ == "__main__":
    main()
