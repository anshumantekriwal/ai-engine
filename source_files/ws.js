import WebSocket from 'ws';
import {
  HYPERLIQUID_WS_URL,
  WS_RECONNECT_BASE_MS,
  WS_RECONNECT_MAX_MS,
  WS_MAX_RECONNECT_ATTEMPTS,
} from './config.js';

/**
 * WebSocket Manager for Hyperliquid DEX
 * 
 * Handles real-time data streams: prices, trades, orderbook, liquidations, user events.
 * Supports multiple subscriptions to the same channel for different coins concurrently.
 * Automatically reconnects on disconnection with exponential backoff and re-subscribes
 * to all channels.
 * 
 * @class HyperliquidWSManager
 */
class HyperliquidWSManager {
  /**
   * Create WebSocket manager
   * 
   * @param {Object} config - Configuration
   * @param {string} [config.address] - 0x-prefixed Hyperliquid address (for userEvents)
   * @param {boolean} [config.debug=false] - Enable debug logging
   * @param {number} [config.reconnectBaseMs=5000] - Base reconnect delay in ms
   * @param {number} [config.reconnectMaxMs=60000] - Max reconnect delay in ms
   * @param {number} [config.maxReconnectAttempts=50] - Max consecutive reconnect attempts before emitting error
   * 
   * @example
   * // For market data only (no userEvents)
   * const manager = new HyperliquidWSManager({ debug: true });
   * 
   * @example
   * // For userEvents (requires address)
   * const manager = new HyperliquidWSManager({
   *   address: "0x...",
   *   debug: true
   * });
   */
  constructor({ address = null, debug = false, reconnectBaseMs = WS_RECONNECT_BASE_MS, reconnectMaxMs = WS_RECONNECT_MAX_MS, maxReconnectAttempts = WS_MAX_RECONNECT_ATTEMPTS } = {}) {
    this.address = address;
    this.debug = debug;

    this.ws = null;
    this.url = HYPERLIQUID_WS_URL;

    // Use composite keys: "channel:paramsHash" -> { params, callbacks: Set<Function> }
    // This allows multiple subscriptions to the same channel type for different coins
    this._subscriptions = new Map();

    this.pendingQueue = [];
    this.isConnected = false;
    this._isFirstConnection = true;
    this._intentionalClose = false;

    // Reconnection with exponential backoff
    this._reconnectBaseMs = reconnectBaseMs;
    this._reconnectMaxMs = reconnectMaxMs;
    this._maxReconnectAttempts = maxReconnectAttempts;
    this._reconnectAttempts = 0;
    this._reconnectTimer = null;

    // Error callback for when max reconnects exhausted
    this._onFatalError = null;

    this.connect();
  }

  /**
   * Register a callback for fatal errors (e.g. max reconnects exhausted)
   * @param {Function} callback - Called with error message
   */
  onFatalError(callback) {
    this._onFatalError = callback;
  }

  // ---------------------------------------------------------------------------
  // Connection lifecycle
  // ---------------------------------------------------------------------------

