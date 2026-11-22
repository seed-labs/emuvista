"""QuickFIX initiator for the private Stock Service to QuantReplay session."""

from __future__ import annotations

import asyncio
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import quickfix as fix


@dataclass(frozen=True, slots=True)
class ExecutionReport:
    client_order_id: str
    original_client_order_id: str
    exchange_order_id: str
    execution_id: str
    execution_type: str
    order_status: str
    symbol: str
    side: str
    last_quantity: int
    last_price: Decimal | None
    cumulative_quantity: int
    leaves_quantity: int
    average_price: Decimal | None
    contra_account_id: str
    text: str


def _get_field(message, tag: int, default: str = "") -> str:
    field = fix.StringField(tag, "")
    try:
        message.getField(field)
    except fix.FieldNotFound:
        return default
    return field.getValue()


def _optional_decimal(value: str) -> Decimal | None:
    try:
        return Decimal(value) if value else None
    except Exception:
        return None


class _Application(fix.Application):
    def __init__(self, loop: asyncio.AbstractEventLoop):
        super().__init__()
        self.loop = loop
        self.session_id = None
        self.connected = asyncio.Event()
        self.reports: asyncio.Queue[ExecutionReport] = asyncio.Queue()

    def onCreate(self, session_id):
        pass

    def onLogon(self, session_id):
        self.session_id = session_id
        self.loop.call_soon_threadsafe(self.connected.set)

    def onLogout(self, session_id):
        self.session_id = None
        self.loop.call_soon_threadsafe(self.connected.clear)

    def toAdmin(self, message, session_id):
        pass

    def fromAdmin(self, message, session_id):
        pass

    def toApp(self, message, session_id):
        pass

    def fromApp(self, message, session_id):
        msg_type = _get_field(message.getHeader(), 35)
        if msg_type not in {"8", "9"}:
            return
        try:
            client_order_id = _get_field(message, 11)
            original_client_order_id = _get_field(message, 41)
            if msg_type == "9":
                report = ExecutionReport(
                    client_order_id=client_order_id,
                    original_client_order_id=original_client_order_id,
                    exchange_order_id="",
                    execution_id=f"CXLREJ-{client_order_id}-{_get_field(message.getHeader(), 34)}",
                    execution_type="CANCEL_REJECT",
                    order_status=_get_field(message, 39),
                    symbol="",
                    side="",
                    last_quantity=0,
                    last_price=None,
                    cumulative_quantity=0,
                    leaves_quantity=0,
                    average_price=None,
                    contra_account_id="",
                    text=_get_field(message, 58),
                )
                self.loop.call_soon_threadsafe(self.reports.put_nowait, report)
                return
            contra_account_id = ""
            parties = int(_get_field(message, 453, "0"))
            for index in range(1, parties + 1):
                group = fix.Group(453, 448)
                message.getGroup(index, group)
                if _get_field(group, 452) == "17":
                    contra_account_id = _get_field(group, 448)
                    break
            report = ExecutionReport(
                client_order_id=client_order_id,
                original_client_order_id=original_client_order_id,
                exchange_order_id=_get_field(message, 37),
                execution_id=_get_field(message, 17),
                execution_type=_get_field(message, 150),
                order_status=_get_field(message, 39),
                symbol=_get_field(message, 55),
                side=_get_field(message, 54),
                last_quantity=int(_get_field(message, 32, "0")),
                last_price=_optional_decimal(_get_field(message, 31)),
                cumulative_quantity=int(_get_field(message, 14, "0")),
                leaves_quantity=int(_get_field(message, 151, "0")),
                average_price=_optional_decimal(_get_field(message, 6)),
                contra_account_id=contra_account_id,
                text=_get_field(message, 58),
            )
        except (ValueError, TypeError):
            return
        self.loop.call_soon_threadsafe(self.reports.put_nowait, report)


