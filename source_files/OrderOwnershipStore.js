import fs from 'fs';
import fsp from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

/**
 * Local durable store that tracks which orders belong to an agent.
 * Used for ownership-scoped cancel/cleanup on shared trading accounts.
 */
class OrderOwnershipStore {
  constructor(agentId) {
    if (!agentId) throw new Error('OrderOwnershipStore requires agentId');
    this.agentId = agentId;
    this.storeDir = path.join(__dirname, 'positions');
    this.storeFile = path.join(this.storeDir, `${agentId}_owned_orders.json`);
    this.state = { version: 1, agentId, orders: {} };

    if (!fs.existsSync(this.storeDir)) {
      fs.mkdirSync(this.storeDir, { recursive: true });
    }
    this._load();
  }

  _load() {
    try {
      if (!fs.existsSync(this.storeFile)) {
        this._save();
        return;
      }
      const parsed = JSON.parse(fs.readFileSync(this.storeFile, 'utf8'));
      if (parsed && typeof parsed === 'object' && parsed.orders) {
        this.state = parsed;
      }
    } catch (error) {
      console.error('OrderOwnershipStore load failed:', error.message);
      // Continue with empty in-memory state to avoid hard stop.
      this.state = { version: 1, agentId: this.agentId, orders: {} };
    }
  }

  _save() {
    fsp.writeFile(this.storeFile, JSON.stringify(this.state, null, 2))
      .catch(error => console.error('OrderOwnershipStore save failed:', error.message));
  }

  /**
   * Remove terminal-state orders older than maxAgeMs to prevent unbounded growth.
   * Called periodically (e.g. from cancelAgentOrders or on a schedule).
   * 
   * @param {number} maxAgeMs - Max age for terminal orders before pruning (default: 1 hour)
   * @param {number} maxEntries - Absolute cap on total entries (default: 500)
   * @returns {number} Number of entries pruned
   */
  prune(maxAgeMs = 60 * 60 * 1000, maxEntries = 500) {
    const terminalStatuses = new Set(['filled', 'cancelled', 'closed_external']);
    const now = Date.now();
    let pruned = 0;

    // Phase 1: Remove terminal-state entries older than maxAgeMs
    for (const [cloid, order] of Object.entries(this.state.orders)) {
      if (!terminalStatuses.has(order.status)) continue;
      const updatedAt = order.updatedAt ? new Date(order.updatedAt).getTime() : 0;
      if ((now - updatedAt) > maxAgeMs) {
        delete this.state.orders[cloid];
        pruned++;
      }
    }

    // Phase 2: If still over maxEntries, drop oldest terminal entries first
    const entries = Object.entries(this.state.orders);
    if (entries.length > maxEntries) {
      // Sort terminal entries by updatedAt ascending (oldest first)
      const terminalEntries = entries
        .filter(([, o]) => terminalStatuses.has(o.status))
        .sort((a, b) => {
          const ta = a[1].updatedAt ? new Date(a[1].updatedAt).getTime() : 0;
          const tb = b[1].updatedAt ? new Date(b[1].updatedAt).getTime() : 0;
          return ta - tb;
        });

      const toRemove = entries.length - maxEntries;
      for (let i = 0; i < Math.min(toRemove, terminalEntries.length); i++) {
        delete this.state.orders[terminalEntries[i][0]];
        pruned++;
      }
    }

    if (pruned > 0) {
      this._save();
      console.log(`🧹 OrderOwnershipStore: pruned ${pruned} stale entries (${Object.keys(this.state.orders).length} remaining)`);
    }

    return pruned;
  }

  registerOrder(order) {
    if (!order?.cloid) return null;
    const now = new Date().toISOString();
    const existing = this.state.orders[order.cloid] || {};
    const merged = {
      ...existing,
      ...order,
      orderId: order.orderId ?? existing.orderId ?? null,
      status: order.status ?? existing.status ?? 'open',
      createdAt: existing.createdAt || now,
      updatedAt: now
    };
    this.state.orders[order.cloid] = merged;
    this._save();
    return merged;
  }

  markByCloid(cloid, status, patch = {}) {
    const existing = this.state.orders[cloid];
    if (!existing) return false;
    this.state.orders[cloid] = {
      ...existing,
      ...patch,
      status,
      updatedAt: new Date().toISOString()
    };
    this._save();
    return true;
  }

  markByOrderId(orderId, status, patch = {}) {
    if (orderId == null) return false;
    const target = String(orderId);
    for (const [cloid, order] of Object.entries(this.state.orders)) {
      if (order.orderId != null && String(order.orderId) === target) {
        return this.markByCloid(cloid, status, patch);
      }
    }
    return false;
  }

  /**
   * Get orders considered "open" by the local store.
   * Filters out entries in terminal states and entries stuck in 'submitted'
   * status for longer than maxStaleMs (likely already filled/cancelled on exchange).
   * 
   * @param {string|null} coin - Optional coin filter
   * @param {number} maxStaleMs - Max age for 'submitted' status before treating as stale (default: 10 min)
   * @returns {Array<Object>}
   */
  getOpenOrders(coin = null, maxStaleMs = 10 * 60 * 1000) {
    const activeStatuses = new Set(['open', 'resting', 'submitted']);
    const now = Date.now();
    return Object.values(this.state.orders).filter(order => {
      if (!activeStatuses.has(order.status)) return false;
      if (coin && order.coin !== coin) return false;
      // Skip orders stuck in 'submitted' for too long — they likely resolved on-chain
      if (order.status === 'submitted') {
        const createdAt = order.createdAt ? new Date(order.createdAt).getTime() : 0;
        if ((now - createdAt) > maxStaleMs) return false;
      }
      return true;
    });
  }
}

export default OrderOwnershipStore;
