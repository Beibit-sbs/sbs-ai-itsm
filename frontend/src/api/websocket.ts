/**
 * WebSocket client for real-time dashboard updates.
 * Provides typed, event-driven interface for receiving dashboard data streams.
 */

import React from 'react'
import { DashboardSummary, MetricsTimeline, ActiveAlerts, RolloutComparison, AnomalyTimeline, CorrelationMatrix } from './client'

export type DashboardStreamType = 'summary' | 'metrics' | 'alerts' | 'comparison' | 'anomalies' | 'correlation'

export interface WebSocketMessage<T = any> {
  type: string
  data?: T
  timestamp: string
  message?: string
  streams?: string[]
}

export interface DashboardStreamListener {
  onSummaryUpdate?: (data: DashboardSummary) => void
  onMetricsUpdate?: (data: MetricsTimeline) => void
  onAlertsUpdate?: (data: ActiveAlerts) => void
  onComparisonUpdate?: (data: RolloutComparison) => void
  onAnomaliesUpdate?: (data: AnomalyTimeline) => void
  onCorrelationUpdate?: (data: CorrelationMatrix) => void
  onError?: (error: string) => void
  onConnect?: () => void
  onDisconnect?: () => void
  onSubscribed?: (streams: string[]) => void
}

/**
 * WebSocket client for real-time dashboard data streaming.
 * Automatically reconnects on disconnect.
 * Supports dynamic subscription/unsubscription.
 */
export class DashboardWebSocketClient {
  private ws: WebSocket | null = null
  private baseUrl: string
  private accessToken: string
  private socketToken: string | null = null
  private listeners: DashboardStreamListener[] = []
  private reconnectAttempts = 0
  private maxReconnectAttempts = 5
  private reconnectDelay = 1000
  private keepAliveInterval: ReturnType<typeof setInterval> | null = null
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private shouldReconnect = true
  private subscribedStreams: Set<DashboardStreamType> = new Set()

  constructor(baseUrl: string, accessToken: string) {
    this.baseUrl = baseUrl
    this.accessToken = accessToken
  }

  /**
   * Fetch a temporary socket token for WebSocket connection.
   * This is more secure than passing JWT directly in query parameter.
   */
  private async fetchSocketToken(): Promise<string> {
    const response = await fetch(`${this.baseUrl}/api/v1/jobs/dashboard/socket-token`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${this.accessToken}`,
        'Content-Type': 'application/json',
      },
    })
    
    if (!response.ok) {
      throw new Error(`Failed to fetch socket token: ${response.statusText}`)
    }
    
    const data = await response.json()
    return data.socket_token
  }

  /**
   * Build WebSocket URL from HTTP base URL and socket token
   */
  private buildWebSocketUrl(socketToken: string): string {
    const httpUrl = new URL(this.baseUrl, window.location.href)
    const protocol = httpUrl.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${protocol}//${httpUrl.host}/api/v1/jobs/dashboard/ws?token=${encodeURIComponent(socketToken)}`
  }

  /**
   * Connect to WebSocket server
   */
  async connect(): Promise<void> {
    this.shouldReconnect = true
    return new Promise(async (resolve, reject) => {
      try {
        // First, get a temporary socket token (more secure than using JWT directly)
        if (!this.socketToken) {
          try {
            this.socketToken = await this.fetchSocketToken()
          } catch (error) {
            reject(new Error(`Failed to authenticate WebSocket connection: ${error}`))
            return
          }
        }

        const wsUrl = this.buildWebSocketUrl(this.socketToken)
        this.ws = new WebSocket(wsUrl)

        this.ws.onopen = () => {
          this.reconnectAttempts = 0
          this.startKeepAlive()
          this.sendCurrentSubscription()
          this.notifyListeners('onConnect')
          resolve()
        }

        this.ws.onmessage = (event) => {
          this.handleMessage(event.data)
        }

        this.ws.onerror = (event) => {
          console.error('WebSocket error:', event)
          this.notifyListeners('onError', 'WebSocket connection error')
          reject(new Error('WebSocket connection error'))
        }

        this.ws.onclose = () => {
          this.stopKeepAlive()
          this.notifyListeners('onDisconnect')
          if (this.shouldReconnect) {
            this.attemptReconnect()
          }
        }
      } catch (error) {
        console.error('WebSocket connection failed:', error)
        reject(error)
      }
    })
  }

  /**
   * Disconnect from WebSocket server
   */
  disconnect(): void {
    this.shouldReconnect = false
    this.stopKeepAlive()
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    if (this.ws) {
      this.ws.close()
      this.ws = null
    }
  }

  /**
   * Subscribe to one or more dashboard data streams
   */
  subscribe(streams: DashboardStreamType[]): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      console.warn('WebSocket not connected, cannot subscribe')
      return
    }