  /**
   * Establish WebSocket connection with automatic reconnection on close.
   * @private
   */
  connect() {
    if (this._intentionalClose) return;
    if (this.debug) console.log(`Connecting to ${this.url}...`);

    this.ws = new WebSocket(this.url);

    this.ws.on('open', () => {
      this.isConnected = true;
      this._reconnectAttempts = 0; // Reset backoff on successful connect

      if (this.debug) console.log('✅ WebSocket connected');

      // Flush pending messages
      while (this.pendingQueue.length > 0) {
        const msg = this.pendingQueue.shift();
        this.ws.send(JSON.stringify(msg));
      }

      // Resubscribe on reconnection (not first connection)
      if (!this._isFirstConnection) {
        this._resubscribeAll();
      } else {
        this._isFirstConnection = false;
      }
    });

    this.ws.on('message', (data) => {
      try {
        const parsed = JSON.parse(data.toString());
        this._handleMessage(parsed);
      } catch (error) {
        if (this.debug) console.error('Failed to parse WS message:', error);
      }
    });

    this.ws.on('error', (error) => {
      if (this.debug) console.error('WS Error:', error.message);
    });

    this.ws.on('close', () => {
      this.isConnected = false;

      // Don't reconnect if close() was called intentionally
      if (this._intentionalClose) return;

      this._reconnectAttempts += 1;

      if (this._reconnectAttempts > this._maxReconnectAttempts) {
        const msg = `WebSocket max reconnect attempts (${this._maxReconnectAttempts}) exhausted`;
        console.error(`❌ ${msg}`);
        if (this._onFatalError) this._onFatalError(msg);
        return;
      }

      // Exponential backoff with jitter
      const exp = Math.min(
        this._reconnectBaseMs * Math.pow(2, this._reconnectAttempts - 1),
        this._reconnectMaxMs
      );
      const jitter = Math.random() * exp * 0.2; // up to 20% jitter
      const delay = Math.round(exp + jitter);

      if (this.debug) {
        console.log(`❌ WebSocket closed. Reconnecting in ${delay}ms (attempt ${this._reconnectAttempts}/${this._maxReconnectAttempts})...`);
      }

      this._reconnectTimer = setTimeout(() => this.connect(), delay);
    });
  }

  // ---------------------------------------------------------------------------
  // Message routing
  // ---------------------------------------------------------------------------

  /**
   * Route an incoming message to all registered callbacks for the matching
   * subscription(s). Hyperliquid sends messages with a `channel` field and
   * optional `data.coin` (for per-coin channels). We match against composite
   * subscription keys to dispatch to the correct callbacks.
   * 
   * @private
   * @param {Object} msg - Parsed WebSocket message
   */
  _handleMessage(msg) {
    if (!msg.channel) {
      if (this.debug) console.log('Non-data message:', msg);
      return;
    }

    const channel = msg.channel;
    const dataCoin = msg.data?.coin ?? null;

    // Try exact composite key first (channel + coin)
    if (dataCoin) {
      const exactKey = this._makeKey(channel, { coin: dataCoin });
      const sub = this._subscriptions.get(exactKey);
      if (sub) {
        for (const cb of sub.callbacks) {
          try { cb(msg.data); } catch (err) {
            console.error(`WS callback error [${exactKey}]:`, err);
          }
        }
        return;
      }
    }

    // Fall back to channel-only key (for global channels like allMids, liquidations)
    const globalKey = this._makeKey(channel, {});
    const globalSub = this._subscriptions.get(globalKey);
    if (globalSub) {
      for (const cb of globalSub.callbacks) {
        try { cb(msg.data); } catch (err) {
          console.error(`WS callback error [${globalKey}]:`, err);
        }
      }
      return;
    }

    // userEvents arrive on channel "user" but subscription type is "userEvents"
    // Handle this special mapping
    if (channel === 'user') {
      const userKey = this._makeKey('userEvents', { user: this.address });
      const userSub = this._subscriptions.get(userKey);
      if (userSub) {
        for (const cb of userSub.callbacks) {
          try { cb(msg.data); } catch (err) {
            console.error(`WS callback error [${userKey}]:`, err);
          }
        }
        return;
      }
    }

    if (this.debug) {
      console.log(`No callback for channel: ${channel} (coin: ${dataCoin})`);
    }
  }

  // ---------------------------------------------------------------------------
  // Subscribe / unsubscribe primitives
  // ---------------------------------------------------------------------------

  /**
   * Create a deterministic composite key from channel + params.
   * @private
   */
  _makeKey(channel, params) {
    const paramStr = Object.keys(params).sort().map(k => `${k}=${params[k]}`).join('&');
    return paramStr ? `${channel}:${paramStr}` : channel;
  }

  /**
   * Build the subscription message for a given channel + params.
   * @private
   */
  _buildSubMessage(channel, params) {
    return {
      method: "subscribe",
      subscription: { type: channel, ...params }
    };
  }

