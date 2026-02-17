/**
 * Shared HTTP client for the Hyperliquid info API.
 *
 * Every module that needs to call `POST https://api.hyperliquid.xyz/info`
 * should import `hyperliquidInfoRequest` from this file instead of
 * duplicating the fetch/error-handling boilerplate.
 *
 * @module apiClient
 */

import { HYPERLIQUID_INFO_URL } from './config.js';

/**
 * Make a POST request to the Hyperliquid info API.
 *
 * @param {Object} body - JSON body (e.g. `{ type: "allMids" }`)
 * @param {Object} [options={}] - Extra fetch options
 * @param {Object} [options.headers] - Additional headers merged with defaults
 * @returns {Promise<any>} Parsed JSON response
 * @throws {Error} On HTTP errors or network failures
 */
export async function hyperliquidInfoRequest(body, options = {}) {
  const response = await fetch(HYPERLIQUID_INFO_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...options.headers },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(
      `Hyperliquid API error: ${response.status} ${response.statusText} - ${errorText}`
    );
  }

  return response.json();
}
