#!/usr/bin/env node

import fs from "node:fs/promises";

function parseArgs(argv) {
  const args = {};
  for (let i = 2; i < argv.length; i += 1) {
    const token = argv[i];
    if (!token.startsWith("--")) {
      continue;
    }
    const key = token.slice(2);
    const value = argv[i + 1];
    if (value === undefined || value.startsWith("--")) {
      args[key] = "true";
      continue;
    }
    args[key] = value;
    i += 1;
  }
  return args;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function parseHeight(value) {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string") {
    if (value.startsWith("0x") || value.startsWith("0X")) {
      const parsed = Number.parseInt(value, 16);
      return Number.isFinite(parsed) ? parsed : null;
    }
    const parsed = Number.parseInt(value, 10);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function extractHeadNumber(payload) {
  if (payload === null || payload === undefined) {
    return null;
  }
  if (typeof payload !== "object") {
    return parseHeight(payload);
  }
  if (payload.header && typeof payload.header === "object") {
    const headerNumber = parseHeight(payload.header.number);
    if (headerNumber !== null) {
      return headerNumber;
    }
  }
  if (Array.isArray(payload)) {
    for (const item of payload) {
      const nested = extractHeadNumber(item);
      if (nested !== null) {
        return nested;
      }
    }
    return null;
  }
  for (const value of Object.values(payload)) {
    const nested = extractHeadNumber(value);
    if (nested !== null) {
      return nested;
    }
  }
  return null;
}

function classifyError(message) {
  const lowered = String(message || "").toLowerCase();
  if (
    lowered.includes("tls") ||
    lowered.includes("ssl") ||
    lowered.includes("cert") ||
    lowered.includes("handshake") ||
    lowered.includes("eproto")
  ) {
    return "tls";
  }
  return "other";
}

function pushSample(target, value, limit = 8) {
  if (target.length >= limit) {
    return;
  }
  target.push(String(value));
}

async function rpcChainInfo(httpUrl) {
  const response = await fetch(httpUrl, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      jsonrpc: "2.0",
      method: "chain.info",
      params: [],
      id: 1,
    }),
  });
  if (!response.ok) {
    throw new Error(`http status ${response.status}`);
  }
  const data = await response.json();
  const head = data?.result?.head?.number;
  const height = parseHeight(head);
  if (height === null) {
    throw new Error(`invalid head number: ${JSON.stringify(head)}`);
  }
  return height;
}

function heightAt(records, ts) {
  if (records.length === 0) {
    return null;
  }
  let candidate = records[0].height;
  for (const item of records) {
    if (item.ts <= ts) {
      candidate = item.height;
      continue;
    }
    break;
  }
  return candidate;
}

function windowExpectedNotifications(records, startTs, endTs) {
  if (startTs === null || endTs === null || endTs <= startTs) {
    return null;
  }
  const startHeight = heightAt(records, startTs);
  const endHeight = heightAt(records, endTs);
  if (startHeight === null || endHeight === null) {
    return null;
  }
  return Math.max(0, endHeight - startHeight);
}

function heightAtOrAfter(records, ts) {
  for (const item of records) {
    if (item.ts >= ts) {
      return item.height;
    }
  }
  return records.length > 0 ? records[records.length - 1].height : null;
}

class WorkerProbe {
  constructor(index, wsUrl, endTs) {
    this.index = index;
    this.wsUrl = wsUrl;
    this.endTs = endTs;
    this.firstAckTs = null;
    this.lastAckTs = null;
    this.connectionAttempts = 0;
    this.connectionsOpened = 0;
    this.subscribeAcks = 0;
    this.disconnects = 0;
    this.reconnectAttempts = 0;
    this.reconnectSuccesses = 0;
    this.notifications = 0;
    this.uniqueHeads = new Set();
    this.transientErrors = 0;
    this.unexpectedErrors = 0;
    this.errors = [];
    this.tlsErrors = 0;
    this.connectedWindows = [];
    this._windowStartTs = null;
    this._windowHeads = new Set();
    this._active = true;
    this._socket = null;
    this._needReconnect = false;
    this._everConnected = false;
    this._reconnectTimer = null;
  }

