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

        http_rpc = os.environ["MONAD_RPC"]
        oracle_address = Web3.to_checksum_address(os.environ["ORACLE_ADDRESS"])
        updater_key = os.environ["UPDATER_PRIVATE_KEY"]

        self.w3 = Web3(Web3.HTTPProvider(http_rpc))
        self.account = self.w3.eth.account.from_key(updater_key)
        self.last_processed_block = max(self.w3.eth.block_number - 1, 0)
        artifact = load_artifact()
        self.oracle = self.w3.eth.contract(address=oracle_address, abi=artifact["abi"])
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

    def process_block(self, block_number: int) -> None:
        started_at = time.perf_counter()
        metrics = self.detector.analyze_block(block_number)
        suggested_floor = self.model.compute_optimal_gas_floor(metrics.spam_ratio, metrics.total_gas)
        equilibrium = self.model.compute_expected_spam_equilibrium(suggested_floor)
        plateau = self.model.compute_plateau_threshold(suggested_floor)
        tx_hash = self.push_metrics(block_number, metrics.spam_ratio, suggested_floor)
        duration_ms = (time.perf_counter() - started_at) * 1000
        self.last_processed_block = block_number

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
        nonce = self.w3.eth.get_transaction_count(self.account.address)
        gas_price = self.w3.eth.gas_price
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
        sent_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        return sent_hash.hex()

    def catch_up_to(self, latest_block: int) -> None:
        if latest_block <= self.last_processed_block:
            return

        for block_number in range(self.last_processed_block + 1, latest_block + 1):
            self.process_block(block_number)

    def run(self) -> None:
        while True:
            try:
                latest_block = self.w3.eth.block_number
                self.catch_up_to(latest_block)
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                logger.warning("HTTP polling error: %s", exc)
            time.sleep(1)


def main() -> None:
    service = OracleUpdaterService()
    try:
        service.run()
    except KeyboardInterrupt:
        logger.info("Oracle updater stopped by user.")


if __name__ == "__main__":
    main()
