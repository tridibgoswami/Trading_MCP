# core/webhook_receiver.py
# ─────────────────────────────────────────────
# HTTP server that receives TradingView webhook
# alerts and feeds them into the signal engine.
#
# TradingView alert message format (paste into
# the "Message" box when creating an alert):
#
# {
#   "indicator": "YourIndicatorName",
#   "type": "BUY",
#   "price": {{close}},
#   "strength": {{plot_0}},
#   "rsi": {{plot_1}},
#   "volume": {{volume}},
#   "ticker": "{{ticker}}",
#   "interval": "{{interval}}",
#   "secret": "your_webhook_secret"
# }
#
# Webhook URL to paste in TradingView:
#   http://<your-ip>:<WEBHOOK_PORT>/signal
#
# For local desktop use ngrok:
#   ngrok http 5050
#   → use the https://xxxx.ngrok.io/signal URL
# ─────────────────────────────────────────────

import threading
from datetime import datetime
from flask import Flask, request, jsonify
from loguru import logger

from signal_logger import SignalLogger
from telegram_notifier import TelegramNotifier
import config

app      = Flask(__name__)
sig_log  = SignalLogger()
telegram = TelegramNotifier()

# Optional reference to LiveAnalyzer — set from start_engine.py
_live_analyzer = None

def set_live_analyzer(analyzer):
    global _live_analyzer
    _live_analyzer = analyzer


# ─────────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    """Simple liveness check — open in browser to confirm server is up."""
    return jsonify({
        "status":     "ok",
        "server":     "BankNifty MCP Webhook Receiver",
        "time":       datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "port":       config.WEBHOOK_PORT,
    })


@app.route("/signal", methods=["POST"])
def receive_signal():
    """
    Main endpoint — receives TradingView alert JSON.

    Required fields : type (BUY/SELL/EXIT_LONG/EXIT_SHORT), price
    Optional fields : indicator, strength, rsi, volume, volume_ratio,
                      ema_9, ema_21, above_vwap, atr, macd, macd_signal,
                      vix, regime, trend_direction, rule_triggered, ticker, interval
    Auth field      : secret (must match WEBHOOK_SECRET in .env if set)
    """
    try:
        data = request.get_json(force=True, silent=True)
        if not data:
            logger.warning("Webhook: empty or non-JSON payload received")
            return jsonify({"error": "invalid JSON"}), 400

        # ── Optional secret validation
        if config.WEBHOOK_SECRET:
            incoming = data.get("secret") or request.headers.get("X-Webhook-Secret", "")
            if incoming != config.WEBHOOK_SECRET:
                logger.warning(f"Webhook: invalid secret from {request.remote_addr}")
                return jsonify({"error": "unauthorized"}), 401

        # ── Required fields
        signal_type = data.get("type", "").upper()
        price       = data.get("price")

        if signal_type not in ("BUY", "SELL", "EXIT_LONG", "EXIT_SHORT"):
            return jsonify({"error": f"invalid type: {signal_type}"}), 400
        if not price:
            return jsonify({"error": "price is required"}), 400

        # ── Build signal dict
        signal = {
            "type":             signal_type,
            "price":            float(price),
            "indicator_name":   data.get("indicator", "pine_script"),
            "strength":         _safe_float(data.get("strength")),
            "rsi":              _safe_float(data.get("rsi")),
            "ema_9":            _safe_float(data.get("ema_9")),
            "ema_21":           _safe_float(data.get("ema_21")),
            "above_vwap":       data.get("above_vwap"),
            "volume_ratio":     _safe_float(data.get("volume_ratio")),
            "atr":              _safe_float(data.get("atr")),
            "macd":             _safe_float(data.get("macd")),
            "macd_signal":      _safe_float(data.get("macd_signal")),
            "vix":              _safe_float(data.get("vix")),
            "regime":           data.get("regime"),
            "trend_direction":  data.get("trend_direction"),
            "rule_triggered":   data.get("rule_triggered"),
            "extra": {
                "ticker":   data.get("ticker"),
                "interval": data.get("interval"),
                "source":   "tradingview_webhook",
            }
        }

        # ── Log the signal
        signal_id = sig_log.log_signal(signal)

        # ── Telegram alert
        telegram.signal_alert(
            signal_type = signal_type,
            price       = float(price),
            strength    = signal.get("strength") or 0,
            regime      = signal.get("regime") or "UNKNOWN",
            session     = sig_log._get_session(),
        )

        # ── Pass context to live analyzer if running
        if _live_analyzer and _live_analyzer._running:
            with _live_analyzer._lock:
                _live_analyzer._recent_signals.appendleft({
                    "time":           datetime.now().strftime("%H:%M:%S"),
                    "signal":         f"[{signal['indicator_name']}] {signal_type}",
                    "direction":      "BUY" if signal_type in ("BUY",) else "SELL",
                    "price":          float(price),
                    "rsi":            signal.get("rsi"),
                    "regime":         signal.get("regime"),
                    "volume_ratio":   signal.get("volume_ratio"),
                    "source":         "tradingview",
                })
                _live_analyzer._state["signals"] = list(
                    _live_analyzer._recent_signals
                )[:10]

        logger.success(
            f"[WEBHOOK] {signal['indicator_name']} → {signal_type} "
            f"@ ₹{price} | signal_id={signal_id}"
        )

        return jsonify({
            "status":     "logged",
            "signal_id":  signal_id,
            "type":       signal_type,
            "price":      float(price),
            "indicator":  signal["indicator_name"],
        }), 200

    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/outcome", methods=["POST"])