  start() {
    this._connect();
  }

  stop() {
    this._active = false;
    this._closeWindow(Date.now());
    if (this._reconnectTimer !== null) {
      clearTimeout(this._reconnectTimer);
      this._reconnectTimer = null;
    }
    if (this._socket) {
      try {
        this._socket.close();
      } catch (_) {
        // ignored
      }
    }
  }

  _scheduleReconnect() {
    if (!this._active || Date.now() >= this.endTs) {
      return;
    }
    if (this._reconnectTimer !== null) {
      return;
    }
    this.reconnectAttempts += 1;
    this._reconnectTimer = setTimeout(() => {
      this._reconnectTimer = null;
      if (this._active && Date.now() < this.endTs) {
        this._connect();
      }
    }, 500);
  }

  _recordError(message, transient = false) {
    if (transient) {
      this.transientErrors += 1;
    } else {
      this.unexpectedErrors += 1;
      pushSample(this.errors, message);
    }
    if (classifyError(message) === "tls") {
      this.tlsErrors += 1;
    }
  }

  _closeWindow(endTs) {
    if (this._windowStartTs === null) {
      return;
    }
    const heads = Array.from(this._windowHeads).sort((a, b) => a - b);
    this.connectedWindows.push({
      start_ts: this._windowStartTs,
      end_ts: endTs,
      unique_heads: heads,
      unique_head_notifications: heads.length,
    });
    this._windowStartTs = null;
    this._windowHeads = new Set();
  }

  _connect() {
    if (!this._active || Date.now() >= this.endTs) {
      return;
    }
    this.connectionAttempts += 1;
    const requestId = this.index * 100000 + this.connectionAttempts;
    let closedHandled = false;
    let subscribed = false;
    const socket = new WebSocket(this.wsUrl);
    this._socket = socket;

    const handleClose = () => {
      if (closedHandled) {
        return;
      }
      closedHandled = true;
      if (!this._active) {
        return;
      }
      if (this._everConnected) {
        this.disconnects += 1;
        this._needReconnect = true;
        this._closeWindow(Date.now());
      }
      this._scheduleReconnect();
    };

    socket.addEventListener("open", () => {
      this.connectionsOpened += 1;
      this._everConnected = true;
      socket.send(
        JSON.stringify({
          jsonrpc: "2.0",
          id: requestId,
          method: "starcoin_subscribe",
          params: [["newHeads"]],
        }),
      );
    });

    socket.addEventListener("message", (event) => {
      let msg;
      try {
        msg = JSON.parse(String(event.data));
      } catch (err) {
        this._recordError(`invalid json message: ${err}`);
        return;
      }
      if (msg.id === requestId && msg.result !== undefined) {
        subscribed = true;
        this.subscribeAcks += 1;
        this.lastAckTs = Date.now();
        if (this.firstAckTs === null) {
          this.firstAckTs = this.lastAckTs;
        }
        if (this._windowStartTs === null) {
          this._windowStartTs = this.lastAckTs;
          this._windowHeads = new Set();
        }
        if (this._needReconnect) {
          this.reconnectSuccesses += 1;
          this._needReconnect = false;
        }
        return;
      }
      if (msg.error) {
        this._recordError(msg.error.message || JSON.stringify(msg.error));
        return;
      }
      if (msg.method === "starcoin_subscription") {
        this.notifications += 1;
        const headNumber = extractHeadNumber(msg.params?.result ?? msg.params);
        if (headNumber !== null) {
          this.uniqueHeads.add(headNumber);
          if (this._windowStartTs !== null) {
            this._windowHeads.add(headNumber);
          }
        }
      }
    });

    socket.addEventListener("error", (event) => {
      this._recordError(event?.message || "websocket error", this._everConnected);
      this._scheduleReconnect();
    });

    socket.addEventListener("close", () => {
      if (subscribed || this._everConnected) {
        handleClose();
      } else {
        this._recordError("websocket closed before subscribe ack", this._everConnected);
        this._scheduleReconnect();
      }
    });
  }

