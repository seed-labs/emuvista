/** Keep resource identity stable across the configured proxy and local API. */
const browserHosts = new Set(['localhost', '127.0.0.1', 'host.docker.internal'])

function bases() {
  const internal = process.env.PAYMENT_ACCOUNTING_INTERNAL_URL
  const canonical = process.env.API_BASE_URL
  if (!internal || !canonical) return undefined
  return {
    internal: new URL(internal.replace(/\/$/, '') + '/'),
    canonical: new URL(canonical.replace(/\/$/, '') + '/'),
  }
}

function relativeTo(address: URL, base: URL) {
  if (address.origin !== base.origin || !address.pathname.startsWith(base.pathname)) return undefined
  return address.pathname.slice(base.pathname.length) + address.search
}

export function canonicalResourceURL(href: string): string {
  const configured = bases()
  if (!configured) return href
  const address = new URL(href)
  if (address.username || address.password || address.hash) return href
  let relative = relativeTo(address, configured.canonical) ?? relativeTo(address, configured.internal)
  if (relative === undefined && address.protocol === 'https:' && browserHosts.has(address.hostname)
      && address.port === process.env.PAYMENT_BROWSER_PORT && address.pathname.startsWith('/accounting/')) {
    relative = address.pathname.slice('/accounting/'.length) + address.search
  }
  return relative === undefined ? href : new URL(configured.canonical.href + relative).href
}

/** Resolve this application's public resources directly, including at bootstrap. */
export function resourceFetchURL(href: string): string {
  const configured = bases()
  if (!configured) return href
  const canonical = canonicalResourceURL(href)
  const address = new URL(canonical)
  if (address.username || address.password || address.hash) return href
  const relative = relativeTo(address, configured.canonical)
  return relative === undefined ? canonical : new URL(configured.internal.href + relative).href
}
