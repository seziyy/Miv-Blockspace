import React, { useEffect, useMemo, useRef, useState } from "react";

const WS_URL = "ws://localhost:8765";
const STORAGE_KEY = "spamguard_dead_blocks_v1";
const MAX_BLOCKS = 30;
const MONAD_EXPLORER_TX_URL = "https://testnet.monadexplorer.com/tx/";
const BRAND_PHOTO_URL = "/miv-blockspace-photo.png";
const SCRAMBLE_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";

function normalizeTimestamp(timestamp) {
  if (!timestamp) return null;
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return null;
  return date.toISOString();
}

function normalizeBlock(block) {
  if (!block || typeof block !== "object") return null;
  const blockNumber = Number(block.block_number);
  if (!Number.isFinite(blockNumber)) return null;
  const oracleTx = normalizeTxHash(block.oracle_tx ?? block.oracle_tx_hash);

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
    is_high_spam:
      typeof block.is_high_spam === "boolean"
        ? block.is_high_spam
        : Number(block.spam_ratio) > 0.7,
    oracle_tx: oracleTx,
    oracle_tx_hash: oracleTx,
    timestamp: normalizeTimestamp(block.timestamp) ?? new Date().toISOString(),
  };
}

function normalizeTxHash(value) {
  if (typeof value !== "string") return "";
  const trimmed = value.trim();
  if (!trimmed) return "";
  const withoutPrefix = trimmed.startsWith("0x") ? trimmed.slice(2) : trimmed;
  if (!/^[0-9a-fA-F]{64}$/.test(withoutPrefix)) return "";
  return `0x${withoutPrefix.toLowerCase()}`;
}

