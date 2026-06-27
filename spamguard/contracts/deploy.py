import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv
from solcx import compile_standard, install_solc
from web3 import Web3


CHAIN_ID = 10143
SOLC_VERSION = "0.8.20"
ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
SOURCE_PATH = ROOT / "SpamOracle.sol"
ARTIFACT_PATH = ROOT / "artifacts" / "SpamOracle.json"
DEPLOYMENT_PATH = ROOT / "deployment.json"
EXPLORER_URL_TEMPLATE = "https://testnet.monadexplorer.com/address/{address}"


def load_env() -> None:
    load_dotenv(PROJECT_ROOT / ".env")


def compile_contract() -> Dict[str, Any]:
    install_solc(SOLC_VERSION)
    source = SOURCE_PATH.read_text()
    compiled = compile_standard(
        {
            "language": "Solidity",
            "sources": {
                "SpamOracle.sol": {
                    "content": source,
                }
            },
            "settings": {
                "outputSelection": {
                    "*": {
                        "*": ["abi", "evm.bytecode.object"],
                    }
                }
            },
        },
        solc_version=SOLC_VERSION,
    )

    contract_data = compiled["contracts"]["SpamOracle.sol"]["SpamOracle"]
    artifact = {
        "abi": contract_data["abi"],
        "bytecode": contract_data["evm"]["bytecode"]["object"],
    }
    ARTIFACT_PATH.write_text(json.dumps(artifact, indent=2))
    return artifact


def build_web3() -> Web3:
    rpc_url = os.environ["MONAD_RPC"]
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    chain_id = w3.eth.chain_id
    if chain_id != CHAIN_ID:
        raise RuntimeError(f"Connected to unexpected chain ID {chain_id}, expected {CHAIN_ID}")
    return w3


def deploy_contract(w3: Web3, artifact: Dict[str, Any]) -> Dict[str, Any]:
    private_key = os.environ["DEPLOYER_PRIVATE_KEY"]
    deployer = w3.eth.account.from_key(private_key)
    contract = w3.eth.contract(abi=artifact["abi"], bytecode=artifact["bytecode"])

    deploy_tx = contract.constructor(deployer.address).build_transaction(
        {
            "from": deployer.address,
            "nonce": w3.eth.get_transaction_count(deployer.address),
            "chainId": CHAIN_ID,
            "gas": int(os.getenv("DEPLOY_GAS_LIMIT", "2500000")),
            "gasPrice": w3.eth.gas_price,
        }
    )
    signed_deploy_tx = deployer.sign_transaction(deploy_tx)
    tx_hash = w3.eth.send_raw_transaction(signed_deploy_tx.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)

    if receipt.status != 1 or not receipt.contractAddress:
        raise RuntimeError(f"Deployment failed, receipt status={receipt.status}")

    return {
        "deployer": deployer,
        "receipt": receipt,
        "contract": w3.eth.contract(address=receipt.contractAddress, abi=artifact["abi"]),
        "deploy_tx_hash": tx_hash.hex(),
    }


def save_deployment(receipt: Any, abi: List[Dict[str, Any]]) -> None:
    payload = {
        "address": receipt.contractAddress,
        "abi": abi,
        "block_number": receipt.blockNumber,
        "chain_id": CHAIN_ID,
        "deployed_at": datetime.now(timezone.utc).isoformat(),
    }
    DEPLOYMENT_PATH.write_text(json.dumps(payload, indent=2))


def run_test_update(w3: Web3, deployer: Any, contract: Any) -> str:
    nonce = w3.eth.get_transaction_count(deployer.address)
    gas_price = w3.eth.gas_price
    function = resolve_update_function(contract)
    args = build_test_update_args(function.abi)
    tx = function(*args).build_transaction(
        {
            "from": deployer.address,
            "nonce": nonce,
            "chainId": CHAIN_ID,
            "gas": int(os.getenv("ORACLE_UPDATE_GAS", "250000")),
            "gasPrice": gas_price,
        }
    )
    signed_tx = deployer.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    if receipt.status != 1:
        raise RuntimeError("Test updateMetrics transaction reverted")
    return tx_hash.hex()


def resolve_update_function(contract: Any) -> Any:
    for function_name in ("updateMetrics", "updateSpamMetrics"):
        if hasattr(contract.functions, function_name):
            return getattr(contract.functions, function_name)
    raise RuntimeError("No compatible update function found in contract ABI")


def build_test_update_args(function_abi: Dict[str, Any]) -> List[int]:
    arg_count = len(function_abi.get("inputs", []))
    if arg_count == 4:
        return [500, 1_000_000, 50_000, 1]
    if arg_count == 3:
        return [500, 1_000_000, 1]
    raise RuntimeError(f"Unsupported update function arity: {arg_count}")


def main() -> int:
    try:
        load_env()
        artifact = compile_contract()
        w3 = build_web3()
        deployment = deploy_contract(w3, artifact)
        receipt = deployment["receipt"]
        contract = deployment["contract"]
        deployer = deployment["deployer"]

        save_deployment(receipt, artifact["abi"])
        test_tx_hash = run_test_update(w3, deployer, contract)

        address = receipt.contractAddress
        print(f"SpamOracle deployed at: {address}")
        print(f"Explorer: {EXPLORER_URL_TEMPLATE.format(address=address)}")
        print(f"Deployment tx: {deployment['deploy_tx_hash']}")
        print(f"Test update tx: {test_tx_hash}")
        print(f"Deployment metadata saved to: {DEPLOYMENT_PATH}")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"Deployment failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
