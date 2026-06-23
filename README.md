# PortfolioAdvisor

A local multi-agent system that researches your equity holdings and recommends portfolio adjustments using Gemini + live market data.

## How it works

```
Holdings JSON
     │
     ▼
Market Agent ──────► Live prices, P&L, fundamentals (yfinance)
     │
News + Analyst Agent ► Web search per ticker (Gemini + Google Search)
     │
Portfolio Manager ──► Synthesizes everything into a structured review (Gemini)
     │
     ▼
CLI summary + Markdown report
```

## Setup

### 1. Install dependencies

```bash
# Create a virtual environment (recommended)
python3 -m venv .venv
source .venv/bin/activate

# Install packages
pip install -r requirements.txt
```

### 2. Set your Gemini API key

Get a free key at [aistudio.google.com](https://aistudio.google.com).

```bash
export GEMINI_API_KEY="AIza..."
```

Add this to your `~/.zshrc` or `~/.bashrc` to make it permanent.

### 3. Edit your holdings

Open `data/holdings.json` and replace the sample holdings with your own:

```json
{
  "portfolio_name": "My Portfolio",
  "currency": "USD",
  "holdings": [
    { "ticker": "AAPL", "shares": 20, "avg_cost": 165.00, "sector": "Technology" }
  ],
  "cash_usd": 5000
}
```

`ticker` must match the Yahoo Finance ticker symbol exactly (e.g. `BRK-B`, `0700.HK`, `TSLA`).

## Usage

```bash
# Full run (fetches prices + web research + recommendation)
python run.py

# Custom holdings file and output path
python run.py --holdings my_portfolio.json --output my_report.md

# Fast mode: skip web research (prices + AI analysis only, no news)
python run.py --no-research
```

A full run with 5 holdings typically takes 45–90 seconds (most of this is the concurrent web searches).

## Output

**CLI:** A formatted table with action, score, and conviction per ticker, plus top concerns and next steps.

**Markdown report:** `portfolio_report.md` (or custom path) with full per-holding rationale.

## Actions explained

| Action | Meaning |
|---|---|
| 🟢 Strong Buy More | High-conviction opportunity; add significantly |
| 🟩 Add | Positive outlook; add modestly if available cash |
| 🟡 Hold | No clear edge either way; maintain position |
| 🟠 Trim | Reduce position size; elevated risk or stretched valuation |
| 🔴 Exit | Exit the position; fundamentals or thesis has broken down |

## Extending the system

- **Add more tickers:** Edit `data/holdings.json`
- **Change the model:** Edit `model=` in `agents/portfolio_manager.py` or `agents/news_analyst_agent.py` (e.g. `gemini-2.0-flash`, `gemini-1.5-flash`)
- **Add a scheduler:** Use `cron` to run `python run.py` every weekday morning
- **Add email delivery:** Pipe `portfolio_report.md` to `mail` or integrate with a notification script
- **Add more agents:** Create a new file in `agents/` following the same pattern and call it from `run.py`

## Disclaimer

This tool is for informational purposes only. It is not financial advice. Always do your own research and consult a qualified advisor before making investment decisions.
