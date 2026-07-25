// Thin wrapper around the native WebSocket API for FarmVault's live feeds.
// Backed by backend/app/websocket/manager.py, which broadcasts events from
// the IoT simulator's event_bus (sensor ticks, anomalies, timeline events).

const WS_BASE =
  import.meta.env.VITE_WS_BASE_URL ||
  `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws`

const RECONNECT_DELAY_MS = 2000
const MAX_RECONNECT_DELAY_MS = 15000

/**
 * Open a resilient WebSocket connection with auto-reconnect and JSON parsing.
 * @param {string} path e.g. '/twin/123'
 * @param {{onOpen?: Function, onMessage?: (data: any) => void, onClose?: Function, onError?: Function}} handlers
 * @returns {{ close: () => void, send: (payload: any) => void }}
 */
export function connectSocket(path, handlers = {}) {
  const { onOpen, onMessage, onClose, onError } = handlers
  let socket = null
  let closedByCaller = false
  let reconnectDelay = RECONNECT_DELAY_MS
  let reconnectTimer = null

  function open() {
    socket = new WebSocket(`${WS_BASE}${path}`)

    socket.onopen = (event) => {
      reconnectDelay = RECONNECT_DELAY_MS
      onOpen?.(event)
    }

    socket.onmessage = (event) => {
      try {
        onMessage?.(JSON.parse(event.data))
      } catch {
        onMessage?.(event.data)
      }
    }

    socket.onerror = (event) => {
      onError?.(event)
    }

    socket.onclose = (event) => {
      onClose?.(event)
      if (!closedByCaller) {
        reconnectTimer = setTimeout(open, reconnectDelay)
        reconnectDelay = Math.min(reconnectDelay * 1.5, MAX_RECONNECT_DELAY_MS)
      }
    }
  }

  open()

  return {
    close() {
      closedByCaller = true
      clearTimeout(reconnectTimer)
      socket?.close()
    },
    send(payload) {
      if (socket?.readyState === WebSocket.OPEN) {
        socket.send(typeof payload === 'string' ? payload : JSON.stringify(payload))
      }
    }
  }
}

// Convenience helper for the produce twin live feed used by useTwinData.
export function connectTwinSocket(produceId, handlers) {
  return connectSocket(`/twin/${produceId}`, handlers)
}

// Convenience helper for live mandi price feeds.
export function connectMarketSocket(marketId, handlers) {
  return connectSocket(`/market/${marketId}`, handlers)
}