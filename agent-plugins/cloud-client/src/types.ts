export interface CloudAccount {
  baseUrl: string
  username: string
  password: string
}

export interface CloudClientConfig {
  curlPath?: string
  timeoutMs?: number
  maxTransferBytes?: number
  maxInlineBytes?: number
  maxMetadataBytes?: number
  downloadDirectory?: string
  versionDirectory?: string
  baseUrl?: string
  username?: string
}

export interface CloudHttpResponse {
  status: number
  headers: Record<string, string>
  body: Buffer
}
