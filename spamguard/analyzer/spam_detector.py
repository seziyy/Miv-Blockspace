import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from web3 import Web3


TRANSFER_SIG = Web3.keccak(text="Transfer(address,address,uint256)").hex()
DEFAULT_TRACE_TIMEOUT = "20s"
DEFAULT_DEX_ROUTERS = {
    "0xfe31f71c1b106eac32f1a19239c9a9a72ddfb900",
    "0x0d97dc33264bfc1c226207428a79b26757fb9dc3",
}
DEFAULT_DEX_POOLS: Set[str] = {
    "0x204faca1764b154221e35c0d20abb3c525710498",
}
DEX_ADDRESS_FILE = Path(__file__).resolve().parent / "dex_addresses.json"

logger = logging.getLogger(__name__)


@dataclass
class SpamTransaction:
    tx_hash: str
    confidence: str
    gas: int


@dataclass
class SpamResult:
    block_number: int
    total_txs: int
    spam_txs: List[SpamTransaction]
    spam_gas: int
    total_gas: int
    spam_ratio: float
    analysis_time_ms: float

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["spam_tx_count"] = len(self.spam_txs)
        return payload


class TraceUnsupportedError(RuntimeError):
    pass


class SpamDetector:
    def __init__(
        self,
        w3: Web3,
        dex_addresses: Optional[Iterable[str]] = None,
        trace_timeout: str = DEFAULT_TRACE_TIMEOUT,
        spam_gas_mode: str = "limit",
    ):
        self.w3 = w3
        self.trace_timeout = trace_timeout
        self.spam_gas_mode = spam_gas_mode
        router_addresses, pool_addresses = self._load_dex_addresses()
        if dex_addresses:
            router_addresses.update(self._normalize_addresses(dex_addresses))
        self.dex_router_addresses = router_addresses
        self.dex_pool_addresses = pool_addresses
        self.dex_addresses = self.dex_router_addresses | self.dex_pool_addresses

    def analyze_block(self, block_number: int) -> SpamResult:
        started_at = time.perf_counter()
        block = self.w3.eth.get_block(block_number, full_transactions=True)
        total_gas = int(block["gasUsed"])
        transactions = list(block["transactions"])
        transfer_txs = self._fetch_transfer_tx_hashes(block_number)
        dex_matches = self._fetch_dex_touching_transactions(block_number, transactions)

        spam_txs: List[SpamTransaction] = []
        spam_gas = 0
        for tx in transactions:
            tx_hash = tx["hash"].hex()
            confidence = dex_matches.get(tx_hash)
            if not confidence or tx_hash in transfer_txs:
                continue

            gas_value = self._tx_gas_value(tx)
            spam_txs.append(
                SpamTransaction(
                    tx_hash=tx_hash,
                    confidence=confidence,
                    gas=gas_value,
                )
            )
            spam_gas += gas_value

        analysis_time_ms = (time.perf_counter() - started_at) * 1000
        result = SpamResult(
            block_number=block_number,
            total_txs=len(transactions),
            spam_txs=spam_txs,
            spam_gas=spam_gas,
            total_gas=total_gas,
            spam_ratio=(spam_gas / total_gas) if total_gas else 0.0,
            analysis_time_ms=analysis_time_ms,
        )
        logger.info(
            "Block %s analyzed in %.2fms | total_txs=%s spam_txs=%s spam_ratio=%.2f%%",
            block_number,
            analysis_time_ms,
            result.total_txs,
            len(result.spam_txs),
            result.spam_ratio * 100,
        )
        return result

    def _fetch_transfer_tx_hashes(self, block_number: int) -> Set[str]:
        logs = self.w3.eth.get_logs(
            {
                "fromBlock": block_number,
                "toBlock": block_number,
                "topics": [TRANSFER_SIG],
            }
        )
        return {log["transactionHash"].hex() for log in logs}

    def _fetch_dex_touching_transactions(self, block_number: int, transactions: List[Any]) -> Dict[str, str]:
        try:
            return self._extract_dex_matches_from_block_trace(block_number, transactions)
        except TraceUnsupportedError as exc:
            logger.warning("debug_traceBlockByNumber unavailable for block %s, falling back to tx.to only: %s", block_number, exc)
            return self._fallback_match_from_tx_to(transactions)

    def _extract_dex_matches_from_block_trace(self, block_number: int, transactions: List[Any]) -> Dict[str, str]:
        traces = self._trace_block(block_number)
        tx_hashes = {tx["hash"].hex() for tx in transactions}
        matches: Dict[str, str] = {}

        for trace in traces:
            tx_hash = self._extract_tx_hash(trace)
            if not tx_hash or tx_hash not in tx_hashes:
                continue

            trace_result = trace.get("result", trace)
            confidence = self._trace_confidence(trace_result)
            if confidence:
                matches[tx_hash] = confidence

        for tx in transactions:
            tx_hash = tx["hash"].hex()
            top_level_confidence = self._top_level_confidence(tx.get("to"))
            if top_level_confidence == "high":
                matches[tx_hash] = "high"
            elif top_level_confidence == "medium" and tx_hash not in matches:
                matches[tx_hash] = "medium"

        return matches

    def _trace_block(self, block_number: int) -> List[Dict[str, Any]]:
        params = [
            hex(block_number),
            {
                "tracer": "callTracer",
                "timeout": self.trace_timeout,
            },
        ]
        try:
            response = self.w3.provider.make_request("debug_traceBlockByNumber", params)
        except Exception as exc:  # noqa: BLE001
            raise self._map_trace_error(exc) from exc
        if "error" in response:
            raise self._map_trace_error(response["error"])

        result = response.get("result")
        if result is None:
            raise TraceUnsupportedError("missing trace result")
        if not isinstance(result, list):
            raise RuntimeError(f"Unexpected trace response format: {type(result)!r}")
        return result

    def _map_trace_error(self, error: Any) -> Exception:
        message = str(error).lower()
        if "method not found" in message or "unsupported" in message or "400" in message:
            return TraceUnsupportedError(str(error))
        return RuntimeError(f"debug_traceBlockByNumber failed: {error}")

    def _trace_confidence(self, call_node: Dict[str, Any]) -> Optional[str]:
        current_confidence = self._top_level_confidence(call_node.get("to"))
        best_confidence = current_confidence

        for nested in call_node.get("calls", []) or []:
            nested_confidence = self._trace_confidence(nested)
            best_confidence = self._prefer_confidence(best_confidence, nested_confidence)

        return best_confidence

    def _top_level_confidence(self, to_addr: Optional[str]) -> Optional[str]:
        if not isinstance(to_addr, str):
            return None
        normalized = to_addr.lower()
        if normalized in self.dex_router_addresses:
            return "high"
        if normalized in self.dex_pool_addresses:
            return "medium"
        return None

    def _prefer_confidence(self, current: Optional[str], candidate: Optional[str]) -> Optional[str]:
        order = {"high": 2, "medium": 1, None: 0}
        return candidate if order[candidate] > order[current] else current

    def _extract_tx_hash(self, trace: Dict[str, Any]) -> Optional[str]:
        for key in ("txHash", "transactionHash"):
            value = trace.get(key)
            if isinstance(value, str):
                return value
        return None

    def _fallback_match_from_tx_to(self, transactions: List[Any]) -> Dict[str, str]:
        matches: Dict[str, str] = {}
        for tx in transactions:
            confidence = self._top_level_confidence(tx.get("to"))
            if confidence:
                matches[tx["hash"].hex()] = confidence
        return matches

    def _tx_gas_value(self, tx: Any) -> int:
        if self.spam_gas_mode == "used":
            receipt = self.w3.eth.get_transaction_receipt(tx["hash"])
            return int(receipt["gasUsed"])
        return int(tx["gas"])

    def _load_dex_addresses(self) -> Tuple[Set[str], Set[str]]:
        if DEX_ADDRESS_FILE.exists():
            try:
                payload = json.loads(DEX_ADDRESS_FILE.read_text())
                routers = self._normalize_addresses(payload.get("routers", []))
                pools = self._normalize_addresses(payload.get("pools", []))
                return routers or self._normalize_addresses(DEFAULT_DEX_ROUTERS), pools
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to load %s: %s", DEX_ADDRESS_FILE, exc)

        env_addresses = [addr.strip() for addr in os.getenv("DEX_ADDRESSES", "").split(",") if addr.strip()]
        routers = self._normalize_addresses(env_addresses) or self._normalize_addresses(DEFAULT_DEX_ROUTERS)
        pools = self._normalize_addresses(DEFAULT_DEX_POOLS)
        logger.warning("Using fallback DEX address configuration; %s not found or unreadable.", DEX_ADDRESS_FILE.name)
        return routers, pools

    def _normalize_addresses(self, addresses: Iterable[str]) -> Set[str]:
        normalized: Set[str] = set()
        for address in addresses:
            if not address:
                continue
            normalized.add(Web3.to_checksum_address(address).lower())
        return normalized
