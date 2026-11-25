const $ = (selector) => document.querySelector(selector);
const state = {scenario: null, index: 0, timer: null, live: false, liveTimer: null, demoTimer: null, demoStatus: null, symbol: 'EMU'};
const money = (value) => `$${Number(value).toFixed(2)}`;
const quotePrice = (value) => value == null ? '—' : money(value);
const usdQuote = new Intl.NumberFormat('en-US', {
  style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 8,
});
const realPrice = (value) => value == null ? '—' : usdQuote.format(Number(value));
const agentById = (id) => state.scenario.agents.find((agent) => agent.id === id);
const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (char) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[char]));

async function loadScenario() {
  state.live = new URLSearchParams(location.search).get('live') === '1';
  if (state.live) {
    state.symbol = new URLSearchParams(location.search).get('symbol') || 'EMU';
    if (!/^[A-Za-z0-9._-]{1,16}$/.test(state.symbol)) throw new Error('Invalid market symbol');
    document.body.classList.add('live-mode');
    $('.demo-chip').textContent = 'LIVE STOCK SERVICE';
    $('.demo-notice').innerHTML = '<span class="notice-icon">i</span><span><strong>Live market.</strong> Real prices come from the external data feed. Orders, fills, and holdings belong to the simulation.</span><button id="notice-dismiss" aria-label="Dismiss notice">×</button>';
    $('.scenario-picker').innerHTML = '<label>LIVE MARKET</label><span style="font-weight:600;font-size:12px;color:#41495a"></span>';
    $('.scenario-picker span').textContent = `${state.symbol} · USD`;
    $('.book-symbol').innerHTML = `<span class="book-pulse"></span>${state.symbol} <span class="tiny-separator">·</span> LIMIT ORDERS`;
    $('.trades-card .tape-live')?.replaceChildren(document.createTextNode('VIRTUAL'));
    $('.order-card .book-mid span:nth-child(2)').textContent = 'LAST VIRTUAL TRADE';
    $('#volume-label').textContent = 'VIRTUAL VOLUME';
    $('.book-foot span:last-child').innerHTML = 'VIRTUAL ORDER BOOK <i class="feed-dot"></i>';
    $('.timeline-controls').hidden = true;
    $('.activity-section .section-kicker').textContent = 'LIVE MARKET STATE';
    $('.activity-section h2').textContent = 'Current market state';
    $('#price-change').hidden = true;
    await updateDemoStatus().catch(showError);
    await loadLiveMarket();
    state.liveTimer = setInterval(() => loadLiveMarket().catch(showError), 2000);
    state.demoTimer = setInterval(() => updateDemoStatus().catch(showError), 1200);
    return;
  }
  const response = await fetch('/api/v1/demo/scenario');
  if (!response.ok) throw new Error('Could not load the demo scenario');
  state.scenario = await response.json();
  state.index = 0;
  render();
}

async function loadLiveMarket() {
  const response = await fetch(`/api/v1/market/${encodeURIComponent(state.symbol)}`, {cache: 'no-store'});
  if (!response.ok) throw new Error('Could not load the live Stock Service market');
  const market = await response.json();
  const accounts = new Map();
  for (const participant of state.demoStatus?.participants || []) {
    accounts.set(participant.account_id, {
      id: participant.account_id, name: participant.name, shares: participant.shares || 0,
      bankBalance: participant.bank_balance, stockCash: participant.stock_cash,
      stockCashAvailable: participant.stock_cash_available,
    });
  }
  for (const position of market.positions) {
    accounts.set(position.account_id, {...accounts.get(position.account_id), id: position.account_id,
      name: position.agent, shares: position.quantity});
  }
  for (const order of market.orders) {
    if (!accounts.has(order.account_id)) accounts.set(order.account_id, {id: order.account_id, name: order.agent, shares: 0});
  }
  const fills = market.fills.slice().reverse().map((fill) => ({
    time: new Date(fill.executed_at).toLocaleTimeString(), price: Number(fill.price), quantity: fill.quantity,
  }));
  const events = [{
    time: new Date().toLocaleTimeString(), type: 'market', actor: null,
    title: 'Live order and ownership state',
    detail: `${market.orders.length} open orders · ${fills.length} recent fills`,
    book: {
      asks: market.orders.filter((order) => order.side === 'SELL').map((order, sequence) => ({
        agent: order.account_id, price: Number(order.price), quantity: order.quantity, sequence,
      })),
      bids: market.orders.filter((order) => order.side === 'BUY').map((order, sequence) => ({
        agent: order.account_id, price: Number(order.price), quantity: order.quantity, sequence,
      })),
    },
    agents: Object.fromEntries([...accounts].map(([id, agent]) => [id, {shares: agent.shares}])),
    trades: fills,
    price: market.virtual_quote?.last_trade_price,
    realQuote: market.quote,
  }];
  state.scenario = {
    company: `${market.symbol} Agent Market`, symbol: market.symbol,
    agents: [...accounts.values()].map((agent, index) => ({...agent, color: ['#7569db', '#2c9a76', '#e38b56'][index % 3]})),
    events,
  };
  state.index = 0;
  render();
}