  /**
   * Subscribe to a channel. Supports multiple callbacks per channel+params combo
   * and multiple subscriptions to the same channel type for different params
   * (e.g. trades for BTC and trades for ETH simultaneously).
   * 
   * @private
   * @param {string} channel - Subscription channel type
   * @param {Object} params - Subscription parameters (e.g. { coin: "BTC" })
   * @param {Function} callback - Data callback
   * @returns {string} Subscription key (for unsubscribing)
   */
  _subscribe(channel, params, callback) {
    const key = this._makeKey(channel, params);

    let sub = this._subscriptions.get(key);
    if (sub) {
      // Already subscribed to this channel+params — just add the callback
      sub.callbacks.add(callback);
    } else {
      // New subscription — register and send subscribe message
      sub = { channel, params, callbacks: new Set([callback]) };
      this._subscriptions.set(key, sub);
      this._send(this._buildSubMessage(channel, params));
    }

    if (this.debug) {
      console.log(`Subscribed to ${key} (${sub.callbacks.size} callback(s))`);
    }

    return key;
  }

  /**
   * Unsubscribe a specific callback from a subscription key. If no callbacks
   * remain, the WebSocket unsubscribe message is sent and the subscription
   * is removed entirely.
   * 
   * @private
   * @param {string} key - Composite subscription key
   * @param {Function} [callback] - Specific callback to remove. If omitted, removes all.
   */
  _unsubscribeByKey(key, callback) {
    const sub = this._subscriptions.get(key);
    if (!sub) return;

    if (callback) {
      sub.callbacks.delete(callback);
    } else {
      sub.callbacks.clear();
    }

    if (sub.callbacks.size === 0) {
      this._subscriptions.delete(key);

      const unsubMsg = {
        method: "unsubscribe",
        subscription: { type: sub.channel, ...sub.params }
      };
      this._send(unsubMsg);

      if (this.debug) {
        console.log(`Unsubscribed from ${key}`);
      }
    } else if (this.debug) {
      console.log(`Removed callback from ${key} (${sub.callbacks.size} remaining)`);
    }
  }

  /**
   * Resubscribe to all channels (on reconnection).
   * @private
   */
  _resubscribeAll() {
    if (this.debug) console.log('🔄 Resubscribing to all channels...');

    for (const [, sub] of this._subscriptions.entries()) {
      this._send(this._buildSubMessage(sub.channel, sub.params));
    }
  }