    streams.forEach((stream) => this.subscribedStreams.add(stream))
    this.sendCurrentSubscription()
  }

  /**
   * Unsubscribe from one or more dashboard data streams
   */
  unsubscribe(streams: DashboardStreamType[]): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      console.warn('WebSocket not connected, cannot unsubscribe')
      return
    }

    streams.forEach((stream) => this.subscribedStreams.delete(stream))

    this.ws.send(
      JSON.stringify({
        type: 'unsubscribe',
        streams,
      })
    )
  }

  /**
   * Register a listener for WebSocket events
   */
  addListener(listener: DashboardStreamListener): void {
    this.listeners.push(listener)
  }

  /**
   * Unregister a listener
   */
  removeListener(listener: DashboardStreamListener): void {
    this.listeners = this.listeners.filter((l) => l !== listener)
  }

  /**
   * Send keep-alive ping to server
   */
  private sendKeepAlive(): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(
        JSON.stringify({
          type: 'ping',
          timestamp: new Date().toISOString(),
        })
      )
    }
  }

  /**
   * Start keep-alive ping interval (every 30 seconds)
   */
  private startKeepAlive(): void {
    this.keepAliveInterval = setInterval(() => {
      this.sendKeepAlive()
    }, 30000)
  }

  /**
   * Stop keep-alive ping interval
   */
  private stopKeepAlive(): void {
    if (this.keepAliveInterval) {
      clearInterval(this.keepAliveInterval)
      this.keepAliveInterval = null
    }
  }

  private sendCurrentSubscription(): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN || this.subscribedStreams.size === 0) {
      return
    }
    this.ws.send(
      JSON.stringify({
        type: 'subscribe',
        streams: Array.from(this.subscribedStreams),
      })
    )
  }

  /**
   * Handle incoming WebSocket message
   */
  private handleMessage(data: string): void {
    try {
      const message: WebSocketMessage = JSON.parse(data)

      switch (message.type) {
        case 'summary':
          if (message.data) {
            this.notifyListeners('onSummaryUpdate', message.data as DashboardSummary)
          }
          break
        case 'metrics':
          if (message.data) {
            this.notifyListeners('onMetricsUpdate', message.data as MetricsTimeline)
          }
          break
        case 'alerts':
          if (message.data) {
            this.notifyListeners('onAlertsUpdate', message.data as ActiveAlerts)
          }
          break
        case 'comparison':
          if (message.data) {
            this.notifyListeners('onComparisonUpdate', message.data as RolloutComparison)
          }
          break
        case 'anomalies':
          if (message.data) {
            this.notifyListeners('onAnomaliesUpdate', message.data as AnomalyTimeline)
          }
          break
        case 'correlation':
          if (message.data) {
            this.notifyListeners('onCorrelationUpdate', message.data as CorrelationMatrix)
          }
          break
        case 'subscription_confirmed':
          if (message.streams) {
            this.notifyListeners('onSubscribed', message.streams)
          }
          break
        case 'pong':
          // Keep-alive response, just log
          console.debug('WebSocket pong received')
          break
        case 'error':
          this.notifyListeners('onError', message.message || 'Unknown error')
          break
        default:
          console.warn(`Unknown WebSocket message type: ${message.type}`)
      }
    } catch (error) {
      console.error('Error parsing WebSocket message:', error)
    }
  }

  /**
   * Attempt to reconnect to WebSocket server
   */
  private attemptReconnect(): void {
    if (!this.shouldReconnect) {
      return
    }
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error('Max reconnection attempts reached')
      this.notifyListeners('onError', 'Failed to reconnect to WebSocket')
      return
    }

    this.reconnectAttempts++
    const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1)
    
    console.log(`Attempting to reconnect in ${delay}ms (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`)

    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      if (!this.shouldReconnect) {
        return
      }
      // Clear old socket token to get a fresh one on reconnect
      this.socketToken = null
      
      this.connect().catch((error) => {
        console.error('Reconnection failed:', error)
      })
    }, delay)
  }

  /**
   * Notify all listeners of an event
   */
  private notifyListeners(eventName: keyof DashboardStreamListener, data?: any): void {
    this.listeners.forEach((listener) => {
      const callback = listener[eventName]
      if (typeof callback === 'function') {
        try {
          callback(data)
        } catch (error) {
          console.error(`Error in listener callback ${String(eventName)}:`, error)
        }
      }
    })
  }

  /**
   * Get current connection state
   */
  isConnected(): boolean {
    return this.ws !== null && this.ws.readyState === WebSocket.OPEN
  }

  /**
   * Get currently subscribed streams
   */
  getSubscribedStreams(): DashboardStreamType[] {
    return Array.from(this.subscribedStreams)
  }
}

/**
 * Hook for using WebSocket client in React components
 */
export function useDashboardWebSocket(baseUrl: string, accessToken: string) {
  const [isConnected, setIsConnected] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const clientRef = React.useRef<DashboardWebSocketClient | null>(null)

  React.useEffect(() => {
    if (!accessToken) {
      setIsConnected(false)
      setError(null)
      clientRef.current = null
      return
    }

    const client = new DashboardWebSocketClient(baseUrl, accessToken)
    clientRef.current = client

    client.addListener({
      onConnect: () => {
        setIsConnected(true)
        setError(null)
      },
      onDisconnect: () => {
        setIsConnected(false)
      },
      onError: (errorMsg) => {
        setError(errorMsg)
      },
    })

    client.connect().catch((err) => {
      setError(err.message)
    })

    return () => {
      client.disconnect()
    }
  }, [baseUrl, accessToken])

  return {
    client: clientRef.current,
    isConnected,
    error,
  }
}
