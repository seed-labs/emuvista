import { randomUUID } from 'node:crypto'

type Packet = Record<string, any>
interface Reply { control?: Packet; metadata?: Packet; messages: Packet[] }

export class Tinode {
  private readonly socket: WebSocket

  constructor(endpoint: string, apiKey: string, private readonly signal: AbortSignal) {
    const url = new URL('/v0/channels', endpoint)
    url.searchParams.set('apikey', apiKey)
    this.socket = new WebSocket(url)
  }

  async open(): Promise<void> {
    await new Promise<void>((resolve, reject) => {
      const clean = () => {
        this.signal.removeEventListener('abort', failed)
        this.socket.removeEventListener('open', opened)
        this.socket.removeEventListener('error', failed)
        this.socket.removeEventListener('close', failed)
      }
      const opened = () => { clean(); resolve() }
      const failed = () => { clean(); reject(new Error('Tinode connection failed or timed out')) }
      if (this.signal.aborted) return failed()
      this.signal.addEventListener('abort', failed, { once: true })
      this.socket.addEventListener('open', opened, { once: true })
      this.socket.addEventListener('error', failed, { once: true })
      this.socket.addEventListener('close', failed, { once: true })
    })
    await this.request('hi', { ver: '0.25', ua: 'EmuVista E30', lang: 'en' })
  }

  close(): void {
    this.socket.close()
  }

  request(operation: string, payload: Packet, metadata = false): Promise<Reply> {
    const id = randomUUID()
    const messages: Packet[] = []
    return new Promise((resolve, reject) => {
      const clean = () => {
        this.signal.removeEventListener('abort', failed)
        this.socket.removeEventListener('message', received)
        this.socket.removeEventListener('error', failed)
        this.socket.removeEventListener('close', failed)
      }
      const failed = () => { clean(); reject(new Error(`Tinode ${operation} connection closed or timed out`)) }
      const received = (event: MessageEvent) => {
        let packet: Packet
        try { packet = JSON.parse(String(event.data)) } catch { return }
        if (packet.data && operation === 'get' && payload.what === 'data') messages.push(packet.data)
        if (packet.meta?.id === id && metadata) {
          clean()
          resolve({ metadata: packet.meta, messages })
        }
        const ctrl = packet.ctrl
        if (ctrl?.id !== id) return
        clean()
        if (ctrl.code >= 400) reject(new Error(`Tinode ${operation} failed (status ${ctrl.code})`))
        else resolve({ control: ctrl, messages })
      }
      if (this.signal.aborted || this.socket.readyState !== WebSocket.OPEN) return failed()
      this.signal.addEventListener('abort', failed, { once: true })
      this.socket.addEventListener('message', received)
      this.socket.addEventListener('error', failed, { once: true })
      this.socket.addEventListener('close', failed, { once: true })
      try { this.socket.send(JSON.stringify({ [operation]: { ...payload, id } })) } catch { failed() }
    })
  }
}
