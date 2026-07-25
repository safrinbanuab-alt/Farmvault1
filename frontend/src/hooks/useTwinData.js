import { useEffect, useRef, useState } from 'react'
import { getTwin, getTwinSensorHistory, getTwinTimeline, getRecommendations } from '../services/api.js'
import { connectTwinSocket } from '../services/websocket.js'

const MAX_HISTORY_POINTS = 200

/**
 * Loads a produce twin's current state, sensor history, recommendations, and
 * timeline over REST, then keeps them live via the /ws/twin/{id} socket
 * fed by the IoT simulator's event bus.
 */
export default function useTwinData(produceId) {
  const [twin, setTwin] = useState(null)
  const [sensorHistory, setSensorHistory] = useState([])
  const [recommendations, setRecommendations] = useState([])
  const [timelineEvents, setTimelineEvents] = useState([])
  const [connected, setConnected] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const socketRef = useRef(null)

  useEffect(() => {
    if (!produceId) {
      setLoading(false)
      return
    }

    let cancelled = false
    setLoading(true)
    setError(null)

    Promise.all([
      getTwin(produceId),
      getTwinSensorHistory(produceId),
      getTwinTimeline(produceId),
      getRecommendations(produceId)
    ])
      .then(([twinData, history, timeline, recs]) => {
        if (cancelled) return
        setTwin(twinData)
        setSensorHistory(history ?? [])
        setTimelineEvents(timeline ?? [])
        setRecommendations(recs ?? [])
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || 'Failed to load produce twin')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    socketRef.current = connectTwinSocket(produceId, {
      onOpen: () => !cancelled && setConnected(true),
      onClose: () => !cancelled && setConnected(false),
      onError: () => !cancelled && setConnected(false),
      onMessage: (message) => {
        if (cancelled || !message?.type) return

        switch (message.type) {
          case 'sensor_update':
            setSensorHistory((prev) => [...prev.slice(-MAX_HISTORY_POINTS + 1), message.data])
            setTwin((prev) =>
              prev
                ? {
                    ...prev,
                    current_temp: message.data.temperature ?? prev.current_temp,
                    current_humidity: message.data.humidity ?? prev.current_humidity,
                    freshness_score: message.data.freshness_score ?? prev.freshness_score
                  }
                : prev
            )
            break

          case 'twin_update':
            setTwin((prev) => (prev ? { ...prev, ...message.data } : message.data))
            break

          case 'timeline_event':
            setTimelineEvents((prev) => [message.data, ...prev])
            break

          case 'recommendation':
            setRecommendations((prev) => {
              const withoutDup = prev.filter((r) => r.id !== message.data.id)
              return [message.data, ...withoutDup]
            })
            break

          case 'anomaly':
            setTimelineEvents((prev) => [
              {
                id: message.data.id ?? `anomaly-${Date.now()}`,
                title: message.data.title ?? 'Anomaly injected',
                description: message.data.description,
                timestamp: message.data.timestamp ?? new Date().toISOString(),
                type: 'critical'
              },
              ...prev
            ])
            break

          default:
            break
        }
      }
    })

    return () => {
      cancelled = true
      socketRef.current?.close()
    }
  }, [produceId])

  return { twin, sensorHistory, recommendations, timelineEvents, connected, loading, error }
}