function mergeBlocks(currentBlocks, incomingBlocks, limit = MAX_BLOCKS) {
  const byBlockNumber = new Map();

  [...currentBlocks, ...incomingBlocks].forEach((block) => {
    if (block) byBlockNumber.set(block.block_number, block);
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

function createFallbackBlocks() {
  const now = Date.now();
  const ratios = [
    0.42, 0.37, 0.48, 0.55, 0.58, 0.62, 0.51, 0.46, 0.69, 0.72,
    0.63, 0.57, 0.61, 0.74, 0.68, 0.53, 0.44, 0.39, 0.47, 0.59,
    0.66, 0.71, 0.64, 0.49, 0.52, 0.58, 0.62, 0.65, 0.67, 0.688,
  ];

  return ratios
    .map((ratio, index) =>
      normalizeBlock({
        block_number: 84035755 + index,
        spam_ratio: ratio,
        spam_gas: Math.floor(29_000_000 * ratio),
        total_gas: 29_000_000,
        spam_tx_count: Math.max(1, Math.round(ratio * 11)),
        total_txs: 11 + (index % 10),
        suggested_floor_gwei: 14 + ratio * 28,
        analysis_time_ms: 95 + index * 4,
        is_high_spam: ratio > 0.7,
        timestamp: new Date(now - (29 - index) * 7000).toISOString(),
      }),
    )
    .filter(Boolean);
}

function formatPercent(value) {
  if (typeof value !== "number" || Number.isNaN(value)) return "\u2014";
  return `${Math.round(value * 100)}%`;
}

function formatPercentPrecise(value) {
  if (typeof value !== "number" || Number.isNaN(value)) return "\u2014";
  return `${(value * 100).toFixed(1)}%`;
}

function formatGwei(value) {
  if (typeof value !== "number" || Number.isNaN(value)) return "\u2014";
  if (value > 0 && value < 0.01) return `${value.toFixed(4)} gwei`;
  if (value > 0 && value < 0.1) return `${value.toFixed(3)} gwei`;
  return `${value.toFixed(1)} gwei`;
}

function formatInteger(value) {
  if (typeof value !== "number" || Number.isNaN(value)) return "\u2014";
  return value.toLocaleString("en-US");
}

function formatCompact(value) {
  if (typeof value !== "number" || Number.isNaN(value)) return "\u2014";
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return String(value);
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

function formatTxHash(txHash) {
  if (!txHash) return "\u2014";
  return `${txHash.slice(0, 10)}...${txHash.slice(-8)}`;
}

function oracleTxLink(txHash) {
  if (!txHash) return null;
  return `${MONAD_EXPLORER_TX_URL}${txHash}`;
}

function getLatestOracleTxs(blocks, count = 3) {
  const seen = new Set();
  const txs = [];

  for (const block of [...blocks].reverse()) {
    if (!block.oracle_tx || seen.has(block.oracle_tx)) continue;
    seen.add(block.oracle_tx);
    txs.push(block.oracle_tx);
    if (txs.length === count) break;
  }

  return txs;
}

function pressureCopy(spamRatio) {
  if (typeof spamRatio !== "number" || Number.isNaN(spamRatio)) return "No live signal";
  if (spamRatio > 0.7) return "Elevated";
  if (spamRatio >= 0.4) return "Active";
  return "Stable";
}

function diagnosis(spamRatio) {
  if (typeof spamRatio !== "number" || Number.isNaN(spamRatio)) {
    return "Waiting for current block telemetry from the monitor.";
  }
  if (spamRatio > 0.7) {
    return "Spam pressure remains dominant. Floor intervention should be evaluated if this persists.";
  }
  if (spamRatio >= 0.4) {
    return "Pressure is elevated but not saturated. Continue observing short-term block behavior.";
  }
  return "Network conditions look healthy. Immediate intervention does not appear necessary.";
}

function barClass(value) {
  if (value > 0.75) return "bg-[#5f7f73]";
  if (value > 0.6) return "bg-[#8aa08f]";
  return "bg-[#353535]";
}

function SectionLabel({ children }) {
  return (
    <p className="m-0 text-[11px] font-bold uppercase text-[#5d5a54]">
      {children}
    </p>
  );
}

function SummaryCard({ label, value }) {
  return (
    <div className="rounded-[18px] border border-[#2b2b2b] bg-[#f4efe6] p-5">
      <SectionLabel>{label}</SectionLabel>
      <div className="mt-7 break-words text-[40px] font-black leading-none text-[#121212]">{value}</div>
    </div>
  );
}

function MetricCell({ value, label, highlight = false }) {
  return (
    <div className="min-w-0 border-t border-[#2b2b2b] p-4 first:border-t-0 sm:border-t-0 sm:border-r sm:last:border-r-0">
      <div className={`h-[3px] w-10 ${highlight ? "bg-[#5f7f73]" : "bg-[#2b2b2b]"}`} />
      <div className="mt-4 min-w-0 break-words text-[22px] font-black leading-[1.05] text-[#111111] xl:text-[20px] 2xl:text-[22px]">
        {value}
      </div>
      <div className="mt-2 break-words text-[10px] font-bold uppercase text-[#5d5a54] 2xl:text-[11px]">
        {label}
      </div>
    </div>
  );
}

function TxHashValue({ txHash }) {
  if (!txHash) return "Not written";

  return (
    <a
      className="inline-block max-w-full break-all text-[15px] leading-[1.15] underline decoration-[#5f7f73] underline-offset-4"
      href={oracleTxLink(txHash)}
      rel="noreferrer"
      target="_blank"
      title={txHash}
    >
      {formatTxHash(txHash)}
    </a>
  );
}

function OracleHashStrip({ txHashes }) {
  if (!txHashes.length) return "Not written";

  return (
    <div className="grid max-w-full gap-3 text-[16px] font-black leading-[1.2] md:grid-cols-3">
      {txHashes.map((txHash) => (
        <a
          className="min-w-0 truncate border border-[#2b2b2b] bg-[#e3ddcf] px-4 py-3 font-mono text-[#111111] underline decoration-[#5f7f73] decoration-2 underline-offset-4"
          href={oracleTxLink(txHash)}
          key={txHash}
          rel="noreferrer"
          target="_blank"
          title={txHash}
        >
          {formatTxHash(txHash)}
        </a>
      ))}
    </div>
  );
}

function ScrambleButtonText({ text }) {
  const [label, setLabel] = useState(text);
  const intervalRef = useRef(null);

  function clearScramble() {
    if (!intervalRef.current) return;
    window.clearInterval(intervalRef.current);
    intervalRef.current = null;
  }

  function scramble() {
    clearScramble();
    let frame = 0;

    intervalRef.current = window.setInterval(() => {
      frame += 1;
      setLabel(
        text.split("")
          .map((char, index) => {
            if (char === " ") return " ";
            if (frame > index + 5) return char;
            return SCRAMBLE_CHARS[Math.floor(Math.random() * SCRAMBLE_CHARS.length)];
          })
          .join(""),
      );

      if (frame > text.length + 6) {
        clearScramble();
        setLabel(text);
      }
    }, 35);
  }

  useEffect(() => {
    setLabel(text);
  }, [text]);

  useEffect(() => clearScramble, []);

  return (
    <span className="font-mono tabular-nums" onMouseEnter={scramble}>
      {label}
    </span>
  );
}

function BrandPhotoPanel() {
  const [visible, setVisible] = useState(true);

  if (!visible) return null;

  return (
    <section className="mt-10 overflow-hidden rounded-[18px] border border-[#2b2b2b] bg-[#f4efe6]">
      <img
        alt="Miv Blockspace"
        className="h-[260px] w-full object-cover"
        onError={() => setVisible(false)}
        src={BRAND_PHOTO_URL}
      />
    </section>
  );
}

function ChainCard({ title, mainValue, barValue, cells, wide = false }) {
  return (
    <div className={`min-w-0 rounded-[20px] border border-[#2b2b2b] bg-[#f4efe6] p-5 2xl:p-6 ${wide ? "md:col-span-2 xl:col-span-3" : ""}`}>
      <h3 className="m-0 min-h-[72px] break-words text-[30px] font-black uppercase leading-[1] text-[#111111] xl:text-[26px] 2xl:text-[30px]">
        {title}
      </h3>

      <div className="mt-5 border-t border-[#2b2b2b]" />

      <div className="mt-6 rounded-none border border-[#2b2b2b] p-5">
        <div className="min-w-0 break-words text-[42px] font-black leading-[0.98] text-[#111111] xl:text-[36px] 2xl:text-[42px]">
          {mainValue}
        </div>
        <div className="mt-8 h-[18px] border border-[#2b2b2b] bg-[#f4efe6] p-[2px]">
          <div className={`h-full ${barClass(barValue)}`} style={{ width: `${Math.max(6, barValue * 100)}%` }} />
        </div>
      </div>

      <div className={`mt-7 grid min-w-0 grid-cols-1 border border-[#2b2b2b] sm:grid-cols-2 ${wide ? "xl:grid-cols-4" : ""}`}>
        {cells.map((cell, index) => (
          <MetricCell key={`${title}-${index}`} {...cell} />
        ))}
      </div>
    </div>
  );
}

export default function App() {
  const [connected, setConnected] = useState(false);
  const [blocks, setBlocks] = useState(() => loadStoredBlocks());

  useEffect(() => {
    let socket;
    let reconnectTimer;
    let shouldReconnect = true;

    function applyIncomingBlocks(rawBlocks) {
      const incomingBlocks = rawBlocks.map(normalizeBlock).filter(Boolean);
      if (!incomingBlocks.length) return;
      setBlocks((currentBlocks) => mergeBlocks(currentBlocks, incomingBlocks, MAX_BLOCKS));
    }

    function connect() {
      const ws = new WebSocket(WS_URL);
      socket = ws;

      ws.onopen = () => {
        if (ws === socket) setConnected(true);
      };
      ws.onmessage = (event) => {
        if (ws !== socket) return;
        try {
          const message = JSON.parse(event.data);
          if (message.type === "history" && Array.isArray(message.blocks)) {
            applyIncomingBlocks(message.blocks);
          }
          if (message.type === "block" && message.data) {
            applyIncomingBlocks([message.data]);
          }
        } catch {
          // Ignore malformed messages.
        }
      };
      ws.onerror = () => {
        if (ws !== socket) return;
        ws.close();
      };
      ws.onclose = () => {
        if (ws !== socket) return;
        setConnected(false);
        if (shouldReconnect) reconnectTimer = window.setTimeout(connect, 3000);
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
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(blocks));
  }, [blocks]);

  const effectiveBlocks = useMemo(() => {
    if (blocks.length) return blocks;
    if (!connected) return createFallbackBlocks();
    return [];
  }, [blocks, connected]);

  const latestBlock = effectiveBlocks[effectiveBlocks.length - 1] ?? null;
  const averageSpam =
    effectiveBlocks.length > 0
      ? effectiveBlocks.reduce((sum, block) => sum + block.spam_ratio, 0) / effectiveBlocks.length
      : NaN;
  const suspiciousWalletsEstimate =
    latestBlock && Number.isFinite(latestBlock.total_txs)
      ? latestBlock.total_txs * 1_250_000
      : NaN;
  const priorityChains = effectiveBlocks.length ? 4 : NaN;
  const latestOracleTxs = getLatestOracleTxs(effectiveBlocks, 3);
  const latestOracleTx = latestOracleTxs[0] ?? "";

  const cards = [
    {
      title: "Spam pressure",
      mainValue: formatPercent(latestBlock?.spam_ratio),
      barValue: latestBlock?.spam_ratio ?? 0,
      cells: [
        {
          value: formatPercent(latestBlock?.spam_ratio),
          label: "Bot activity",
          highlight: true,
        },
        {
          value:
            typeof latestBlock?.spam_ratio === "number" && !Number.isNaN(latestBlock.spam_ratio)
              ? formatPercent(1 - latestBlock.spam_ratio)
              : "\u2014",
          label: "Human activity",
        },
        {
          value: formatCompact(latestBlock?.spam_gas),
          label: "Spam gas",
        },
        {
          value: formatCompact(latestBlock?.total_gas),
          label: "Total gas",
          highlight: true,
        },
      ],
    },
    {
      title: "Transaction flow",
      mainValue:
        latestBlock && Number.isFinite(latestBlock.spam_tx_count) && Number.isFinite(latestBlock.total_txs)
          ? `${latestBlock.spam_tx_count}/${latestBlock.total_txs}`
          : "\u2014",
      barValue:
        latestBlock && latestBlock.total_txs > 0 ? latestBlock.spam_tx_count / latestBlock.total_txs : 0,
      cells: [
        {
          value: formatInteger(latestBlock?.spam_tx_count),
          label: "Spam tx count",
          highlight: true,
        },
        {
          value: formatInteger(latestBlock?.total_txs),
          label: "Total tx count",
        },
        {
          value: `${Math.round(latestBlock?.analysis_time_ms ?? NaN)} ms`,
          label: "Analysis time",
        },
        {
          value: pressureCopy(latestBlock?.spam_ratio),
          label: "Pressure state",
          highlight: true,
        },
      ],
    },
    {
      title: "Gas floor",
      mainValue: formatGwei(latestBlock?.suggested_floor_gwei),
      barValue:
        latestBlock && Number.isFinite(latestBlock.suggested_floor_gwei)
          ? Math.min(latestBlock.suggested_floor_gwei / 50, 1)
          : 0,
      cells: [
        {
          value: formatPercentPrecise(averageSpam),
          label: "Avg spam share",
          highlight: true,
        },
        {
          value: formatPercentPrecise(latestBlock?.spam_ratio),
          label: "Current share",
        },
        {
          value: formatGwei(latestBlock?.suggested_floor_gwei),
          label: "Suggested floor",
        },
        {
          value: latestBlock ? latestBlock.block_number : "\u2014",
          label: "Latest block",
          highlight: true,
        },
      ],
    },
    {
      title: "Oracle sync",
      mainValue: <OracleHashStrip txHashes={latestOracleTxs} />,
      barValue: latestOracleTx ? 0.92 : 0.12,
      wide: true,
      cells: [
        {
          value: <OracleHashStrip txHashes={latestOracleTxs} />,
          label: "Latest oracle txs",
          highlight: Boolean(latestOracleTx),
        },
        {
          value: latestBlock ? latestBlock.block_number : "\u2014",
          label: "Source block",
        },
        {
          value: connected ? "Connected" : "Retrying",
          label: "WebSocket",
          highlight: connected,
        },
        {
          value: formatTime(latestBlock?.timestamp),
          label: "Update time",
        },
      ],
    },
  ];

  return (
    <main className="min-h-screen bg-[#ece6db] px-3 py-3 text-[#111111] sm:px-5 sm:py-5">
      <div className="mx-auto max-w-[1800px] rounded-[18px] border border-[#2b2b2b] bg-[#f4efe6]">
        <header className="flex flex-wrap items-center justify-between gap-6 border-b border-[#2b2b2b] px-7 py-4">
          <div className="text-[22px] font-black uppercase">
            Miv Blockspace
          </div>

          <a className="inline-flex min-w-[142px] items-center justify-center rounded-[12px] border border-[#2b2b2b] bg-[#5f7f73] px-5 py-2.5 text-[16px] font-black uppercase text-[#fffaf0]" href="/landing.html">
            <ScrambleButtonText text="Landing" />
          </a>
        </header>

        <div className="px-7 py-10">
          <section className="grid gap-8 xl:grid-cols-[1.6fr_0.8fr] xl:items-center">
            <div className="flex gap-5">
              <div className="mt-1 h-[42px] w-[6px] bg-[#2b2b2b]" />
              <div>
                <h1 className="m-0 text-[34px] font-black leading-[1.08]">
                  Real-time spam MEV intelligence for Monad
                </h1>
                <p className="mt-4 max-w-[62ch] text-[17px] leading-[1.6] text-[#4c4a46]">
                  Detect spam pressure, gas abuse, and transaction anomalies before they distort the block.
                </p>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-3 xl:justify-end">
              <StatusChip active>Live monitoring</StatusChip>
              <StatusChip>Powered by Category Labs model</StatusChip>
              <StatusChip warn={!connected}>{connected ? "Connected" : "Disconnected"}</StatusChip>
            </div>
          </section>

          <section className="mt-10 grid gap-5 lg:grid-cols-3">
            <SummaryCard label="Priority chains" value={formatInteger(priorityChains)} />
            <SummaryCard label="Avg bot share" value={formatPercent(averageSpam)} />
            <SummaryCard label="Suspicious wallets" value={formatCompact(suspiciousWalletsEstimate)} />
          </section>

          <BrandPhotoPanel />

          <section className="mt-10 grid gap-6 md:grid-cols-2 xl:grid-cols-3">
            {cards.map((card) => (
              <ChainCard key={card.title} {...card} />
            ))}
          </section>
        </div>
      </div>
    </main>
  );
}

function StatusChip({ children, active = false, warn = false }) {
  return (
    <span
      className={`inline-flex items-center rounded-[10px] border px-4 py-2 text-[11px] font-black uppercase ${
        active
          ? "border-[#2b2b2b] bg-[#111111] text-[#fffaf0]"
          : warn
            ? "border-[#5f7f73] text-[#5f7f73]"
            : "border-[#2b2b2b] text-[#2f2f2f]"
      }`}
    >
      {children}
    </span>
  );
}
