import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv
from web3 import Web3

from gas_model import CategoryLabsModel
from spam_detector import SpamDetector
from ws_server import broadcast, start_server


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = ROOT / "contracts" / "artifacts" / "SpamOracle.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def load_artifact() -> Dict[str, Any]:
    with ARTIFACT_PATH.open() as handle:
        return json.load(handle)


class OracleUpdaterService:
    def __init__(self) -> None:
        load_dotenv(ROOT / ".env")

        analysis_rpc = os.environ["MONAD_RPC"]
        oracle_rpc = os.getenv("MONAD_TESTNET_RPC", "https://testnet-rpc.monad.xyz")
        oracle_address = os.getenv("ORACLE_ADDRESS", "").strip()
        updater_key = os.environ["UPDATER_PRIVATE_KEY"]

        self.w3 = Web3(Web3.HTTPProvider(analysis_rpc))
        self.oracle_w3 = Web3(Web3.HTTPProvider(oracle_rpc))
        self.account = self.oracle_w3.eth.account.from_key(updater_key)
        self.last_processed_block = max(self.w3.eth.block_number - 1, 0)
        artifact = load_artifact()
        self.oracle = (
            self.oracle_w3.eth.contract(address=Web3.to_checksum_address(oracle_address), abi=artifact["abi"])
            if oracle_address
            else None
        )
        self.detector = SpamDetector(
            self.w3,
            spam_gas_mode=os.getenv("SPAM_GAS_MODE", "limit"),
        )
        self.model = CategoryLabsModel(
            d0=float(os.getenv("MODEL_D0", "1200")),
            beta=float(os.getenv("MODEL_BETA", "6")),
            s=float(os.getenv("MODEL_SLOT_COST", "20")),
            r0=float(os.getenv("MODEL_R0", "6000")),
            target_spam_ratio=float(os.getenv("TARGET_SPAM_RATIO", "0.15")),
            baseline_floor_wei=int(os.getenv("BASELINE_FLOOR_WEI", "1000000")),
        )

    async def process_block(self, block_number: int) -> None:
        started_at = time.perf_counter()
        metrics = self.detector.analyze_block(block_number)
        suggested_floor = self.model.compute_optimal_gas_floor(metrics.spam_ratio, metrics.total_gas)
        equilibrium = self.model.compute_expected_spam_equilibrium(suggested_floor)
        plateau = self.model.compute_plateau_threshold(suggested_floor)
        tx_hash = None
        try:
            tx_hash = self.push_metrics(block_number, metrics.spam_ratio, suggested_floor)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Oracle write skipped for block %s: %s", block_number, exc)
        duration_ms = (time.perf_counter() - started_at) * 1000
        self.last_processed_block = block_number
        payload = {
            "block_number": block_number,
            "spam_ratio": metrics.spam_ratio,
            "spam_gas": metrics.spam_gas,
            "total_gas": metrics.total_gas,
            "total_txs": metrics.total_txs,
            "spam_tx_count": len(metrics.spam_txs),
            "spam_txs": [spam_tx.tx_hash for spam_tx in metrics.spam_txs[:10]],
            "suggested_floor": suggested_floor,
            "suggested_floor_gwei": suggested_floor / 1e9,
            "equilibrium": equilibrium,
            "plateau": plateau,
            "analysis_time_ms": metrics.analysis_time_ms,
            "oracle_tx_hash": tx_hash,
            "oracle_tx": tx_hash,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

        await broadcast(payload)

        logger.info(
            "timestamp=%s block=%s processing_ms=%.2f spam_ratio=%.2f%% spam_txs=%s suggested_floor=%s plateau=%s equilibrium=%.2f oracle_tx=%s",
            time.strftime("%Y-%m-%d %H:%M:%S"),
            block_number,
            duration_ms,
            metrics.spam_ratio * 100,
            len(metrics.spam_txs),
            suggested_floor,
            plateau,
            equilibrium,
            tx_hash,
        )

    def push_metrics(self, block_number: int, spam_ratio: float, suggested_floor: int) -> str:
        if self.oracle is None:
            raise RuntimeError("ORACLE_ADDRESS is empty; oracle writes are disabled")

        nonce = self.oracle_w3.eth.get_transaction_count(self.account.address)
        gas_price = self.oracle_w3.eth.gas_price
        tx = self.oracle.functions.updateSpamMetrics(
            int(spam_ratio * 10_000),
            suggested_floor,
            block_number,
        ).build_transaction(
            {
                "from": self.account.address,
                "nonce": nonce,
                "gas": int(os.getenv("ORACLE_UPDATE_GAS", "200000")),
                "gasPrice": gas_price,
            }
        )
        signed = self.account.sign_transaction(tx)
        try:
            sent_hash = self.oracle_w3.eth.send_raw_transaction(signed.raw_transaction)
        except Exception as exc:  # noqa: BLE001
            message = str(exc).lower()
            if "insufficient funds" in message or "insufficient balance" in message:
                raise RuntimeError("insufficient balance for oracle write") from exc
            raise
        self.oracle_w3.eth.wait_for_transaction_receipt(sent_hash)
        return sent_hash.hex()

    async def catch_up_to(self, latest_block: int) -> None:
        if latest_block <= self.last_processed_block:
            return

        for block_number in range(self.last_processed_block + 1, latest_block + 1):
            await self.process_block(block_number)

    async def run(self) -> None:
        while True:
            try:
                latest_block = self.w3.eth.block_number
                await self.catch_up_to(latest_block)
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                logger.warning("HTTP polling error: %s", exc)
            await asyncio.sleep(1)


async def main() -> None:
    service = OracleUpdaterService()
    server = await start_server()
    server_task = asyncio.create_task(server.wait_closed())
    try:
        await service.run()
    except KeyboardInterrupt:
        logger.info("Oracle updater stopped by user.")
    finally:
        server.close()
        await server.wait_closed()
        server_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