  summary(heightRecords, finalHeight) {
    const windows = [...this.connectedWindows];
    if (this._windowStartTs !== null) {
      windows.push({
        start_ts: this._windowStartTs,
        end_ts: Date.now(),
        unique_heads: Array.from(this._windowHeads).sort((a, b) => a - b),
        unique_head_notifications: this._windowHeads.size,
      });
    }
    let expectedNotifications = 0;
    let actualNotifications = 0;
    let hasExpected = false;
    const summarizedWindows = windows.map((window) => {
      const windowHeads = Array.isArray(window.unique_heads) ? window.unique_heads : [];
      const uniqueHeadCount =
        typeof window.unique_head_notifications === "number"
          ? window.unique_head_notifications
          : windowHeads.length;
      actualNotifications += uniqueHeadCount;
      const startHeight = heightAtOrAfter(heightRecords, window.start_ts ?? 0);
      const endHeight = heightAt(heightRecords, window.end_ts ?? 0);
      let windowExpected = null;
      if (startHeight !== null && endHeight !== null && endHeight >= startHeight) {
        windowExpected = Math.max(
          0,
          endHeight - startHeight + (uniqueHeadCount > 0 ? 1 : 0),
        );
      } else if (uniqueHeadCount > 0) {
        windowExpected = Math.max(1, windowHeads[windowHeads.length - 1] - windowHeads[0] + 1);
      } else {
        windowExpected = windowExpectedNotifications(
          heightRecords,
          window.start_ts ?? null,
          window.end_ts ?? null,
        );
      }
      if (typeof windowExpected === "number") {
        expectedNotifications += windowExpected;
        hasExpected = true;
      }
      return {
        ...window,
        start_height: startHeight,
        end_height: endHeight,
        expected_notifications: windowExpected,
      };
    });
    expectedNotifications = hasExpected ? expectedNotifications : null;
    const missingNotifications =
      expectedNotifications === null
        ? null
        : Math.max(0, expectedNotifications - actualNotifications);
    return {
      index: this.index,
      connection_attempts: this.connectionAttempts,
      connections_opened: this.connectionsOpened,
      subscribe_acks: this.subscribeAcks,
      first_ack_ts: this.firstAckTs,
      last_ack_ts: this.lastAckTs,
      disconnects: this.disconnects,
      reconnect_attempts: this.reconnectAttempts,
      reconnect_successes: this.reconnectSuccesses,
      notifications: this.notifications,
      unique_head_notifications: this.uniqueHeads.size,
      expected_notifications: expectedNotifications,
      missing_notifications: missingNotifications,
      connected_windows: summarizedWindows,
      transient_errors: this.transientErrors,
      unexpected_errors: this.unexpectedErrors,
      tls_errors: this.tlsErrors,
      errors: this.errors,
    };
  }
}

