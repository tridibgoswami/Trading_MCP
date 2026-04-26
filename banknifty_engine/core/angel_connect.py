# core/angel_connect.py
# ─────────────────────────────────────────────
# Handles all AngelOne SmartAPI interactions:
#  - Login with TOTP
#  - Historical data fetch
#  - Live WebSocket feed
#  - Order placement (paper + live)
# ─────────────────────────────────────────────

import pyotp
import time
import json
import threading
import pandas as pd
from datetime import datetime, timedelta
from loguru import logger

from SmartApi import SmartConnect
from SmartApi.smartWebSocketV2 import SmartWebSocketV2

import config


class AngelOneConnect:
    def __init__(self):
        self.api         = None
        self.auth_token  = None
        self.feed_token  = None
        self.ws          = None
        self._connected  = False
        self._callbacks  = []       # list of functions to call on tick
        self._daily_pnl  = 0.0

    # ─────────────────────────────────────────
    # LOGIN
    # ─────────────────────────────────────────
    def login(self) -> bool:
        """Login to AngelOne with TOTP authentication"""
        try:
            self.api = SmartConnect(api_key=config.ANGEL_API_KEY)

            totp     = pyotp.TOTP(config.ANGEL_TOTP_SECRET).now()
            data     = self.api.generateSession(
                clientCode = config.ANGEL_CLIENT_ID,
                password   = config.ANGEL_MPIN,
                totp       = totp
            )

            if data['status'] is False:
                logger.error(f"AngelOne login failed: {data['message']}")
                return False

            self.auth_token = data['data']['jwtToken']
            self.feed_token = self.api.getfeedToken()
            self._connected = True

            logger.success(f"AngelOne login successful | Client: {config.ANGEL_CLIENT_ID}")
            return True

        except Exception as e:
            logger.error(f"AngelOne login error: {e}")
            return False

    # ─────────────────────────────────────────
    # HISTORICAL DATA
    # ─────────────────────────────────────────
    def get_historical_data(self,
                             symbol_token : str  = config.BANKNIFTY_TOKEN,
                             exchange     : str  = "NSE",
                             interval     : str  = "FIVE_MINUTE",
                             days         : int  = 14) -> pd.DataFrame:
        """
        Fetch historical OHLCV candles.
        interval options: ONE_MINUTE, FIVE_MINUTE, FIFTEEN_MINUTE,
                          THIRTY_MINUTE, ONE_HOUR, ONE_DAY
        """
        try:
            to_date   = datetime.now()
            from_date = to_date - timedelta(days=days)

            params = {
                "exchange":    exchange,
                "symboltoken": symbol_token,
                "interval":    interval,
                "fromdate":    from_date.strftime("%Y-%m-%d %H:%M"),
                "todate":      to_date.strftime("%Y-%m-%d %H:%M"),
            }

            resp = self.api.getCandleData(params)

            if resp['status'] is False:
                logger.error(f"Historical data error: {resp['message']}")
                return pd.DataFrame()

            df = pd.DataFrame(
                resp['data'],
                columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
            )
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df = df.sort_values('timestamp').reset_index(drop=True)

            logger.info(f"Fetched {len(df)} candles | {interval} | last {days} days")
            return df

        except Exception as e:
            logger.error(f"Historical data fetch error: {e}")
            return pd.DataFrame()

    def get_ltp(self, exchange: str, symbol: str, token: str) -> float:
        """Get last traded price"""
        try:
            resp = self.api.ltpData(exchange, symbol, token)
            if resp['status']:
                return float(resp['data']['ltp'])
        except Exception as e:
            logger.error(f"LTP fetch error: {e}")
        return 0.0

    # ─────────────────────────────────────────
    # WEBSOCKET LIVE FEED
    # ─────────────────────────────────────────
    def start_live_feed(self, tokens: list = None):
        """
        Start WebSocket live feed for BankNifty.
        tokens = list of {"exchangeType": 1, "tokens": ["99926009"]}
        """
        if tokens is None:
            tokens = [{"exchangeType": 1, "tokens": [config.BANKNIFTY_TOKEN]}]

        def on_data(wsapp, message):
            try:
                tick = json.loads(message) if isinstance(message, str) else message
                for cb in self._callbacks:
                    cb(tick)
            except Exception as e:
                logger.error(f"WebSocket data error: {e}")

        def on_open(wsapp):
            logger.success("WebSocket connected — live feed started")

        def on_error(wsapp, error):
            logger.error(f"WebSocket error: {error}")

        def on_close(wsapp):
            logger.warning("WebSocket closed — attempting reconnect in 5s")
            time.sleep(5)
            self.start_live_feed(tokens)

        self.ws = SmartWebSocketV2(
            auth_token   = self.auth_token,
            api_key      = config.ANGEL_API_KEY,
            client_code  = config.ANGEL_CLIENT_ID,
            feed_token   = self.feed_token,
            on_open      = on_open,
            on_data      = on_data,
            on_error     = on_error,
            on_close     = on_close,
        )

        ws_thread = threading.Thread(
            target=self.ws.connect,
            args=(1, tokens),  # 1 = LTP mode
            daemon=True
        )
        ws_thread.start()
        logger.info("Live feed thread started")

    def register_tick_callback(self, func):
        """Register a function to be called on every price tick"""
        self._callbacks.append(func)

    def stop_live_feed(self):
        if self.ws:
            self.ws.close_connection()
            logger.info("Live feed stopped")

    # ─────────────────────────────────────────
    # ORDER PLACEMENT
    # ─────────────────────────────────────────
    def place_order(self,
                    symbol       : str,
                    token        : str,
                    action       : str,   # "BUY" or "SELL"
                    qty          : int,
                    order_type   : str  = "MARKET",
                    price        : float = 0,
                    product_type : str  = "INTRADAY") -> dict:
        """
        Place order — paper trade or live based on config.PAPER_TRADE
        Returns order dict with order_id
        """

        # ── Safety check
        if self._daily_pnl <= -config.MAX_DAILY_LOSS:
            logger.warning(f"Daily loss limit hit ₹{config.MAX_DAILY_LOSS}. No new orders.")
            return {"status": "BLOCKED", "reason": "daily_loss_limit"}

        if config.PAPER_TRADE:
            logger.info(
                f"[PAPER TRADE] {action} {qty} {symbol} | "
                f"Type: {order_type} | Price: {price}"
            )
            return {
                "status":   "PAPER_SUCCESS",
                "order_id": f"PAPER_{int(time.time())}",
                "symbol":   symbol,
                "action":   action,
                "qty":      qty,
                "price":    price,
            }

        # ── Live order
        try:
            order_params = {
                "variety":         "NORMAL",
                "tradingsymbol":   symbol,
                "symboltoken":     token,
                "transactiontype": action,
                "exchange":        "NFO",
                "ordertype":       order_type,
                "producttype":     product_type,
                "duration":        "DAY",
                "price":           str(price),
                "squareoff":       "0",
                "stoploss":        "0",
                "quantity":        str(qty),
            }
            resp = self.api.placeOrder(order_params)

            if resp['status']:
                logger.success(f"Order placed: {action} {qty} {symbol} | ID: {resp['data']['orderid']}")
                return {"status": "SUCCESS", "order_id": resp['data']['orderid']}
            else:
                logger.error(f"Order failed: {resp['message']}")
                return {"status": "FAILED", "reason": resp['message']}

        except Exception as e:
            logger.error(f"Order placement error: {e}")
            return {"status": "ERROR", "reason": str(e)}

    def update_daily_pnl(self, pnl: float):
        self._daily_pnl += pnl

    def get_profile(self) -> dict:
        """Get account profile info"""
        try:
            resp = self.api.getProfile(self.auth_token)
            return resp.get('data', {})
        except Exception as e:
            logger.error(f"Profile fetch error: {e}")
            return {}

    @property
    def is_connected(self) -> bool:
        return self._connected