  /**
   * Send message to WebSocket. Queues if not connected.
   * @private
   * @param {Object} msg - Message to send
   */
  _send(msg) {
    if (this.isConnected && this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg));
      if (this.debug) console.log('📤 Sent:', JSON.stringify(msg));
    } else {
      this.pendingQueue.push(msg);
      if (this.debug) console.log('📦 Queued:', JSON.stringify(msg));
    }
  }

  // ---------------------------------------------------------------------------
  // Public subscription API
  // ---------------------------------------------------------------------------

  /**
   * Subscribe to all mid prices (all trading pairs, global feed).
   * 
   * @param {Function} callback - Called on every price update
   * @returns {string} Subscription key
   * 
   * @example
   * manager.subscribeAllMids((data) => {
   *   const btcPrice = parseFloat(data.mids.BTC);
   * });
   */
  subscribeAllMids(callback) {
    return this._subscribe("allMids", {}, callback);
  }

  /**
   * Subscribe to real-time trades for a coin. You can call this multiple times
   * for different coins — each gets its own independent subscription.
   * 
   * @param {string} coin - Coin symbol (e.g., "BTC", "ETH", "SOL")
   * @param {Function} callback - Called on new trades
   * @returns {string} Subscription key
   * 
   * @example
   * // Subscribe to BTC and ETH trades simultaneously
   * const btcKey = manager.subscribeTrades("BTC", handleBtcTrades);
   * const ethKey = manager.subscribeTrades("ETH", handleEthTrades);
   */
  subscribeTrades(coin, callback) {
    return this._subscribe("trades", { coin }, callback);
  }

  /**
   * Subscribe to L2 order book updates for a coin. Multiple coins supported.
   * 
   * @param {string} coin - Coin symbol
   * @param {Function} callback - Called on orderbook update
   * @returns {string} Subscription key
   */
  subscribeL2Book(coin, callback) {
    return this._subscribe("l2Book", { coin }, callback);
  }

  /**
   * Subscribe to liquidation events (global feed).
   * 
   * @param {Function} callback - Called on liquidation
   * @returns {string} Subscription key
   */
  subscribeLiquidations(callback) {
    return this._subscribe("liquidations", {}, callback);
  }

  /**
   * Subscribe to authenticated user events (requires address in constructor).
   * Multiple callbacks can be registered and all will receive events.
   * 
   * IMPORTANT: Subscription type is "userEvents" but responses arrive on "user" channel.
   * 
   * @param {Function} callback - Called on every user event
   * @returns {string} Subscription key
   * @throws {Error} If address not provided
   */
  subscribeUserEvents(callback) {
    if (!this.address) {
      throw new Error("Address required for user events. Provide 'address' in constructor.");
    }
    return this._subscribe("userEvents", { user: this.address }, callback);
  }

  // ---------------------------------------------------------------------------
  // Public unsubscription API
  // ---------------------------------------------------------------------------

  /**
   * Unsubscribe using the key returned by a subscribe* method.
   * Optionally pass the specific callback to remove only that listener.
   * 
   * @param {string} key - Subscription key from subscribe*()
   * @param {Function} [callback] - Specific callback to remove; omit to remove all
   * 
   * @example
   * const key = manager.subscribeTrades("BTC", myHandler);
   * // Later:
   * manager.unsubscribe(key, myHandler); // remove one callback
   * manager.unsubscribe(key);            // remove all callbacks and unsubscribe
   */
  unsubscribe(key, callback) {
    this._unsubscribeByKey(key, callback);
  }

  /** Convenience: unsubscribe from all mids */
  unsubscribeAllMids() {
    this._unsubscribeByKey(this._makeKey("allMids", {}));
  }

  /** Convenience: unsubscribe from trades for a specific coin */
  unsubscribeTrades(coin) {
    this._unsubscribeByKey(this._makeKey("trades", { coin }));
  }

  /** Convenience: unsubscribe from L2 book for a specific coin */
  unsubscribeL2Book(coin) {
    this._unsubscribeByKey(this._makeKey("l2Book", { coin }));
  }

  /** Convenience: unsubscribe from liquidations */
  unsubscribeLiquidations() {
    this._unsubscribeByKey(this._makeKey("liquidations", {}));
  }

  /** Convenience: unsubscribe from user events */
  unsubscribeUserEvents() {
    if (this.address) {
      this._unsubscribeByKey(this._makeKey("userEvents", { user: this.address }));
    }
  }

  // ---------------------------------------------------------------------------
  // Introspection
  // ---------------------------------------------------------------------------

  /**
   * Check if WebSocket connection is open
   * @returns {boolean}
   */
  isConnectionOpen() {
    return this.isConnected && this.ws && this.ws.readyState === WebSocket.OPEN;
  }

  /**
   * Get list of active subscription keys
   * @returns {Array<string>}
   */
  getActiveSubscriptions() {
    return Array.from(this._subscriptions.keys());
  }

  // ---------------------------------------------------------------------------
  // Teardown
  // ---------------------------------------------------------------------------

  /**
   * Close WebSocket connection permanently. Prevents auto-reconnect.
   */
  close() {
    this._intentionalClose = true;

    if (this._reconnectTimer) {
      clearTimeout(this._reconnectTimer);
      this._reconnectTimer = null;
    }

    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }

    this.isConnected = false;
    this._subscriptions.clear();
    this.pendingQueue = [];

    if (this.debug) console.log('WebSocket closed manually');
  }
}

export { HyperliquidWSManager };