def receive_outcome():
    """
    Optional endpoint — update a signal with its trade result.
    Call this from Pine Script or manually after a trade closes.

    JSON body:
    {
      "signal_id":    123,
      "entry_price":  48250.0,
      "exit_price":   48510.0,
      "holding_mins": 15,
      "exit_reason":  "TARGET",
      "secret":       "your_webhook_secret"
    }
    """
    try:
        data = request.get_json(force=True, silent=True)
        if not data:
            return jsonify({"error": "invalid JSON"}), 400

        if config.WEBHOOK_SECRET:
            incoming = data.get("secret") or request.headers.get("X-Webhook-Secret", "")
            if incoming != config.WEBHOOK_SECRET:
                return jsonify({"error": "unauthorized"}), 401

        result = sig_log.update_outcome(
            signal_id    = int(data["signal_id"]),
            entry_price  = float(data["entry_price"]),
            exit_price   = float(data["exit_price"]),
            holding_mins = int(data["holding_mins"]),
            exit_reason  = data.get("exit_reason", "MANUAL"),
        )

        telegram.trade_closed(
            signal_type = "TRADE",
            entry       = float(data["entry_price"]),
            exit_       = float(data["exit_price"]),
            pnl         = result["pnl"],
            reason      = data.get("exit_reason", "MANUAL"),
        )

        logger.success(f"[WEBHOOK] Outcome updated: signal {data['signal_id']} → {result['outcome']}")
        return jsonify(result), 200

    except Exception as e:
        logger.error(f"Outcome webhook error: {e}")
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────
# SERVER STARTUP
# ─────────────────────────────────────────────

def start(port: int = None):
    """Start the webhook receiver in a background daemon thread."""
    port = port or config.WEBHOOK_PORT
    logger.info(f"Starting webhook receiver on port {port}...")
    logger.info(f"  Signal endpoint : http://0.0.0.0:{port}/signal")
    logger.info(f"  Outcome endpoint: http://0.0.0.0:{port}/outcome")
    logger.info(f"  Health check    : http://0.0.0.0:{port}/health")
    if not config.WEBHOOK_SECRET:
        logger.warning("WEBHOOK_SECRET not set — webhook is open to anyone. Set it in .env!")

    t = threading.Thread(
        target=lambda: app.run(
            host      = "0.0.0.0",
            port      = port,
            threaded  = True,
            use_reloader = False,
        ),
        name   = "webhook-receiver",
        daemon = True,
    )
    t.start()
    return t


# ─────────────────────────────────────────────
# HELPER
# ─────────────────────────────────────────────

def _safe_float(val):
    try:
        return float(val) if val is not None else None
    except (ValueError, TypeError):
        return None
