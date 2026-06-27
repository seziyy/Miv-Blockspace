# SpamGuard

SpamGuard is a backend-only prototype for Monad spam detection and on-chain gas floor publication.

## Scope

This repository intentionally implements only these layers:

- `analyzer/`: block listener, spam detector, gas floor model, oracle updater
- `contracts/`: `SpamOracle.sol` and Python deploy script

The frontend/dashboard layer is intentionally omitted.

## Layout

```text
spamguard/
├── analyzer/
│   ├── block_listener.py
│   ├── gas_model.py
│   ├── oracle_updater.py
│   └── spam_detector.py
├── contracts/
│   ├── artifacts/
│   ├── SpamOracle.sol
│   └── deploy.py
├── .env.example
└── requirements.txt
```

## Detection logic

For each new block:

1. Subscribe to new blocks over WebSocket.
2. Pull ERC-20 `Transfer` logs with `eth_getLogs`.
3. Pull full call traces with `debug_traceBlockByNumber`.
4. Mark a transaction as spam when it touches a configured DEX router or pool in its call tree but emits no `Transfer` log.
5. Compute:
   - `spam_gas`
   - `spam_tx_count`
   - `spam_ratio`
6. Use the Category Labs-inspired model to compute a suggested gas floor.
7. Publish `spamGasRatio` and `suggestedGasFloor` to `SpamOracle`.

## Setup

```bash
cd /Users/omerburaksal/Desktop/winner/spamguard
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill in:

- `MONAD_RPC` for HTTP calls and `MONAD_WSS` for `newHeads` subscription
- DEX router/pool allowlist
- deployer and updater keys
- deployed oracle address after deployment

## Deploy

```bash
cd /Users/omerburaksal/Desktop/winner/spamguard/contracts
python deploy.py
```

The script compiles `SpamOracle.sol`, writes `contracts/artifacts/SpamOracle.json`, and deploys the contract.

## Run the updater

```bash
cd /Users/omerburaksal/Desktop/winner/spamguard/analyzer
python oracle_updater.py
```

`oracle_updater.py` uses WebSocket subscription for block discovery, reconnects automatically after disconnects, and catches up any missed blocks over HTTP before resuming live processing.

## Assumptions

- The target Monad RPC supports `eth_subscribe` and `debug_traceBlockByNumber`.
- DEX detection is allowlist-based via `DEX_ADDRESSES`.
- Spam gas defaults to transaction gas limit with `SPAM_GAS_MODE=limit`, matching the hackathon framing. Switch to `used` if you want receipt-based accounting.
