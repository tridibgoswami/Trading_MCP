# BrahmAstra → MCP Engine: TradingView Alert Setup

Paste one of these JSON templates into the **Message** box
when creating each alert in TradingView.

The `signal_name` field is what the engine uses to track each
of your 12 signals separately in the database.

---

## Webhook URL

```
https://xxxx.ngrok-free.app/signal
```
(replace with your actual ngrok URL — run ngrok_webhook.bat to get it)

---

## Entry Signals — BUY

### Signal 1 — BUY Entry
```json
{
  "indicator": "BrahmAstra",
  "signal_name": "S1_BUY",
  "type": "BUY",
  "price": {{close}},
  "volume": {{volume}},
  "ticker": "{{ticker}}",
  "interval": "{{interval}}",
  "secret": "YOUR_WEBHOOK_SECRET"
}
```

### Signal 2 — BUY Entry (add as many as you have)
```json
{
  "indicator": "BrahmAstra",
  "signal_name": "S2_BUY",
  "type": "BUY",
  "price": {{close}},
  "volume": {{volume}},
  "ticker": "{{ticker}}",
  "interval": "{{interval}}",
  "secret": "YOUR_WEBHOOK_SECRET"
}
```

---

## Entry Signals — SELL

### Signal 1 — SELL Entry
```json
{
  "indicator": "BrahmAstra",
  "signal_name": "S1_SELL",
  "type": "SELL",
  "price": {{close}},
  "volume": {{volume}},
  "ticker": "{{ticker}}",
  "interval": "{{interval}}",
  "secret": "YOUR_WEBHOOK_SECRET"
}
```

---

## Exit Signals — Target Hit

### Exit Long (target hit)
```json
{
  "indicator": "BrahmAstra",
  "signal_name": "EXIT_LONG_TARGET",
  "type": "EXIT_LONG",
  "price": {{close}},
  "ticker": "{{ticker}}",
  "interval": "{{interval}}",
  "secret": "YOUR_WEBHOOK_SECRET"
}
```

### Exit Short (target hit)
```json
{
  "indicator": "BrahmAstra",
  "signal_name": "EXIT_SHORT_TARGET",
  "type": "EXIT_SHORT",
  "price": {{close}},
  "ticker": "{{ticker}}",
  "interval": "{{interval}}",
  "secret": "YOUR_WEBHOOK_SECRET"
}
```

---

## Stop Loss Hit Signals

### SL Hit — Long position
```json
{
  "indicator": "BrahmAstra",
  "signal_name": "SL_HIT_LONG",
  "type": "EXIT_LONG",
  "price": {{close}},
  "ticker": "{{ticker}}",
  "interval": "{{interval}}",
  "secret": "YOUR_WEBHOOK_SECRET"
}
```

### SL Hit — Short position
```json
{
  "indicator": "BrahmAstra",
  "signal_name": "SL_HIT_SHORT",
  "type": "EXIT_SHORT",
  "price": {{close}},
  "ticker": "{{ticker}}",
  "interval": "{{interval}}",
  "secret": "YOUR_WEBHOOK_SECRET"
}
```

---

## If your indicator has numeric plots to send

Add these fields to any template above:
```json
  "strength":    {{plot_0}},
  "rsi":         {{plot_1}},
  "volume_ratio": {{plot_2}}
```

Replace `plot_0`, `plot_1` etc. with the actual plot
variable names from your Pine Script.

---

## Updating the trade outcome (optional but recommended)

Send this to `https://xxxx.ngrok-free.app/outcome`
after a trade closes — this stops the MFE/MAE tracker
immediately and records the exact exit:

```json
{
  "signal_id":    123,
  "entry_price":  54086,
  "exit_price":   54329,
  "holding_mins": 47,
  "exit_reason":  "TARGET",
  "secret": "YOUR_WEBHOOK_SECRET"
}
```

`exit_reason` options: `TARGET` | `STOPLOSS` | `TIME` | `MANUAL`

---

## Naming convention (customise to match your signals)

| signal_name          | type        | meaning                    |
|----------------------|-------------|----------------------------|
| `S1_BUY`            | BUY         | BrahmAstra signal 1 long   |
| `S2_BUY`            | BUY         | BrahmAstra signal 2 long   |
| `S1_SELL`           | SELL        | BrahmAstra signal 1 short  |
| `S2_SELL`           | SELL        | BrahmAstra signal 2 short  |
| `EXIT_LONG_TARGET`  | EXIT_LONG   | Target hit on long          |
| `EXIT_SHORT_TARGET` | EXIT_SHORT  | Target hit on short         |
| `SL_HIT_LONG`       | EXIT_LONG   | SL hit on long              |
| `SL_HIT_SHORT`      | EXIT_SHORT  | SL hit on short             |

Rename the `signal_name` values to match whatever your
indicator actually calls them — the engine stores and
analyses whatever name you give it.