class QuantReplayFixGateway:
    """A single FIXT.1.1 / FIX 5.0 SP2 client session."""

    def __init__(
        self,
        host: str,
        port: int,
        sender_comp_id: str,
        target_comp_id: str,
        store_path: str | Path = "/var/lib/stock/fixstore",
        log_path: str | Path = "/var/log/stock/fix",
    ):
        self.host = host
        self.port = port
        self.sender_comp_id = sender_comp_id
        self.target_comp_id = target_comp_id
        self.store_path = Path(store_path)
        self.log_path = Path(log_path)
        self._initiator = None
        self._application: _Application | None = None
        self._settings_path: Path | None = None

    @property
    def connected(self) -> bool:
        return bool(self._application and self._application.connected.is_set())

    @property
    def reports(self) -> asyncio.Queue[ExecutionReport] | None:
        return self._application.reports if self._application else None

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self.store_path.mkdir(parents=True, exist_ok=True)
        self.log_path.mkdir(parents=True, exist_ok=True)
        config_dir = Path(tempfile.mkdtemp(prefix="stock-fix-"))
        self._settings_path = config_dir / "initiator.cfg"
        self._settings_path.write_text(
            "\n".join(
                [
                    "[DEFAULT]",
                    "ConnectionType=initiator",
                    "ReconnectInterval=5",
                    "HeartBtInt=30",
                    "ResetOnLogon=Y",
                    "StartTime=00:00:00",
                    "EndTime=23:59:59",
                    "FileStorePath=" + str(self.store_path),
                    "FileLogPath=" + str(self.log_path),
                    "UseDataDictionary=Y",
                    "TransportDataDictionary=/usr/local/share/quickfix/FIXT11.xml",
                    "AppDataDictionary=/usr/local/share/quickfix/FIX50SP2.xml",
                    "BeginString=FIXT.1.1",
                    "DefaultApplVerID=9",
                    "SocketConnectHost=" + self.host,
                    "SocketConnectPort=" + str(self.port),
                    "",
                    "[SESSION]",
                    "BeginString=FIXT.1.1",
                    "SenderCompID=" + self.sender_comp_id,
                    "TargetCompID=" + self.target_comp_id,
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        application = _Application(loop)
        settings = fix.SessionSettings(str(self._settings_path))
        store_factory = fix.FileStoreFactory(settings)
        log_factory = fix.FileLogFactory(settings)
        initiator = fix.SocketInitiator(application, store_factory, settings, log_factory)
        initiator.start()
        self._application = application
        self._initiator = initiator

    async def wait_until_connected(self, timeout: float = 10.0) -> None:
        if not self._application:
            raise RuntimeError("FIX gateway has not been started")
        await asyncio.wait_for(self._application.connected.wait(), timeout=timeout)

    async def stop(self) -> None:
        if self._initiator:
            self._initiator.stop()
            self._initiator = None
        self._application = None
        if self._settings_path:
            self._settings_path.unlink(missing_ok=True)

    def _send(self, msg_type: str, fields: dict[int, str]) -> None:
        if not self._application or not self._application.session_id:
            raise ConnectionError("QuantReplay FIX session is not logged on")
        message = fix.Message()
        message.getHeader().setField(fix.StringField(35, msg_type))
        for tag, value in fields.items():
            message.setField(fix.StringField(tag, value))
        if not fix.Session.sendToTarget(message, self._application.session_id):
            raise ConnectionError("QuickFIX did not queue the message for delivery")

    def submit_limit_order(
        self, client_order_id: str, symbol: str, side: str, quantity: int, limit_price: Decimal,
        account_id: str,
    ) -> None:
        if side not in {"BUY", "SELL"} or quantity <= 0 or limit_price <= 0:
            raise ValueError("invalid limit order")
        self._send(
            "D",
            {
                11: client_order_id,
                21: "1",
                38: str(quantity),
                40: "2",
                44: format(limit_price, "f"),
                54: "1" if side == "BUY" else "2",
                55: symbol,
                59: "0",
                60: datetime.now(timezone.utc).strftime("%Y%m%d-%H:%M:%S"),
                1: account_id,
            },
        )
        # QuantReplay reports the contra firm in tag 452/role 17 when available.
        # Tag 1 gives the venue an account identifier for this order.

    def cancel_order(self, cancel_id: str, original_client_order_id: str, symbol: str, side: str) -> None:
        if side not in {"BUY", "SELL"}:
            raise ValueError("invalid order side")
        self._send(
            "F",
            {
                11: cancel_id,
                41: original_client_order_id,
                54: "1" if side == "BUY" else "2",
                55: symbol,
                60: datetime.now(timezone.utc).strftime("%Y%m%d-%H:%M:%S"),
            },
        )
