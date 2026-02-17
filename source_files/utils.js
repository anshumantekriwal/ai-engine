/**
 * Shared utility functions used across the Hyperliquid trading system.
 *
 * Math helpers, sleep, retry logic, and other small reusable functions
 * live here so they are defined once and imported everywhere.
 *
 * @module utils
 */

// ---------------------------------------------------------------------------
// Math / precision helpers
// ---------------------------------------------------------------------------

/**
 * Round a number to specified decimal places.
 * @param {number} value
 * @param {number} [decimals=8]
 * @returns {number}
 */
export function toPrecision(value, decimals = 8) {
  const factor = Math.pow(10, decimals);
  return Math.round(value * factor) / factor;
}

/**
 * Compare two floats within a tolerance.
 * @param {number} a
 * @param {number} b
 * @param {number} [tolerance=0.0001]
 * @returns {boolean}
 */
export function compareFloats(a, b, tolerance = 0.0001) {
  return Math.abs(a - b) < tolerance;
}

/**
 * Divide two numbers safely, returning `fallback` when the denominator is
 * zero or non-finite.
 * @param {number} numerator
 * @param {number} denominator
 * @param {number} [fallback=0]
 * @returns {number}
 */
export function safeDivide(numerator, denominator, fallback = 0) {
  if (denominator === 0 || !isFinite(denominator)) return fallback;
  const result = numerator / denominator;
  return isFinite(result) ? result : fallback;
}

/**
 * Coerce a DB/API value to a finite number, returning `fallback` on failure.
 * @param {any} value
 * @param {number} [fallback=0]
 * @returns {number}
 */
export function toFiniteNumber(value, fallback = 0) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : fallback;
}

// ---------------------------------------------------------------------------
// Async helpers
// ---------------------------------------------------------------------------

/**
 * Promise-based sleep.
 * @param {number} ms - Milliseconds to sleep
 * @returns {Promise<void>}
 */
export function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Retry a function with exponential backoff on 429 (rate limit) errors.
 * @param {Function} fn - Async function to retry
 * @param {number} [maxRetries=3]
 * @param {number} [baseDelay=1000] - Base delay in ms
 * @returns {Promise<any>}
 */
export async function retryWithBackoff(fn, maxRetries = 3, baseDelay = 1000) {
  let lastError = null;
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      return await fn();
    } catch (err) {
      lastError = err;
      const msg = err.toString();
      if (msg.includes('429') || msg.includes('Too Many Requests')) {
        if (attempt < maxRetries) {
          const delay = baseDelay * Math.pow(2, attempt);
          console.warn(
            `Rate limited (429), retrying in ${delay}ms (attempt ${attempt + 1}/${maxRetries})`
          );
          await sleep(delay);
          continue;
        }
      }
      throw err;
    }
  }
  throw lastError;
}
