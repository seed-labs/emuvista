// Expose the browser endpoint only to the colocated agent.
const fs = require('fs');
const { chromium } = require(process.env.PLAYWRIGHT_DRIVER_DIR + '/package');
(async () => {
  const config = JSON.parse(fs.readFileSync('/run/browser-agent/browser_connection.json', 'utf8'));
  const server = await chromium.launchServer({
    host: '127.0.0.1', port: 8080, wsPath: new URL(config.ws_endpoint).pathname,
    headless: false, args: ['--start-maximized', '--disable-dev-shm-usage'],
  });
  for (const signal of ['SIGTERM', 'SIGINT']) {
    process.once(signal, async () => { await server.close(); process.exit(0); });
  }
  server.on('close', () => process.exit(0));
})().catch(() => { console.error('Browser server failed to start'); process.exit(1); });
