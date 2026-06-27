import React, { useState, useEffect } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
} from "recharts";

const WS_PROTOCOL = window.location.protocol === "https:" ? "wss" : "ws";
const WS_URL = `${WS_PROTOCOL}://${window.location.hostname}:8765`;
const EXPLORER_BASE_URL = "https://testnet.monadexplorer.com";
const ORACLE_ADDRESS = "0x1c80d99dF50075D456830016d8a2ba318d1cb321";
const PAPER_URL = "https://arxiv.org/abs/2604.00234";
const STORAGE_KEY = "spamguard_blocks_v1";

function formatPercent(value) {
  if (typeof value !== "number" || Number.isNaN(value)) return "\u2014";
  return `${(value * 100).toFixed(1)}%`;
}

function formatGwei(value) {
  if (typeof value !== "number" || Number.isNaN(value)) return "\u2014";
  return `${value.toFixed(1)} gwei`;
}

function formatTime(timestamp) {
  if (!timestamp) return "\u2014";
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return "\u2014";

  return date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

function getSpamColor(value) {
  if (typeof value !== "number" || Number.isNaN(value)) return "text-zinc-400";
  if (value > 0.5) return "text-red-400";
  if (value >= 0.2) return "text-yellow-400";
  return "text-green-400";
}

function getSpamLabel(value) {
  if (typeof value !== "number" || Number.isNaN(value)) return "NO SIGNAL";
  if (value > 0.5) return "HIGH SPAM PRESSURE";
  if (value >= 0.2) return "MEDIUM PRESSURE";
  return "LOW PRESSURE";
}

function shortHash(hash) {
  if (!hash || typeof hash !== "string") return "\u2014";
  if (hash.length <= 12) return hash;
  return `${hash.slice(0, 5)}...${hash.slice(-4)}`;
}

function blockUrl(blockNumber) {
  return `${EXPLORER_BASE_URL}/block/${blockNumber}`;
}

function txUrl(hash) {
  return `${EXPLORER_BASE_URL}/tx/${hash}`;
}

function addressUrl(address) {
  return `${EXPLORER_BASE_URL}/address/${address}`;
}

function normalizeBlock(block) {
  if (!block || typeof block !== "object") return null;
  const blockNumber = Number(block.block_number);
  if (!Number.isFinite(blockNumber)) return null;

  return {
    ...block,
    block_number: blockNumber,
    spam_ratio: Number(block.spam_ratio),
    spam_gas: Number(block.spam_gas),
    total_gas: Number(block.total_gas),
    spam_tx_count: Number(block.spam_tx_count),
    total_txs: Number(block.total_txs),
    suggested_floor_gwei: Number(
      block.suggested_floor_gwei ??
        (typeof block.suggested_floor === "number" ? block.suggested_floor / 1e9 : block.suggested_floor),
    ),
    analysis_time_ms: Number(block.analysis_time_ms),
    oracle_tx: block.oracle_tx ?? block.oracle_tx_hash ?? null,
  };
}

function mergeBlocks(currentBlocks, incomingBlocks, limit) {
  const byBlockNumber = new Map();

  currentBlocks.forEach((block) => {
    byBlockNumber.set(block.block_number, block);
  });

  incomingBlocks.forEach((block) => {
    byBlockNumber.set(block.block_number, block);
  });

  return Array.from(byBlockNumber.values())
    .sort((a, b) => a.block_number - b.block_number)
    .slice(-limit);
}

function loadStoredBlocks() {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];

    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.map(normalizeBlock).filter(Boolean);
  } catch {
    return [];
  }
}

function MetricCard({ label, value, helper, valueClass = "text-zinc-50", children }) {
  return (
    <section className="border-2 border-zinc-800 bg-[#13131a] p-4 shadow-[5px_5px_0_#050507]">
      <div className="mb-3 flex items-center justify-between gap-3">
        <p className="text-[11px] font-black uppercase tracking-[0.16em] text-zinc-500">
          {label}
        </p>
        <span className="border border-zinc-800 px-2 py-1 font-mono text-[10px] uppercase text-zinc-500">
          RT
        </span>
      </div>
      {value !== undefined ? (
        <div className={`font-mono text-3xl font-black leading-none md:text-4xl ${valueClass}`}>
          {value}
        </div>
      ) : null}
      {helper ? (
        <p className="mt-3 text-xs uppercase tracking-[0.08em] text-zinc-500">{helper}</p>
      ) : null}
      {children}
    </section>
  );
}