function showError(error) {
  const paragraph = document.createElement('p');
  paragraph.className = 'event-detail';
  paragraph.textContent = error.message;
  $('#event-list').replaceChildren(paragraph);
}

function currentEvent() { return state.scenario.events[state.index]; }

function renderChart() {
  const chart = $('#price-chart');
  const trades = state.scenario.events.slice(0, state.index + 1).flatMap((event) => event.trades || []);
  const values = trades.map((trade) => trade.price);
  if (!state.live) values.unshift(state.scenario.initial_price);
  $('.chart-label').textContent = state.live
    ? (values.length ? 'VIRTUAL TRADE PRICES' : 'NO VIRTUAL TRADES YET')
    : (values.length ? 'TRADE PRICE' : 'NO TRADES YET');
  if (!values.length) {
    chart.replaceChildren();
    return;
  }
  const width = 760, height = 112, top = 20, bottom = 96;
  const low = Math.min(...values) - 1, high = Math.max(...values) + 1;
  const points = values.map((value, index) => {
    const x = values.length === 1 ? 40 : 40 + index * (width - 60) / (values.length - 1);
    const y = bottom - ((value - low) / (high - low || 1)) * (bottom - top);
    return [x, y];
  });
  const path = points.map(([x, y], index) => `${index ? 'L' : 'M'} ${x} ${y}`).join(' ');
  const end = points.at(-1);
  chart.innerHTML = `<defs><linearGradient id="chartFill" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stop-color="#7569db" stop-opacity=".17"/><stop offset="100%" stop-color="#7569db" stop-opacity="0"/></linearGradient></defs>
    <line class="chart-grid" x1="0" y1="29" x2="760" y2="29"/><line class="chart-grid" x1="0" y1="63" x2="760" y2="63"/><line class="chart-grid" x1="0" y1="96" x2="760" y2="96"/>
    <path class="chart-area" d="${path} L ${end[0]} 102 L ${points[0][0]} 102 Z"/><path class="chart-line" d="${path}"/><circle class="chart-point" cx="${end[0]}" cy="${end[1]}" r="4"/>`;
}

function renderBook(event) {
  const asks = [...event.book.asks].sort((a, b) => a.price - b.price || a.sequence - b.sequence);
  const bids = [...event.book.bids].sort((a, b) => b.price - a.price || a.sequence - b.sequence);
  const maxQty = Math.max(1, ...asks.map((o) => o.quantity), ...bids.map((o) => o.quantity));
  const row = (order, side) => {
    const agent = agentById(order.agent);
    const depth = Math.max(15, order.quantity / maxQty * 84);
    return `<div class="book-row ${side === 'SELL' ? 'sell-row' : 'buy-row'}" style="--depth:${depth}%;--depth-color:${side === 'SELL' ? '#ffe4e7' : '#dff5ee'}"><span class="book-price">${money(order.price)}</span><span class="book-qty">${order.quantity}</span><span class="book-agent">${escapeHtml(agent?.name || 'Agent')}</span></div>`;
  };
  $('#asks-list').classList.toggle('empty-book', !asks.length);
  $('#bids-list').classList.toggle('empty-book', !bids.length);
  $('#asks-list').innerHTML = asks.length ? asks.map((o) => row(o, 'SELL')).join('') : '<div class="empty-order">No open sell orders</div>';
  $('#bids-list').innerHTML = bids.length ? bids.map((o) => row(o, 'BUY')).join('') : '<div class="empty-order">No open buy orders</div>';
  $('#ask-count').textContent = `${asks.length} ${asks.length === 1 ? 'order' : 'orders'}`;
  $('#bid-count').textContent = `${bids.length} ${bids.length === 1 ? 'order' : 'orders'}`;
  if (!state.live) {
    const ask = asks[0]?.price;
    const bid = bids[0]?.price;
    $('#best-ask').textContent = quotePrice(ask);
    $('#best-bid').textContent = quotePrice(bid);
    $('#spread').textContent = ask != null && bid != null ? money(ask - bid) : '—';
  }
  $('#book-mid-price').textContent = quotePrice(event.price);
}

