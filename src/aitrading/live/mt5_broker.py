"""MT5 order execution.

Safety properties, in order of importance:

1. DEMO BY DEFAULT. The broker refuses to construct against a live account
   unless allow_live=True is passed explicitly. Nothing in this repository sets
   that flag; you have to type it yourself.
2. Idempotent reconciliation. The bot computes a TARGET position and sends the
   delta needed to reach it. If a fill is missed, dropped or partially executed,
   the next cycle corrects it. It never accumulates orders on the assumption that
   previous ones worked.
3. Every order carries a deviation cap, so a request cannot be filled at an
   arbitrarily worse price during a spread spike.
"""

import time
from dataclasses import dataclass
from typing import Optional


class LiveAccountRefused(RuntimeError):
    """Raised when pointed at a real-money account without explicit consent."""


@dataclass
class Tick:
    bid: float
    ask: float
    time: float

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread(self) -> float:
        return self.ask - self.bid


@dataclass
class OrderResult:
    ok: bool
    retcode: int
    comment: str
    filled_lots: float = 0.0
    price: float = 0.0


def _mt5():
    try:
        import MetaTrader5 as mt5  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "MetaTrader5 not installed. Run: pip install MetaTrader5\n"
            "Requires Windows (or Wine) and a running MT5 terminal."
        ) from exc
    return mt5


class MT5Broker:
    def __init__(self, symbol: str, magic: int = 20260911,
                 allow_live: bool = False, deviation_points: int = 20,
                 terminal_path: Optional[str] = None):
        mt5 = _mt5()
        kwargs = {"path": terminal_path} if terminal_path else {}
        if not mt5.initialize(**kwargs):
            raise RuntimeError(f"MT5 initialize() failed: {mt5.last_error()}")

        acct = mt5.account_info()
        if acct is None:
            raise RuntimeError("account_info() returned None -- not logged in?")

        is_demo = acct.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO
        if not is_demo and not allow_live:
            mt5.shutdown()
            raise LiveAccountRefused(
                f"Account {acct.login} is a {'REAL' if acct.trade_mode == 0 else 'CONTEST'} "
                f"account.\nThis bot refuses live accounts unless you pass "
                f"--i-understand-live-risk.\n"
                f"Validated expectation for this strategy is NO measurable edge "
                f"(see docs/results/xauusd-findings.md). Use a demo account."
            )

        info = mt5.symbol_info(symbol)
        if info is None:
            raise RuntimeError(f"symbol {symbol!r} not found at this broker")
        if not info.visible:
            mt5.symbol_select(symbol, True)

        self.mt5 = mt5
        self.symbol = symbol
        self.magic = magic
        self.deviation = deviation_points
        self.is_demo = is_demo
        self.account_login = acct.login
        self.currency = acct.currency
        self.contract_size = float(info.trade_contract_size)
        self.min_lot = float(info.volume_min)
        self.lot_step = float(info.volume_step)
        self.max_lot = float(info.volume_max)
        self.digits = int(info.digits)

    # -- state --------------------------------------------------------------
    def equity(self) -> float:
        a = self.mt5.account_info()
        return float(a.equity) if a else 0.0

    def tick(self) -> Optional[Tick]:
        t = self.mt5.symbol_info_tick(self.symbol)
        if not t or t.bid <= 0 or t.ask <= 0:
            return None
        return Tick(bid=float(t.bid), ask=float(t.ask), time=float(t.time))

    def position_lots(self) -> float:
        """Net signed position for this symbol and magic number."""
        positions = self.mt5.positions_get(symbol=self.symbol) or []
        net = 0.0
        for p in positions:
            if p.magic and p.magic != self.magic:
                continue
            net += p.volume if p.type == self.mt5.POSITION_TYPE_BUY else -p.volume
        return round(net, 8)

    # -- execution ----------------------------------------------------------
    def reconcile_to(self, target_lots: float) -> Optional[OrderResult]:
        """Send whichever single order moves the net position to `target_lots`.

        Returns None when no action is needed. This is the only order-sending
        path, which is what makes the bot recoverable after any failure.
        """
        current = self.position_lots()
        delta = round(target_lots - current, 8)
        if abs(delta) < self.min_lot:
            return None

        # Snap to the broker's grid, rounding DOWN so we never overshoot a cap.
        steps = int(abs(delta) / self.lot_step)
        volume = round(steps * self.lot_step, 8)
        if volume < self.min_lot:
            return None
        volume = min(volume, self.max_lot)

        return self._market_order(volume, buy=delta > 0)

    def close_all(self) -> Optional[OrderResult]:
        return self.reconcile_to(0.0)

    def _market_order(self, volume: float, buy: bool) -> OrderResult:
        mt5 = self.mt5
        t = self.tick()
        if t is None:
            return OrderResult(False, -1, "no tick available")

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.symbol,
            "volume": float(volume),
            "type": mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL,
            "price": t.ask if buy else t.bid,
            "deviation": self.deviation,
            "magic": self.magic,
            "comment": "aitrading",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result is None:
            return OrderResult(False, -1, f"order_send returned None: {mt5.last_error()}")

        ok = result.retcode == mt5.TRADE_RETCODE_DONE
        if not ok and result.retcode == mt5.TRADE_RETCODE_INVALID_FILL:
            # Some brokers reject IOC; retry once with FOK.
            request["type_filling"] = mt5.ORDER_FILLING_FOK
            result = mt5.order_send(request)
            ok = result is not None and result.retcode == mt5.TRADE_RETCODE_DONE

        return OrderResult(
            ok=ok,
            retcode=int(result.retcode),
            comment=str(result.comment),
            filled_lots=float(getattr(result, "volume", 0.0) or 0.0),
            price=float(getattr(result, "price", 0.0) or 0.0),
        )

    def closed_pnl_since(self, since_ts: float) -> float:
        """Realised P&L (including commission and swap) since a timestamp."""
        deals = self.mt5.history_deals_get(since_ts, time.time()) or []
        total = 0.0
        for d in deals:
            if d.symbol != self.symbol:
                continue
            if d.magic and d.magic != self.magic:
                continue
            total += float(d.profit) + float(d.commission) + float(d.swap)
        return total

    def shutdown(self) -> None:
        try:
            self.mt5.shutdown()
        except Exception:
            pass
