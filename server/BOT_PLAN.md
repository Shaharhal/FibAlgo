# Hybrid Trading Bot — Architecture Plan

## Overview
TradingView handles signal detection (charts + EMA pullback alerts).
Python bot handles everything else (execution, R-exits, pyramiding, notifications).

## Architecture

```
TradingView  ──webhook──>  Python Bot  ──ccxt──>  Binance/Bybit
                           │
                           ├── Calculate position size (live balance)
                           ├── Place entry order
                           ├── Monitor price (websocket)
                           ├── Execute R-multiple exits
                           ├── Trail SL, pyramid at BE
                           └── Notify Telegram/Discord
```

## The Split

### TradingView does:
- Chart visuals (EMA, SMA, dashboard)
- Entry signal detection (EMA pullback bounce)
- Fires webhook: "BUY" or "SELL" + symbol + price + SL

### Python bot does:
- Receives the signal
- Calculates qty from equity % (reads live balance from exchange)
- Places entry order
- Opens websocket to monitor price in real-time
- Manages ALL exits autonomously:
  - +1.25R: sell 25%, move SL to BE, pyramid add
  - +1.75R: sell 25%, trail SL to +0.5R
  - +2.25R: sell 20%, trail SL to +1R
  - Runner: close when price closes below EMA (bot calculates EMA itself)
- Time stop (N bars with no profit = close)
- Sends Telegram/Discord on every action

## Pine Alert Format (simple)

```json
{
  "action": "BUY",
  "symbol": "BTCUSDT",
  "sl": 64800.00,
  "timeframe": "1H"
}
```

No qty, no TP, no R:R — bot figures it out from live account.

## File Structure

```
server/
├── main.py              # FastAPI: webhook receiver + control endpoints
├── exchange.py          # ccxt: connect to Binance/Bybit, place orders
├── trade_manager.py     # The brain: R-exits, SL trailing, pyramids
├── price_feed.py        # Websocket: real-time price stream from exchange
├── ema_calc.py          # Calculate EMA/SMA from exchange candle data
├── notifiers.py         # Telegram/Discord (already exists)
├── models.py            # Pydantic models for signals, positions, orders
├── paper_trader.py      # Simulated exchange for testing without real $
├── config.py            # .env loading, validation, defaults
├── requirements.txt     # ccxt, websockets, fastapi, uvicorn, aiohttp
└── .env.example
```

## API Endpoints

| Endpoint | What it does |
|----------|-------------|
| POST /webhook | Receive TradingView signal |
| GET /positions | See all open trades |
| GET /balance | Current equity + P&L |
| POST /close/{symbol} | Manual close one position |
| POST /close-all | Kill switch — flatten everything |
| GET /history | Trade log with R-multiples |
| GET / | Health check + status |

## Safety Layers

- Paper mode — default ON, simulates everything
- Max position size — never exceed equityPctMax
- Max daily drawdown — auto-stops trading if down X% in a day
- Duplicate filter — ignores same signal within N minutes
- Order confirmation — verifies fill before tracking
- Reconnect logic — auto-reconnects websocket on drop

## Build Order

1. exchange.py + paper_trader.py — Binance testnet
2. price_feed.py — websocket price stream
3. trade_manager.py — R-multiple exit brain
4. main.py — wire webhook → trade manager → exchange
5. ema_calc.py — runner exit EMA calculation
6. Test end-to-end in paper mode
7. Telegram notifications on every action
8. Run paper mode for 1-2 weeks
9. Go live with minimum size

## Status: WAITING
Build when EMA pullback strategy is proven profitable in backtesting.