function renderAgents(event) {
  const total = state.scenario.agents.reduce((sum, agent) => sum + event.agents[agent.id].shares, 0);
  $('#total-shares').textContent = total.toLocaleString();
  $('#agent-count').textContent = String(state.scenario.agents.length).padStart(2, '0');
  $('#agent-list').innerHTML = state.scenario.agents.map((agent) => {
    const portfolio = event.agents[agent.id];
    const width = total ? portfolio.shares / total * 100 : 0;
    const initials = escapeHtml(agent.name.slice(0, 1));
    const className = agent.id.replace('agent-', '');
    const balances = agent.bankBalance === undefined ? '' : `<div class="agent-finances">Bank ${money(agent.bankBalance)} <span>·</span> Stock ${money(agent.stockCash)} <span>(available ${money(agent.stockCashAvailable)})</span></div>`;
    return `<div class="agent-row"><div class="agent-avatar ${className}">${initials}</div><div><div class="agent-name">${escapeHtml(agent.name)}</div><div class="agent-id">${escapeHtml(agent.id)}</div>${balances}</div><div class="agent-amount"><strong>${portfolio.shares}</strong><small> shares</small></div></div><div class="holding-bar"><span style="width:${width}%;background:${agent.color}"></span></div>`;
  }).join('');
  $('#ownership-legend').innerHTML = state.scenario.agents.map((agent) => `<span><i class="legend-dot" style="background:${agent.color}"></i>${escapeHtml(agent.name)}</span>`).join('');
}

function renderTrades(event) {
  const trades = event.trades || [];
  const visible = trades.slice().reverse();
  $('#trade-list').innerHTML = visible.length ? visible.map((trade) => `<div class="trade-row"><span>${trade.time}</span><span>${money(trade.price)}</span><span>${trade.quantity}</span></div>`).join('') : `<div class="empty-trades">No trades yet.${state.live ? '' : '<br>Step through the scenario to see the fill.'}</div>`;
  $('#trade-count').textContent = String(trades.length).padStart(2, '0');
  $('#volume').innerHTML = `${trades.reduce((sum, trade) => sum + trade.quantity, 0)} <small>shares</small>`;
}

function renderTimeline() {
  const events = state.scenario.events;
  $('#event-list').innerHTML = events.map((event, index) => {
    const actor = event.actor ? agentById(event.actor).name : 'MARKET';
    const kind = event.type === 'matched' ? 'trade' : '';
    const label = event.type === 'matched' ? 'TRADE FILLED' : event.type === 'order_placed' ? 'ORDER' : 'MARKET';
    const className = index < state.index ? 'past' : index === state.index ? 'active' : '';
    return `<div class="event-item ${className}"><div class="event-node"></div><div class="event-time">${event.time} <span>· ${actor.toUpperCase()}</span></div><div class="event-title">${event.title}</div><div class="event-detail">${event.detail}</div><span class="event-tag ${kind}">${label}</span></div>`;
  }).join('');
  $('#step-label').textContent = `EVENT ${state.index + 1} OF ${events.length}`;
  $('#progress-fill').style.width = `${(state.index + 1) / events.length * 100}%`;
}

function renderRealQuote(quote) {
  $('#quote-price-label').textContent = 'LATEST REAL TRADE';
  $('#last-price').textContent = realPrice(quote.last_trade_price);
  $('#best-bid').textContent = realPrice(quote.best_bid);
  $('#best-ask').textContent = realPrice(quote.best_ask);
  $('#spread').textContent = realPrice(quote.spread);
  const source = $('#quote-source');
  source.hidden = false;
  if (quote.trade_status === 'not_configured') {
    source.textContent = 'Real market data is not configured for this instrument.';
    return;
  }
  const describe = (status, timestamp) => {
    if (!timestamp || status === 'unavailable') return 'unavailable';
    const time = new Date(timestamp).toLocaleString();
    return status === 'stale' ? `${time} (stale)` : time;
  };
  const checkedAt = quote.checked_at ? new Date(quote.checked_at).toLocaleString() : 'unavailable';
  source.textContent = `${quote.provider_symbol} · ${quote.source} · Last trade ${describe(quote.trade_status, quote.last_trade_at)} · Bid/ask ${describe(quote.quote_status, quote.quoted_at)} · Feed checked ${checkedAt}`;
}

