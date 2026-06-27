import json
import os
import time
from datetime import datetime

from dotenv import load_dotenv
from web3 import Web3


GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"

TRANSFER_TOPIC = Web3.keccak(text="Transfer(address,address,uint256)").hex()
DEX_ADDRESSES = {
    "0x8cf67893c236963233023b56ac56a185b042866f".lower(),
    "0x368ee51e47a594fe1e9908b48228748a30bc7ca4".lower(),
    "0x34b6552d57a35a1d042ccae1951bd1c370112a6f".lower(),
    "0x69df8a43b52033b11b360f74e90f7861f2506292".lower(),
    "0xd32edf6642d917dbbe7b8bf8e5d6f5df6a9fff58".lower(),
    "0x98dc6e90d4c2f212ed9d124ad2afba4833268633".lower(),
    "0x5d8ffa5f7c6a42470b4ec61a8cdabb799fd3765a".lower(),
    "0x0d97dc33264bfc1c226207428a79b26757fb9dc3".lower(),
}


def load_web3():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    load_dotenv(os.path.join(root_dir, ".env"))
    rpc_url = os.getenv("MONAD_RPC")
    if not rpc_url:
        raise RuntimeError("MONAD_RPC is missing from .env")
    return Web3(Web3.HTTPProvider(rpc_url))


def fetch_transfer_tx_hashes(w3, block_number):
    logs = w3.eth.get_logs(
        {
            "fromBlock": block_number,
            "toBlock": block_number,
            "topics": [TRANSFER_TOPIC],
        }
    )
    return {log["transactionHash"].hex() for log in logs}

def color_for_ratio(ratio):
    if ratio < 0.10:
        return GREEN
    if ratio <= 0.20:
        return YELLOW
    return RED


def suggest_floor_gwei(w3, average_spam_ratio):
    base_floor_gwei = max(w3.eth.gas_price / 1e9, 0.001)
    if average_spam_ratio < 0.10:
        return round(base_floor_gwei, 4)
    if average_spam_ratio <= 0.20:
        return round(base_floor_gwei * 1.5, 4)
    return round(base_floor_gwei * 2.0, 4)


def process_block(w3, block_number):
    started_at = time.time()
    block = w3.eth.get_block(block_number, full_transactions=True)
    transfer_txs = fetch_transfer_tx_hashes(w3, block_number)

    spam_txs = []
    spam_gas = 0
    for tx in block["transactions"]:
        tx_hash = tx["hash"].hex()
        to_address = tx.get("to")
        if to_address and to_address.lower() in DEX_ADDRESSES and tx_hash not in transfer_txs:
            spam_txs.append(tx_hash)
            spam_gas += int(tx["gas"])

    total_txs = len(block["transactions"])
    total_gas = int(block["gasUsed"])
    spam_ratio = (spam_gas / total_gas) if total_gas else 0.0
    elapsed_ms = (time.time() - started_at) * 1000
    floor_gwei = suggest_floor_gwei(w3, spam_ratio)

    color = color_for_ratio(spam_ratio)
    print(
        f"{color}Block {block_number} | TXs: {total_txs} | Spam TXs: {len(spam_txs)} | "
        f"Spam: {spam_ratio * 100:.2f}% | Floor: {floor_gwei:.4f} gwei | Time: {elapsed_ms:.0f}ms{RESET}"
    )

    return {
        "block_number": block_number,
        "spam_ratio": spam_ratio,
        "spam_gas": spam_gas,
        "floor_gwei": floor_gwei,
    }


def load_contract_address():
    deployment_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "contracts", "deployment.json")
    if not os.path.exists(deployment_path):
        return None
    with open(deployment_path) as handle:
        payload = json.load(handle)
    return payload.get("address")


def main():
    w3 = load_web3()
    latest_block = w3.eth.block_number

    print("=== SpamGuard Demo — Monad Spam MEV Monitor ===")
    print(f"Started at: {datetime.utcnow().isoformat()}Z")
    print(f"Latest block: {latest_block}")
    print("")

    results = []
    for block_number in range(latest_block - 4, latest_block + 1):
        results.append(process_block(w3, block_number))

    ratios = [result["spam_ratio"] for result in results]
    total_spam_gas = sum(result["spam_gas"] for result in results)
    average_spam_ratio = sum(ratios) / len(ratios)
    min_spam_ratio = min(ratios)
    max_spam_ratio = max(ratios)
    suggested_floor = suggest_floor_gwei(w3, average_spam_ratio)

    print("")
    print("=== Summary ===")
    print(f"Average spam ratio: {average_spam_ratio * 100:.2f}%")
    print(f"Min spam ratio: {min_spam_ratio * 100:.2f}%")
    print(f"Max spam ratio: {max_spam_ratio * 100:.2f}%")
    print(f"Estimated spam gas wasted: {total_spam_gas}")
    print(f"Suggested action: raise gas floor to {suggested_floor:.4f} gwei")

    contract_address = load_contract_address()
    if contract_address:
        print(f"Contract: {contract_address}")
    else:
        print("Contract not yet deployed")


if __name__ == "__main__":
    main()
