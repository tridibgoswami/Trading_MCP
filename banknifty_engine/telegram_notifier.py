# telegram_notifier.py
# ─────────────────────────────────────────────
# Sends trading alerts and reports to Telegram
# ─────────────────────────────────────────────

import requests
from loguru import logger
import config


class TelegramNotifier:

    def __init__(self):
        self.token   = config.TELEGRAM_TOKEN
        self.chat_id = config.TELEGRAM_CHAT_ID
        self.enabled = bool(self.token and self.chat_id)
        if not self.enabled:
            logger.warning("Telegram not configured. Alerts will only appear in logs.")

    def send(self, message: str, parse_mode: str = "HTML") -> bool:
        if not self.enabled:
            logger.info(f"[TELEGRAM-DISABLED] {message[:100]}")
            return False
        try:
            url  = f"https://api.telegram.org/bot{self.token}/sendMessage"
            resp = requests.post(url, json={
                "chat_id":    self.chat_id,
                "text":       message,
                "parse_mode": parse_mode
            }, timeout=10)
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"Telegram send error: {e}")
            return False

    def signal_alert(self, signal_type: str, price: float,
                     strength: float, regime: str, session: str):
        emoji = "🟢" if signal_type in ("BUY", "LONG") else "🔴"
        msg   = (
            f"{emoji} <b>SIGNAL: {signal_type}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Price    : ₹{price:,.2f}\n"
            f"📊 Strength : {strength:.2f}\n"
            f"🌊 Regime   : {regime}\n"
            f"⏰ Session  : {session}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"{'📄 PAPER TRADE' if config.PAPER_TRADE else '⚡ LIVE TRADE'}"
        )
        self.send(msg)

    def trade_closed(self, signal_type: str, entry: float,
                     exit_: float, pnl: float, reason: str):
        emoji = "✅" if pnl > 0 else "❌"
        msg   = (
            f"{emoji} <b>TRADE CLOSED: {signal_type}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📥 Entry  : ₹{entry:,.2f}\n"
            f"📤 Exit   : ₹{exit_:,.2f}\n"
            f"💵 PnL    : ₹{pnl:+,.2f}\n"
            f"🔖 Reason : {reason}\n"
            f"━━━━━━━━━━━━━━━━━━━"
        )
        self.send(msg)

    def daily_report(self, summary: dict):
        pnl_emoji = "🟢" if summary.get('total_pnl', 0) >= 0 else "🔴"
        msg = (
            f"📋 <b>DAILY REPORT — Bank Nifty</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Total Signals : {summary.get('total_signals', 0)}\n"
            f"✅ Wins          : {summary.get('wins', 0)}\n"
            f"❌ Losses        : {summary.get('losses', 0)}\n"
            f"🎯 Win Rate      : {summary.get('win_rate', 0):.1f}%\n"
            f"{pnl_emoji} Total PnL      : ₹{summary.get('total_pnl', 0):+,.2f}\n"
            f"━━━━━━━━━━━━━━━━━━━"
        )
        self.send(msg)

    def evolution_report(self, results: dict, plan: dict):
        assessment = plan.get('market_assessment', {})
        msg = (
            f"🧠 <b>EVOLUTION CYCLE COMPLETE</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📈 Regime    : {assessment.get('dominant_regime', 'N/A')}\n"
            f"⚡ Risk       : {assessment.get('risk_level', 'N/A')}\n"
            f"✅ Rules Added   : {results.get('added', 0)}\n"
            f"🔧 Rules Modified: {results.get('modified', 0)}\n"
            f"❌ Rules Retired : {results.get('retired', 0)}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"💡 {plan.get('optimization_summary', '')}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🔭 Next Week: {plan.get('next_week_focus', '')}"
        )
        self.send(msg)

    def system_status(self, message: str):
        self.send(f"⚙️ <b>SYSTEM</b>: {message}")

    def error_alert(self, error: str):
        self.send(f"🚨 <b>ERROR</b>: {error}")