function render() {
  const event = currentEvent();
  $('#company-name').textContent = state.scenario.company;
  $('#ticker').textContent = state.scenario.symbol;
  if (state.live) renderRealQuote(event.realQuote);
  else $('#last-price').textContent = quotePrice(event.price);
  $('#market-clock').textContent = event.time;
  if (!state.live) {
    $('#price-change').innerHTML = event.trades?.length ? '<span class="change-arrow">↗</span><span>0.00%</span><small>SCENARIO FILL</small>' : '<span class="change-arrow">↗</span><span>—</span><small>NO CHANGE</small>';
  }
  renderChart(); renderBook(event); renderAgents(event); renderTrades(event); renderTimeline();
}

function stopPlayback() {
  if (state.timer) clearInterval(state.timer);
  state.timer = null;
  $('#play-label').textContent = 'Play scenario';
  $('.play-icon').textContent = '▶';
}

function step(direction) {
  stopPlayback();
  state.index = Math.max(0, Math.min(state.scenario.events.length - 1, state.index + direction));
  render();
}

function play() {
  if (state.timer) { stopPlayback(); return; }
  if (state.index === state.scenario.events.length - 1) state.index = 0;
  $('#play-label').textContent = 'Pause';
  $('.play-icon').textContent = 'Ⅱ';
  render();
  state.timer = setInterval(() => {
    if (state.index >= state.scenario.events.length - 1) { stopPlayback(); return; }
    state.index += 1; render();
  }, 1500);
}

$('#reset-button').addEventListener('click', () => { stopPlayback(); state.index = 0; render(); });
$('#previous-button').addEventListener('click', () => step(-1));
$('#next-button').addEventListener('click', () => step(1));
$('#play-button').addEventListener('click', play);
$('#notice-dismiss').addEventListener('click', () => $('.demo-notice').remove());
$('#start-actions-button').addEventListener('click', startAgentActions);
document.addEventListener('keydown', (event) => { if (event.code === 'Space' && !['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement.tagName)) { event.preventDefault(); play(); } });

async function updateDemoStatus() {
  const response = await fetch('/api/v1/demo/status', {cache: 'no-store'});
  if (response.status === 404) return;
  const status = await response.json();
  if (!response.ok) throw new Error(status.detail || status.error || 'Could not read agent status');
  state.demoStatus = status;
  $('#agent-control').hidden = false;
  const button = $('#start-actions-button');
  const label = $('#agent-control-status');
  if (status.completed) {
    button.textContent = 'Actions completed';
    label.textContent = status.message;
  } else if (status.started && status.phase === 'failed') {
    button.textContent = 'Retry agent sequence';
    label.textContent = status.error || status.message;
  } else if (status.started) {
    button.textContent = 'Agents acting…';
    label.textContent = status.phase === 'failed' ? (status.error || status.message) : status.message;
  } else if (!status.ready) {
    button.textContent = 'Preparing agents…';
    label.textContent = status.error || status.message;
  } else if (!status.model_configured) {
    button.textContent = 'LLM configuration required';
    label.textContent = 'Add LLM_API_KEY and LLM_MODEL to examples/H24_stock_market/.env, then restart the demo runner.';
  } else {
    button.textContent = 'Start agent actions';
    label.textContent = status.message;
  }
  button.disabled = !status.can_start;
  const list = $('#agent-action-events');
  list.replaceChildren(...(status.events || []).map((item) => {
    const row = document.createElement('li');
    row.textContent = `${item.time} · ${item.message}`;
    return row;
  }));
}

async function startAgentActions() {
  const button = $('#start-actions-button');
  button.disabled = true;
  button.textContent = 'Starting…';
  try {
    const response = await fetch('/api/v1/demo/start', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || result.detail || 'Could not start agent actions');
    await updateDemoStatus();
  } catch (error) {
    $('#agent-control-status').textContent = error.message;
    button.textContent = 'Start agent actions';
    button.disabled = false;
  }
}

loadScenario().catch(showError);
