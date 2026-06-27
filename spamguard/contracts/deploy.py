import json
import os
from pathlib import Path

from dotenv import load_dotenv
from solcx import compile_standard, install_solc
from web3 import Web3


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
SOURCE_PATH = ROOT / "SpamOracle.sol"
ARTIFACT_PATH = ROOT / "artifacts" / "SpamOracle.json"
SOLC_VERSION = "0.8.20"


def compile_contract() -> dict:
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


def deploy() -> str:
    load_dotenv(PROJECT_ROOT / ".env")

    rpc_url = os.environ["MONAD_RPC_HTTP"]
    private_key = os.environ["DEPLOYER_PRIVATE_KEY"]
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    deployer = w3.eth.account.from_key(private_key)
    updater_raw = os.getenv("ORACLE_UPDATER_ADDRESS") or deployer.address
    updater_address = Web3.to_checksum_address(updater_raw)

    artifact = compile_contract()
    contract = w3.eth.contract(abi=artifact["abi"], bytecode=artifact["bytecode"])

    transaction = contract.constructor(updater_address).build_transaction(
        {
            "from": deployer.address,
            "nonce": w3.eth.get_transaction_count(deployer.address),
            "gas": int(os.getenv("DEPLOY_GAS_LIMIT", "1800000")),
            "gasPrice": w3.eth.gas_price,
        }
    )
    signed = deployer.sign_transaction(transaction)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    return receipt.contractAddress


if __name__ == "__main__":
    address = deploy()
    print(f"SpamOracle deployed at: {address}")