async function main() {
  const args = parseArgs(process.argv);
  const wsUrl = args["ws-url"];
  const httpUrl = args["http-url"];
  const output = args.output;
  const workers = Math.max(1, Number.parseInt(args.workers || "1", 10));
  const durationSeconds = Math.max(1, Number.parseInt(args["duration-seconds"] || "60", 10));

  if (!wsUrl || !httpUrl || !output) {
    throw new Error("required args: --ws-url --http-url --output");
  }

  const startTs = Date.now();
  const endTs = startTs + durationSeconds * 1000;
  const flushGraceMs = 1000;
  const heightRecords = [];
  let pollAttempts = 0;
  let pollSuccesses = 0;
  const pollErrors = [];

  const pollLoop = (async () => {
    while (Date.now() < endTs) {
      pollAttempts += 1;
      try {
        const height = await rpcChainInfo(httpUrl);
        pollSuccesses += 1;
        heightRecords.push({ ts: Date.now(), height });
      } catch (err) {
        pollErrors.push(String(err));
      }
      await sleep(1000);
    }
    try {
      pollAttempts += 1;
      const height = await rpcChainInfo(httpUrl);
      pollSuccesses += 1;
      heightRecords.push({ ts: Date.now(), height });
    } catch (err) {
      pollErrors.push(String(err));
    }
  })();

  const probes = Array.from({ length: workers }, (_, index) => new WorkerProbe(index + 1, wsUrl, endTs));
  for (const probe of probes) {
    probe.start();
  }

  const remaining = Math.max(0, endTs - Date.now());
  await sleep(remaining);
  await sleep(flushGraceMs);
  for (const probe of probes) {
    probe.stop();
  }
  await sleep(300);
  await pollLoop;

  const finalHeight = heightRecords.length > 0 ? heightRecords[heightRecords.length - 1].height : null;
  const workersSummary = probes.map((probe) => probe.summary(heightRecords, finalHeight));
  let totalExpected = 0;
  let totalMissing = 0;
  let totalNotifications = 0;
  let totalTlsErrors = 0;
  let totalConnections = 0;
  let totalTransientErrors = 0;
  let totalUnexpectedErrors = 0;
  let workersWithAck = 0;
  let workersNeedingReconnect = 0;
  let workersRecovered = 0;
  for (const item of workersSummary) {
    if (typeof item.expected_notifications === "number") {
      totalExpected += item.expected_notifications;
    }
    if (typeof item.missing_notifications === "number") {
      totalMissing += item.missing_notifications;
    }
    totalNotifications += item.unique_head_notifications || item.notifications;
    totalTlsErrors += item.tls_errors;
    totalConnections += item.connection_attempts;
    totalTransientErrors += item.transient_errors || 0;
    totalUnexpectedErrors += item.unexpected_errors || 0;
    if (item.subscribe_acks > 0) {
      workersWithAck += 1;
    }
    if (item.disconnects > 0 || item.reconnect_attempts > 0) {
      workersNeedingReconnect += 1;
      if (item.reconnect_successes > 0) {
        workersRecovered += 1;
      }
    }
  }

  const aggregate = {
    workers,
    duration_seconds: durationSeconds,
    final_height: finalHeight,
    poll_attempts: pollAttempts,
    poll_successes: pollSuccesses,
    subscribe_success_rate: workers > 0 ? (workersWithAck * 100.0) / workers : null,
    pubsub_drop_rate: totalExpected > 0 ? (totalMissing * 100.0) / totalExpected : null,
    reconnect_success_rate:
      workersNeedingReconnect > 0 ? (workersRecovered * 100.0) / workersNeedingReconnect : 100.0,
    tls_handshake_error_rate:
      totalConnections > 0 ? (totalTlsErrors * 100.0) / totalConnections : 0.0,
    total_expected_notifications: totalExpected,
    total_missing_notifications: totalMissing,
    total_received_notifications: totalNotifications,
    reconnect_attempts: workersSummary.reduce((sum, item) => sum + item.reconnect_attempts, 0),
    reconnect_successes: workersSummary.reduce((sum, item) => sum + item.reconnect_successes, 0),
    reconnect_workers: workersNeedingReconnect,
    reconnect_workers_recovered: workersRecovered,
    transient_errors: totalTransientErrors,
    unexpected_errors: totalUnexpectedErrors,
    tls_errors: totalTlsErrors,
  };
  let status = "ok";
  let error = null;
  if (pollSuccesses === 0) {
    status = "failed";
    error = "chain.info polling did not succeed";
  } else if (workersWithAck === 0) {
    status = "failed";
    error = "no successful pubsub subscription ack";
  }

  await fs.writeFile(
    output,
    JSON.stringify(
      {
        status,
        error,
        started_at: startTs / 1000,
        completed_at: Date.now() / 1000,
        ws_url: wsUrl,
        http_url: httpUrl,
        aggregate,
        height_records: heightRecords,
        poll_errors: pollErrors,
        workers: workersSummary,
      },
      null,
      2,
    ) + "\n",
    "utf8",
  );
}

main().catch(async (err) => {
  const args = parseArgs(process.argv);
  const output = args.output;
  const payload = {
    status: "failed",
    error: String(err),
  };
  if (output) {
    await fs.writeFile(output, JSON.stringify(payload, null, 2) + "\n", "utf8");
  } else {
    process.stderr.write(`${payload.error}\n`);
  }
  process.exit(1);
});