function EmptyState({ children }) {
  return (
    <div className="flex min-h-[260px] items-center justify-center border border-dashed border-zinc-800 bg-black/20 p-6 text-center">
      <p className="max-w-lg font-mono text-sm uppercase tracking-[0.08em] text-zinc-500">
        {children}
      </p>
    </div>
  );
}

function CustomTooltip({ active, payload }) {
  if (!active || !payload || !payload.length) return null;
  const data = payload[0].payload;

  return (
    <div className="border-2 border-zinc-700 bg-[#0a0a0f] p-3 shadow-[4px_4px_0_#ef4444]">
      <p className="font-mono text-xs uppercase text-zinc-400">Block {data.block}</p>
      <p className="mt-2 font-mono text-lg font-black text-red-400">
        {data.spamPercent.toFixed(1)}%
      </p>
      <p className="mt-1 font-mono text-xs text-zinc-300">
        Spam TXs: {data.spamTxCount} / {data.totalTxs}
      </p>
      <p className="font-mono text-xs text-zinc-300">
        Floor: {formatGwei(data.gasFloor)}
      </p>
    </div>
  );
}

export default function App() {
  const [connected, setConnected] = useState(false);
  const [blocks, setBlocks] = useState(() => loadStoredBlocks());
  const [latestBlock, setLatestBlock] = useState(null);
  const [highSpamBlocks, setHighSpamBlocks] = useState([]);
  const [oracleTxs, setOracleTxs] = useState([]);

  useEffect(() => {
    let socket;
    let reconnectTimer;
    let shouldReconnect = true;

    function applyIncomingBlocks(rawBlocks) {
      const incomingBlocks = rawBlocks.map(normalizeBlock).filter(Boolean);
      if (!incomingBlocks.length) return;

      setBlocks((currentBlocks) => {
        return mergeBlocks(currentBlocks, incomingBlocks, 30);
      });

      setHighSpamBlocks((currentHighSpamBlocks) =>
        mergeBlocks(
          currentHighSpamBlocks,
          incomingBlocks.filter((block) => block.spam_ratio > 0.5),
          10,
        ).reverse(),
      );

      setOracleTxs((currentOracleTxs) => {
        const incomingTxs = [...incomingBlocks]
          .sort((a, b) => b.block_number - a.block_number)
          .map((block) => block.oracle_tx)
          .filter((hash) => typeof hash === "string" && hash.length > 0);

        const deduped = [];
        [...incomingTxs, ...currentOracleTxs].forEach((hash) => {
          if (!deduped.includes(hash)) deduped.push(hash);
        });

        return deduped.slice(0, 5);
      });
    }

    function connect() {
      socket = new WebSocket(WS_URL);

      socket.onopen = () => {
        setConnected(true);
      };

      socket.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);
          if (message.type === "history" && Array.isArray(message.blocks)) {
            applyIncomingBlocks(message.blocks);
          }
          if (message.type === "block" && message.data) {
            applyIncomingBlocks([message.data]);
          }
        } catch {
          // Malformed messages are ignored so the live stream keeps running.
        }
      };

      socket.onerror = () => {
        setConnected(false);
        socket.close();
      };

      socket.onclose = () => {
        setConnected(false);
        if (shouldReconnect) {
          reconnectTimer = window.setTimeout(connect, 3000);
        }
      };
    }

    connect();

    return () => {
      shouldReconnect = false;
      window.clearTimeout(reconnectTimer);
      if (socket) socket.close();
    };
  }, []);

  useEffect(() => {
    setLatestBlock(blocks[blocks.length - 1] || null);
  }, [blocks]);

  useEffect(() => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(blocks));

    setHighSpamBlocks(
      [...blocks]
        .filter((block) => block.spam_ratio > 0.5)
        .slice(-10)
        .reverse(),
    );

    const deduped = [];
    [...blocks]
      .sort((a, b) => b.block_number - a.block_number)
      .map((block) => block.oracle_tx)
      .filter((hash) => typeof hash === "string" && hash.length > 0)
      .forEach((hash) => {
        if (!deduped.includes(hash)) deduped.push(hash);
      });
    setOracleTxs(deduped.slice(0, 5));
  }, [blocks]);

  const chartData = blocks.map((block) => ({
    block: block.block_number,
    spamPercent: block.spam_ratio * 100,
    spamTxCount: block.spam_tx_count,
    totalTxs: block.total_txs,
    gasFloor: block.suggested_floor_gwei,
  }));

  const latestBlockNumber = latestBlock ? String(latestBlock.block_number) : "\u2014";
  const latestBlockLink = latestBlock ? blockUrl(latestBlock.block_number) : null;

  return (
    <main className="min-h-screen bg-[#0a0a0f] text-zinc-100">
      <header className="sticky top-0 z-20 border-b-2 border-zinc-800 bg-[#0a0a0f]/95 backdrop-blur-none">
        <div className="mx-auto grid max-w-7xl grid-cols-1 items-center gap-4 px-4 py-4 md:grid-cols-[1fr_auto_1fr] md:px-6">
          <div>
            <h1 className="font-mono text-2xl font-black uppercase leading-none text-zinc-50">
              SpamGuard
            </h1>
            <p className="mt-1 text-xs font-bold uppercase tracking-[0.18em] text-zinc-500">
              Monad Spam MEV Monitor
            </p>
          </div>

          <div className="flex items-center gap-3 border-2 border-zinc-800 bg-[#13131a] px-4 py-2 font-mono text-sm font-black uppercase">
            <span
              className={`h-3 w-3 ${connected ? "animate-pulse bg-green-400" : "bg-red-500"}`}
            />
            {connected ? "LIVE" : "DISCONNECTED"}
          </div>

          <div className="flex flex-wrap items-center gap-2 md:justify-end">
            <span className="border border-zinc-800 px-2 py-1 font-mono text-[10px] font-bold uppercase tracking-[0.16em] text-zinc-500">
              REALTIME
            </span>
            <span className="border border-zinc-800 px-2 py-1 font-mono text-[10px] font-bold uppercase tracking-[0.16em] text-zinc-500">
              MONAD TESTNET
            </span>
            <a
              href={PAPER_URL}
              target="_blank"
              rel="noreferrer"
              className="border border-zinc-800 px-2 py-1 text-[10px] font-bold uppercase tracking-[0.12em] text-zinc-400 hover:border-red-500 hover:text-red-400"
            >
              Powered by Category Labs Model
            </a>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-7xl px-4 py-5 md:px-6">
        <div className="mb-4 flex flex-wrap gap-2">
          <span className="border border-zinc-800 bg-[#13131a] px-2 py-1 font-mono text-[10px] font-black uppercase tracking-[0.16em] text-green-400">
            MODEL ONLINE
          </span>
          <span className="border border-zinc-800 bg-[#13131a] px-2 py-1 font-mono text-[10px] font-black uppercase tracking-[0.16em] text-zinc-500">
            WS {WS_URL}
          </span>
          <span className="border border-zinc-800 bg-[#13131a] px-2 py-1 font-mono text-[10px] font-black uppercase tracking-[0.16em] text-zinc-500">
            ORACLE SYNC
          </span>
        </div>

        <section className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          <MetricCard
            label="Current Spam Ratio"
            value={latestBlock ? formatPercent(latestBlock.spam_ratio) : "\u2014"}
            valueClass={getSpamColor(latestBlock?.spam_ratio)}
          >
            <p
              className={`mt-3 inline-block border px-2 py-1 font-mono text-[10px] font-black uppercase tracking-[0.14em] ${
                latestBlock?.spam_ratio > 0.5
                  ? "border-red-500/60 bg-red-500/10 text-red-400"
                  : latestBlock?.spam_ratio >= 0.2
                    ? "border-yellow-500/60 bg-yellow-500/10 text-yellow-400"
                    : "border-green-500/60 bg-green-500/10 text-green-400"
              }`}
            >
              {getSpamLabel(latestBlock?.spam_ratio)}
            </p>
          </MetricCard>

          <MetricCard
            label="Spam TXs / Total TXs"
            value={
              latestBlock
                ? `${latestBlock.spam_tx_count} / ${latestBlock.total_txs}`
                : "\u2014"
            }
            helper="Current block transaction classification"
          />

          <MetricCard
            label="Suggested Gas Floor"
            value={latestBlock ? formatGwei(latestBlock.suggested_floor_gwei) : "\u2014"}
            helper="Category Labs equilibrium model"
            valueClass="text-yellow-300"
          />

          <MetricCard label="Latest Block" helper="Open in Monad Explorer" valueClass="text-zinc-50">
            {latestBlockLink ? (
              <a
                href={latestBlockLink}
                target="_blank"
                rel="noreferrer"
                className="font-mono text-3xl font-black leading-none text-zinc-50 underline decoration-red-500 underline-offset-4 hover:text-red-400 md:text-4xl"
              >
                {latestBlockNumber}
              </a>
            ) : (
              <div className="font-mono text-3xl font-black leading-none text-zinc-50 md:text-4xl">
                {latestBlockNumber}
              </div>
            )}
          </MetricCard>
        </section>

        <section className="mt-5 border-2 border-zinc-800 bg-[#13131a] p-4 shadow-[5px_5px_0_#050507]">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-[11px] font-black uppercase tracking-[0.16em] text-zinc-500">
                Spam Ratio per Block (last 30)
              </p>
              <h2 className="mt-1 font-mono text-xl font-black uppercase text-zinc-50">
                Live Block Pressure
              </h2>
            </div>
            <span className="border border-zinc-800 px-2 py-1 font-mono text-[10px] font-black uppercase tracking-[0.16em] text-red-400">
              30 BLOCK WINDOW
            </span>
          </div>

          {chartData.length ? (
            <div className="h-[360px] w-full">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData} margin={{ top: 16, right: 22, left: 0, bottom: 8 }}>
                  <CartesianGrid stroke="#27272a" strokeDasharray="2 6" />
                  <XAxis
                    dataKey="block"
                    tick={{ fill: "#a1a1aa", fontSize: 11, fontFamily: "monospace" }}
                    tickFormatter={(value) => String(value)}
                    stroke="#3f3f46"
                    minTickGap={18}
                  />
                  <YAxis
                    domain={[0, 100]}
                    tick={{ fill: "#a1a1aa", fontSize: 11, fontFamily: "monospace" }}
                    tickFormatter={(value) => `${value}%`}
                    stroke="#3f3f46"
                    width={44}
                  />
                  <Tooltip content={<CustomTooltip />} />
                  <ReferenceLine
                    y={15}
                    stroke="#71717a"
                    strokeDasharray="5 5"
                    label={{
                      value: "Paper target threshold",
                      fill: "#a1a1aa",
                      fontSize: 11,
                      position: "insideTopLeft",
                    }}
                  />
                  <ReferenceLine
                    y={50}
                    stroke="#eab308"
                    strokeDasharray="5 5"
                    label={{
                      value: "High spam alert",
                      fill: "#eab308",
                      fontSize: 11,
                      position: "insideTopRight",
                    }}
                  />
                  <Line
                    type="monotone"
                    dataKey="spamPercent"
                    stroke="#ef4444"
                    strokeWidth={3}
                    dot={{ r: 3, fill: "#0a0a0f", stroke: "#ef4444", strokeWidth: 2 }}
                    activeDot={{ r: 5, fill: "#ef4444", stroke: "#0a0a0f", strokeWidth: 2 }}
                    isAnimationActive
                    animationDuration={500}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <EmptyState>Waiting for live block data from {WS_URL}</EmptyState>
          )}
        </section>

        <section className="mt-5 grid grid-cols-1 gap-5 lg:grid-cols-[1.45fr_1fr]">
          <div className="border-2 border-zinc-800 bg-[#13131a] p-4 shadow-[5px_5px_0_#050507]">
            <div className="mb-4 flex items-center justify-between gap-3">
              <h2 className="font-mono text-lg font-black uppercase text-zinc-50">
                Recent High-Spam Blocks
              </h2>
              <span className="border border-red-500/50 bg-red-500/10 px-2 py-1 font-mono text-[10px] font-black uppercase tracking-[0.14em] text-red-400">
                ALERT FEED
              </span>
            </div>

            {highSpamBlocks.length ? (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[660px] border-collapse font-mono text-sm">
                  <thead>
                    <tr className="border-b-2 border-zinc-800 text-left text-[10px] uppercase tracking-[0.14em] text-zinc-500">
                      <th className="py-3 pr-4">Block #</th>
                      <th className="py-3 pr-4">Spam %</th>
                      <th className="py-3 pr-4">Spam TXs</th>
                      <th className="py-3 pr-4">Gas Floor</th>
                      <th className="py-3">Time</th>
                    </tr>
                  </thead>
                  <tbody>
                    {highSpamBlocks.map((block) => (
                      <tr
                        key={block.block_number}
                        className="border-b border-zinc-800/80 text-zinc-300 hover:bg-red-500/10"
                      >
                        <td className="py-3 pr-4">
                          <a
                            href={blockUrl(block.block_number)}
                            target="_blank"
                            rel="noreferrer"
                            className="font-black text-zinc-50 underline decoration-zinc-700 underline-offset-4 hover:text-red-400"
                          >
                            {block.block_number}
                          </a>
                        </td>
                        <td className={`py-3 pr-4 font-black ${getSpamColor(block.spam_ratio)}`}>
                          {formatPercent(block.spam_ratio)}
                        </td>
                        <td className="py-3 pr-4">
                          {block.spam_tx_count} / {block.total_txs}
                        </td>
                        <td className="py-3 pr-4 text-yellow-300">
                          {formatGwei(block.suggested_floor_gwei)}
                        </td>
                        <td className="py-3 text-zinc-500">{formatTime(block.timestamp)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="border border-dashed border-zinc-800 bg-black/20 p-8 text-center font-mono text-sm uppercase tracking-[0.08em] text-green-400">
                No high-spam blocks detected recently {"\u2713"}
              </div>
            )}
          </div>

          <aside className="border-2 border-zinc-800 bg-[#13131a] p-4 shadow-[5px_5px_0_#050507]">
            <div className="mb-4 flex items-center justify-between gap-3">
              <h2 className="font-mono text-lg font-black uppercase text-zinc-50">
                SpamOracle - Testnet
              </h2>
              <span className="border border-zinc-800 px-2 py-1 font-mono text-[10px] font-black uppercase tracking-[0.14em] text-zinc-500">
                ONCHAIN
              </span>
            </div>

            <a
              href={addressUrl(ORACLE_ADDRESS)}
              target="_blank"
              rel="noreferrer"
              className="block break-all border border-zinc-800 bg-black/20 p-3 font-mono text-sm text-zinc-200 hover:border-red-500 hover:text-red-400"
            >
              {ORACLE_ADDRESS}
            </a>

            <a
              href={addressUrl(ORACLE_ADDRESS)}
              target="_blank"
              rel="noreferrer"
              className="mt-4 inline-flex border-2 border-zinc-700 bg-zinc-100 px-4 py-2 font-mono text-xs font-black uppercase tracking-[0.14em] text-black hover:border-red-500 hover:bg-red-500 hover:text-white"
            >
              View on Explorer
            </a>

            <p className="mt-4 border-l-2 border-zinc-700 pl-3 text-sm leading-6 text-zinc-400">
              Oracle updates on every block. Any protocol can read
              getRecommendedGasFloor() to dynamically adjust parameters.
            </p>

            <div className="mt-6">
              <h3 className="mb-3 font-mono text-sm font-black uppercase tracking-[0.12em] text-zinc-50">
                Latest Oracle TXs
              </h3>

              {oracleTxs.length ? (
                <div className="space-y-2">
                  {oracleTxs.map((hash) => (
                    <a
                      key={hash}
                      href={txUrl(hash)}
                      target="_blank"
                      rel="noreferrer"
                      className="block border border-zinc-800 bg-black/20 px-3 py-2 font-mono text-sm text-zinc-300 hover:border-red-500 hover:bg-red-500/10 hover:text-red-400"
                    >
                      {shortHash(hash)}
                    </a>
                  ))}
                </div>
              ) : (
                <div className="border border-dashed border-zinc-800 bg-black/20 p-5 font-mono text-sm uppercase tracking-[0.08em] text-zinc-500">
                  Waiting for oracle updates
                </div>
              )}
            </div>
          </aside>
        </section>
      </div>

      <footer className="border-t-2 border-zinc-900 px-4 py-6 md:px-6">
        <div className="mx-auto max-w-7xl text-xs leading-6 text-zinc-600">
          SpamGuard implements the mitigation framework proposed in:{" "}
          <a
            href={PAPER_URL}
            target="_blank"
            rel="noreferrer"
            className="text-zinc-400 underline decoration-zinc-700 underline-offset-4 hover:text-red-400"
          >
            Blockspace Under Pressure: An Analysis of Spam MEV on High-Throughput
            Blockchains {"\u2014"} Wang et al., Category Labs, 2026
          </a>
        </div>
      </footer>
    </main>
  );
}
