import html
import json
import hashlib
import threading
import urllib.request
import urllib.error
from typing import Dict, Set, Any
from config import BotConfig
from strategies import TradeSignal, signal_state_identity


def _esc(val: Any) -> str:
    return html.escape(str(val), quote=True)


class TelegramSignalDispatcher:
    """
    Formats and sends NSE Equity & Nifty/BankNifty F&O trade signals to Telegram
    via the official Telegram Bot HTTP API (`sendMessage` with HTML parse_mode).
    Escapes all dynamic values to prevent broken HTML entities or injection.
    """
    def __init__(self, config: BotConfig):
        self.config = config
        self.sent_cache: Set[str] = set()
        self._send_lock = threading.Lock()

    def format_signal_html(self, sig: TradeSignal, broker_name: str) -> str:
        badge = "🟢" if "BULLISH" in str(sig.direction) else "🔴"
        seg_label = "🇮🇳 NIFTY / BANKNIFTY F&amp;O" if sig.segment == "NSE_FO_INDEX" else "📈 NSE INTRADAY EQUITY"
        _, (provider, mode, context) = signal_state_identity(sig, broker_name)
        mode_tag = " [SIMULATED DATA]" if mode == "SIMULATED" else ""
        if context == "SCANNER" and provider != "unknown":
            title = "SIMULATED SIGNAL" if mode == "SIMULATED" else "LIVE SIGNAL"
        else:
            title = f"SIGNAL [{context} / {provider}]"

        return (
            f"{badge} <b>{seg_label} {_esc(title)}{_esc(mode_tag)}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Instrument:</b> <code>{_esc(sig.instrument_label)}</code>\n"
            f"<b>Action:</b> <b>{_esc(sig.direction)}</b>\n"
            f"<b>Strategy:</b> {_esc(sig.strategy_name)}\n"
            f"<b>Setup Quality:</b> {int(sig.quality_score)}/100 (rule score; predictive performance unverified)\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 <b>Entry Price:</b> ₹{float(sig.entry_price):,.2f} <i>(Zone: ₹{float(sig.entry_zone_low):,.2f} – ₹{float(sig.entry_zone_high):,.2f})</i>\n"
            f"🛑 <b>Stop-Loss (S1):</b> ₹{float(sig.stop_loss):,.2f}\n"
            f"✅ <b>Target 1 (T1):</b> ₹{float(sig.target_1):,.2f}\n"
            f"🚀 <b>Target 2 (T2):</b> ₹{float(sig.target_2):,.2f}\n"
            f"⚖️ <b>Risk-Reward:</b> {_esc(sig.risk_reward)}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💼 <b>Position Sizing ({float(self.config.max_risk_per_trade_pct):g}% configured risk limit):</b> {int(sig.position_qty)} Qty (Estimated Risk: ₹{float(sig.capital_risk_inr):,.2f} | Est. NSE Charges: ₹{float(sig.est_charges_inr):,.2f})\n"
            f"🧠 <b>Setup Logic:</b> {_esc(sig.rationale)}\n"
            f"🔌 <b>Data Feed:</b> {_esc(broker_name)} | 🕒 <code>{_esc(sig.timestamp)} IST</code>"
        )

    def send_signal(self, sig: TradeSignal, broker_name: str = "Angel One SmartAPI") -> Dict[str, Any]:
        # Serialize check/send/commit; failed sends never consume a cache entry.
        # Retain process-lifetime deduplication (no TTL); a new candle has a new key.
        # Persisted scanner signals provide same-scope deduplication after restart.
        with self._send_lock:
            return self._send_signal_locked(sig, broker_name)

    def _send_signal_locked(self, sig: TradeSignal, broker_name: str) -> Dict[str, Any]:
        signal_key, (_, mode, _) = signal_state_identity(sig, broker_name)
        dry_run = bool(self.config.telegram_dry_run or not (
            self.config.telegram_bot_token and self.config.telegram_chat_id))
        # A preview or another destination must not suppress an actual delivery.
        destination = hashlib.sha256(str(self.config.telegram_bot_token or "").encode()).hexdigest()
        dedup_key = json.dumps([signal_key, dry_run, destination, self.config.telegram_chat_id])
        if dedup_key in self.sent_cache:
            return {"ok": True, "skipped": True, "reason": "duplicate_within_candle"}

        message_html = self.format_signal_html(sig, broker_name)
        is_sim = mode == "SIMULATED"
        if dry_run:
            self.sent_cache.add(dedup_key)
            return {
                "ok": True,
                "dry_run": True,
                "is_simulated": is_sim,
                "chat_id": self.config.telegram_chat_id or "@indian_fo_signals_demo",
                "message_html": message_html,
            }

        url = f"https://api.telegram.org/bot{self.config.telegram_bot_token}/sendMessage"
        payload = json.dumps({
            "chat_id": self.config.telegram_chat_id,
            "text": message_html,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                if result.get("ok"):
                    self.sent_cache.add(dedup_key)
                return result
        except Exception as exc:
            # Never include the bot token URL in raised error messages
            raise RuntimeError(f"Telegram API request failed ({type(exc).__name__}).") from None
