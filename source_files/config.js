/**
 * Centralized configuration constants for the Hyperliquid trading system.
 * All URLs, default values, and magic numbers should be defined here.
 *
 * @module config
 */

// ---------------------------------------------------------------------------
// API endpoints
// ---------------------------------------------------------------------------

export const HYPERLIQUID_INFO_URL = "https://api.hyperliquid.xyz/info";
export const HYPERLIQUID_WS_URL = "wss://api.hyperliquid.xyz/ws";

// ---------------------------------------------------------------------------
// Trading defaults
// ---------------------------------------------------------------------------

/** Default slippage (bps) applied to market orders */
export const DEFAULT_SLIPPAGE_BPS = 300;

/** Default maximum leverage for agents */
export const DEFAULT_MAX_LEVERAGE = 50;

/** Default daily loss limit (USD) */
export const DEFAULT_DAILY_LOSS_LIMIT = 1000;

// ---------------------------------------------------------------------------
// WebSocket reconnection
// ---------------------------------------------------------------------------

/** Default reconnect base delay for WebSocket (ms) */
export const WS_RECONNECT_BASE_MS = 5000;

/** Default max reconnect delay for WebSocket (ms) */
export const WS_RECONNECT_MAX_MS = 60000;

/** Default max consecutive reconnect attempts */
export const WS_MAX_RECONNECT_ATTEMPTS = 50;

// ---------------------------------------------------------------------------
// File storage
// ---------------------------------------------------------------------------

/** Maximum closed position history entries kept per agent */
export const MAX_HISTORY_ENTRIES = 6000;

/** Maximum trade log entries kept per agent */
export const MAX_TRADE_ENTRIES = 8000;

// ---------------------------------------------------------------------------
// Monitoring intervals (ms)
// ---------------------------------------------------------------------------

/** Technical indicator evaluation interval */
export const TECHNICAL_EVAL_INTERVAL_MS = 10_000;

/** Heartbeat persist interval to Supabase */
export const HEARTBEAT_PERSIST_INTERVAL_MS = 60_000;

/** Position sync interval */
export const POSITION_SYNC_INTERVAL_MS = 60_000;

/** Metrics recording interval */
export const METRICS_INTERVAL_MS = 5 * 60_000;

/** Fee rate refresh interval */
export const FEE_REFRESH_INTERVAL_MS = 60 * 60_000;

/** Leverage sync TTL (skip redundant leverage resets within this window) */
export const DEFAULT_LEVERAGE_SYNC_TTL_MS = 30_000;

/** Metadata cache TTL for orderExecutor */
export const META_CACHE_TTL_MS = 60_000;

/** Clearinghouse state cache TTL (ms) — short-lived to avoid stale balance data */
export const CLEARINGHOUSE_CACHE_TTL_MS = 3_000;

// ---------------------------------------------------------------------------
// Technical trigger evaluation
// ---------------------------------------------------------------------------

/** Per-trigger rate limit: minimum ms between evaluations of the same trigger */
export const TECHNICAL_TRIGGER_RATE_LIMIT_MS = 60_000;

/** Multiplier applied to indicator period to compute candle lookback window */
export const CANDLE_LOOKBACK_MULTIPLIER = 2;

/** Minimum candles required for any indicator computation */
export const MIN_CANDLES_REQUIRED = 20;

/**
 * Map candle interval strings to milliseconds.
 * Used to compute dynamic lookback windows.
 */
export const INTERVAL_MS_MAP = {
  '1m':  60_000,
  '3m':  3 * 60_000,
  '5m':  5 * 60_000,
  '15m': 15 * 60_000,
  '30m': 30 * 60_000,
  '1h':  60 * 60_000,
  '2h':  2 * 60 * 60_000,
  '4h':  4 * 60 * 60_000,
  '8h':  8 * 60 * 60_000,
  '12h': 12 * 60 * 60_000,
  '1d':  24 * 60 * 60_000,
  '3d':  3 * 24 * 60 * 60_000,
  '1w':  7 * 24 * 60 * 60_000,
  '1M':  30 * 24 * 60 * 60_000,
};
