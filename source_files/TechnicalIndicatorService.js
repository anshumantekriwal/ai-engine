/**
 * TechnicalIndicatorService
 *
 * Encapsulates all technical indicator computations using the
 * `technicalindicators` library.  Lazy-loads the library on first use
 * to avoid paying the import cost when no technical triggers are registered.
 *
 * Supported indicators:
 *   Closes-only : RSI, EMA, SMA, MACD, BollingerBands, ROC
 *   OHLCV       : ATR, ADX, Stochastic, WilliamsR, CCI, OBV
 *
 * Public API:
 *   compute(indicator, candles, params)            -> latest value
 *   computeSeries(indicator, candles, params, depth) -> last `depth` values
 *   computePair(indA, paramsA, indB, paramsB, candles, depth) -> { a, b }
 *
 * @module TechnicalIndicatorService
 */

import { toPrecision } from './utils.js';

let _lib = null;

async function loadLib() {
  if (!_lib) {
    _lib = await import('technicalindicators');
  }
  return _lib;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Normalise a candle-data argument.
 * Accepts either a plain number[] (treated as closes) or an object
 * { closes, highs, lows, opens, volumes }.
 */
function normaliseCandles(candles) {
  if (Array.isArray(candles)) {
    return { closes: candles, highs: null, lows: null, opens: null, volumes: null };
  }
  return candles;
}

/** Apply toPrecision to a scalar or every numeric field of an object. */
function applyPrecision(val, decimals = 6) {
  if (val === null || val === undefined) return null;
  if (typeof val === 'number') return toPrecision(val, decimals);
  if (typeof val === 'object') {
    const out = { ...val };
    for (const k in out) {
      if (typeof out[k] === 'number') out[k] = toPrecision(out[k], decimals);
    }
    return out;
  }
  return val;
}

// ---------------------------------------------------------------------------
// Core calculator — returns the full computed array (no slicing).
// ---------------------------------------------------------------------------

async function calculateFull(indicator, candles, params) {
  const lib = await loadLib();
  const { closes, highs, lows, opens, volumes } = normaliseCandles(candles);

  switch (indicator) {
    // ---- closes-only indicators -------------------------------------------
    case 'RSI':
      return lib.RSI.calculate({ values: closes, period: params.period || 14 });

    case 'EMA':
      return lib.EMA.calculate({ values: closes, period: params.period || 20 });

    case 'SMA':
      return lib.SMA.calculate({ values: closes, period: params.period || 20 });

    case 'MACD':
      return lib.MACD.calculate({
        values: closes,
        fastPeriod: params.fastPeriod || 12,
        slowPeriod: params.slowPeriod || 26,
        signalPeriod: params.signalPeriod || 9,
        SimpleMAOscillator: false,
        SimpleMASignal: false,
      });

    case 'BollingerBands':
      return lib.BollingerBands.calculate({
        values: closes,
        period: params.period || 20,
        stdDev: params.stdDev || 2,
      });

    case 'ROC':
      return lib.ROC.calculate({ values: closes, period: params.period || 12 });

    // ---- OHLCV indicators -------------------------------------------------
    case 'ATR':
      if (!highs || !lows) throw new Error('ATR requires highs and lows');
      return lib.ATR.calculate({
        high: highs, low: lows, close: closes,
        period: params.period || 14,
      });

    case 'ADX':
      if (!highs || !lows) throw new Error('ADX requires highs and lows');
      return lib.ADX.calculate({
        high: highs, low: lows, close: closes,
        period: params.period || 14,
      });

    case 'Stochastic':
      if (!highs || !lows) throw new Error('Stochastic requires highs and lows');
      return lib.Stochastic.calculate({
        high: highs, low: lows, close: closes,
        period: params.period || 14,
        signalPeriod: params.signalPeriod || 3,
      });

    case 'WilliamsR':
      if (!highs || !lows) throw new Error('WilliamsR requires highs and lows');
      return lib.WilliamsR.calculate({
        high: highs, low: lows, close: closes,
        period: params.period || 14,
      });

    case 'CCI':
      if (!highs || !lows) throw new Error('CCI requires highs and lows');
      return lib.CCI.calculate({
        high: highs, low: lows, close: closes,
        period: params.period || 20,
      });

    case 'OBV':
      if (!volumes) throw new Error('OBV requires volumes');
      return lib.OBV.calculate({ close: closes, volume: volumes });

    default:
      throw new Error(`Unknown indicator: ${indicator}`);
  }
}

// ---------------------------------------------------------------------------
// Public class
// ---------------------------------------------------------------------------

class TechnicalIndicatorService {
  /**
   * Compute the latest indicator value.
   *
   * @param {string} indicator
   * @param {number[]|Object} candles - number[] of closes, or { closes, highs, lows, opens, volumes }
   * @param {Object} params
   * @returns {Promise<number|Object|null>}
   */
  async compute(indicator, candles, params = {}) {
    const values = await calculateFull(indicator, candles, params);
    if (!values || values.length === 0) return null;
    return applyPrecision(values[values.length - 1]);
  }

  /**
   * Return the last `depth` indicator values (oldest first).
   * Essential for crossover / state-transition detection.
   *
   * @param {string} indicator
   * @param {number[]|Object} candles
   * @param {Object} params
   * @param {number} [depth=2]
   * @returns {Promise<Array<number|Object|null>>}
   */
  async computeSeries(indicator, candles, params = {}, depth = 2) {
    const values = await calculateFull(indicator, candles, params);
    if (!values || values.length === 0) return [];
    const tail = values.slice(-depth);
    return tail.map(v => applyPrecision(v));
  }

  /**
   * Compute two indicator series from the same candle data and return
   * the last `depth` values from each — the primitive for EMA(9) vs EMA(21)
   * crossover detection.
   *
   * @param {string} indicatorA
   * @param {Object} paramsA
   * @param {string} indicatorB
   * @param {Object} paramsB
   * @param {number[]|Object} candles
   * @param {number} [depth=2]
   * @returns {Promise<{a: Array, b: Array}>}
   */
  async computePair(indicatorA, paramsA, indicatorB, paramsB, candles, depth = 2) {
    const [seriesA, seriesB] = await Promise.all([
      this.computeSeries(indicatorA, candles, paramsA, depth),
      this.computeSeries(indicatorB, candles, paramsB, depth),
    ]);
    return { a: seriesA, b: seriesB };
  }
}

export default TechnicalIndicatorService;
