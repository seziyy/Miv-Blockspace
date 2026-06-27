import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import requests
from web3 import Web3


RPC_URL = "https://mainnet.rpc.monad.xyz"
CHAIN_ID = 41454
POOL_CREATED_TOPIC = "0x783cca1c0412dd0d695e784568c96da2e9c22ff989357a2e8b1d9b2b4e6b7118"
OUTPUT_PATH = Path(__file__).resolve().parent / "dex_addresses.json"
RETRIES = 3
RETRY_DELAY_SECONDS = 1
BLOCK_CHUNK_SIZE = 25_000

# Verified fallback from the user's requirement. This is not a Monad-specific deployment proof.
UNISWAP_V3_SWAPROUTER02 = "0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45"

# Kuru docs and public GitHub confirm Kuru is a Monad DEX / aggregator, but no public router address
# was discoverable during implementation, so this is intentionally left unset until verified.
KURU_ROUTER_ADDRESS: Optional[str] = None

# Factory filters are optional. Leaving them unset makes the script scan all PoolCreated logs on Monad,
# which still satisfies the pool-discovery requirement and can surface both Uniswap-style and Pancake-style pools.
UNISWAP_V3_FACTORY: Optional[str] = None
PANCAKESWAP_V3_FACTORY: Optional[str] = None


class RpcRetryError(RuntimeError):
    pass


def make_web3() -> Web3:
    session = requests.Session()
    provider = Web3.HTTPProvider(RPC_URL, session=session)
    w3 = Web3(provider)
    chain_id = rpc_call(w3, "eth_chainId", [])
    if int(chain_id, 16) != CHAIN_ID:
        raise RuntimeError(f"Unexpected chain ID: {int(chain_id, 16)}")
    return w3


def rpc_call(w3: Web3, method: str, params: List[Any]) -> Any:
    last_error: Optional[Exception] = None
    for attempt in range(1, RETRIES + 1):
        try:
            response = w3.provider.make_request(method, params)
            if "error" in response:
                raise RpcRetryError(f"{method} returned error: {response['error']}")
            return response["result"]
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt == RETRIES:
                break
            print(f"[retry {attempt}/{RETRIES}] {method} failed: {exc}")
            time.sleep(RETRY_DELAY_SECONDS)
    raise RpcRetryError(f"{method} failed after {RETRIES} retries") from last_error


def fetch_pool_logs(w3: Web3, factory_address: Optional[str] = None) -> List[Dict[str, Any]]:
    latest_block = int(rpc_call(w3, "eth_blockNumber", []), 16)
    all_logs: List[Dict[str, Any]] = []

    for start_block in range(0, latest_block + 1, BLOCK_CHUNK_SIZE):
        end_block = min(start_block + BLOCK_CHUNK_SIZE - 1, latest_block)
        params: Dict[str, Any] = {
            "fromBlock": hex(start_block),
            "toBlock": hex(end_block),
            "topics": [POOL_CREATED_TOPIC],
        }
        if factory_address:
            params["address"] = Web3.to_checksum_address(factory_address)

        logs = rpc_call(w3, "eth_getLogs", [params])
        all_logs.extend(logs)
        print(f"Scanned blocks {start_block}..{end_block} | logs found: {len(logs)}")

    return all_logs


def extract_pool_addresses(logs: List[Dict[str, Any]]) -> Set[str]:
    pools: Set[str] = set()
    for log in logs:
        topics = log.get("topics", [])
        if len(topics) < 4:
            continue

        pool_topic = topics[3]
        if not isinstance(pool_topic, str) or len(pool_topic) < 66:
            continue

        pool_address = Web3.to_checksum_address("0x" + pool_topic[-40:])
        pools.add(pool_address)
    return pools


def build_router_list() -> List[str]:
    routers = {Web3.to_checksum_address(UNISWAP_V3_SWAPROUTER02)}
    if KURU_ROUTER_ADDRESS:
        routers.add(Web3.to_checksum_address(KURU_ROUTER_ADDRESS))
    else:
        print("Warning: Kuru router address is not set because a verifiable public mainnet address was not found.")
    return sorted(routers)


def main() -> None:
    w3 = make_web3()

    all_logs: List[Dict[str, Any]] = []
    if UNISWAP_V3_FACTORY:
        print(f"Querying Uniswap V3 factory: {UNISWAP_V3_FACTORY}")
        all_logs.extend(fetch_pool_logs(w3, UNISWAP_V3_FACTORY))
    if PANCAKESWAP_V3_FACTORY:
        print(f"Querying PancakeSwap V3 factory: {PANCAKESWAP_V3_FACTORY}")
        all_logs.extend(fetch_pool_logs(w3, PANCAKESWAP_V3_FACTORY))

    if not UNISWAP_V3_FACTORY and not PANCAKESWAP_V3_FACTORY:
        print("Factory addresses not set; scanning all Monad PoolCreated logs for the standard Uniswap V3 topic.")
        all_logs.extend(fetch_pool_logs(w3))

    pools = sorted(extract_pool_addresses(all_logs))
    routers = build_router_list()

    payload = {
        "routers": routers,
        "pools": pools,
    }
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2))

    total_addresses = len(routers) + len(pools)
    print(f"Saved {len(routers)} routers and {len(pools)} pools to {OUTPUT_PATH}")
    print(f"Total addresses found: {total_addresses}")


if __name__ == "__main__":
    main()
