const $ = id => document.getElementById(id);
const labels = {running:'Thinking or acting',calling_tool:'Calling tool',waiting:'Waiting for services',starting:'Starting',paused:'Between rounds',resting:'Resting',recovering:'Retrying later',container_paused:'Container paused',completed:'Stopped normally',failed:'Failed',stopped:'Stopped',not_started:'Not started',unavailable:'Unavailable',unknown:'Unknown',suspended:'Paused',success:'Success',error:'Error',denied:'Denied',interrupted:'Interrupted'};
let state = {agents:[]}, selectedAgent = null, selectedCall = null, filterNames = '', filterTools = '';
function node(tag, cls, text) { const el = document.createElement(tag); if (cls) el.className = cls; if (text !== undefined) el.textContent = text; return el; }
function title(identity) { return state.agents.find(agent=>agent.name===identity)?.display_name || identity || '—'; }
function badge(status, call=false) { return node('span','status '+status,call&&status==='running'?'Running':labels[status]||status); }
function clock(value) { if (!value) return 'Not recorded'; const date = new Date(value); return Number.isNaN(date.getTime()) ? 'Not recorded' : date.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}); }
function duration(call) { if (call.duration_ms !== undefined && call.duration_ms !== null) return call.duration_ms < 1000 ? call.duration_ms+' ms' : (call.duration_ms/1000).toFixed(1)+' s'; if (call.status==='running' && call.timestamp) return Math.max(0,(Date.now()-Date.parse(call.timestamp))/1000).toFixed(1)+' s'; return '—'; }
function allCalls() { return state.agents.flatMap(agent => agent.calls.map((call,index)=>({...call,agent:agent.name,key:agent.name+':'+(agent.run_id||'legacy')+':'+call.id,order:index}))).sort((a,b)=> a.timestamp && b.timestamp ? b.timestamp.localeCompare(a.timestamp) : a.timestamp ? -1 : b.timestamp ? 1 : b.order-a.order); }
function renderCards() {
  $('agents').replaceChildren(...state.agents.map(agent=>{
    const card=node('button','agent'+(agent.name===selectedAgent?' selected':'')); card.type='button'; card.setAttribute('aria-pressed',String(agent.name===selectedAgent)); card.dataset.agent=agent.name;
    card.title='Person ID: '+agent.name;
    const top=node('div','agent-top'); top.append(node('span','avatar',title(agent.name)[0].toUpperCase()));
    const identity=node('div'); const asn=agent.service.match(/^hnode_(\d+)_/); identity.append(node('span','agent-name',title(agent.name)),node('span','agent-address',agent.address||(asn?'AS '+asn[1]:'Address pending'))); top.append(identity);
    const tool=node('div','current-tool',agent.active_tools.length ? agent.active_tools.map(call=>call.tool).join(' · ') : 'No active tool');
    if (!agent.active_tools.length && agent.calls.length) tool.title='Latest: '+agent.calls[agent.calls.length-1].tool;
    const footer=node('div','agent-footer'); const count=node('span'); count.append(node('b','',String(agent.tool_count)),' calls'); footer.append(count,node('span','',agent.cycle ? 'Moment '+agent.cycle : agent.round ? 'Round '+agent.round : 'Awaiting life'));
    card.append(top,badge(agent.status),tool,node('p','agent-task',agent.intention||agent.description||agent.task),footer);
    card.addEventListener('click',()=>{selectedAgent=agent.name;selectedCall=null;$('agent-filter').value=agent.name;render();}); return card;
  }));
}
function renderCalls() {
  const calls=allCalls(); $('call-count').textContent=calls.length+' calls';
  const tools=[...new Set(calls.map(call=>call.tool))].sort();
  if(tools.join(',')!==filterTools){const old=$('tool-filter').value;$('tool-filter').replaceChildren(new Option('All tools',''),...tools.map(tool=>new Option(tool,tool)));$('tool-filter').value=old;filterTools=tools.join(',');}
  const visible=calls.filter(call=>(!$('agent-filter').value||call.agent===$('agent-filter').value)&&(!$('tool-filter').value||call.tool===$('tool-filter').value)&&(!$('errors-only').checked||['error','denied','interrupted'].includes(call.status))).slice(0,150);
  $('empty-calls').classList.toggle('hidden',visible.length>0);
  if (!visible.length) { $('empty-calls').querySelector('strong').textContent=calls.length ? 'No matching calls' : 'No tool calls yet'; }
  $('calls').replaceChildren(...visible.map(call=>{
    const row=node('tr',call.key===selectedCall?'selected':''); row.tabIndex=0;
    row.append(node('td','time',clock(call.timestamp)),node('td','',title(call.agent)),node('td','mono',call.tool),node('td',''),node('td','number mono',duration(call))); row.children[3].append(badge(call.status,true));
    const choose=()=>{selectedCall=call.key;renderCalls();}; row.addEventListener('click',choose);row.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();choose();}}); return row;
  }));
  const chosen=calls.find(call=>call.key===selectedCall);
  if (chosen) {
    const {key,order,arguments:parameters,result,...detail}=chosen;
    $('call-arguments').textContent=JSON.stringify(parameters??{},null,2);
    $('call-result').textContent=result===undefined ? 'No result recorded yet.' : JSON.stringify(result,null,2);
    $('call-detail').textContent=JSON.stringify(detail,null,2);
  } else {
    $('call-arguments').textContent='Select a call to inspect every business parameter.';
    $('call-result').textContent='Full observations appear here. Authentication secrets are hidden.';
    $('call-detail').textContent='Timing, source and errors appear here.';
  }
  renderMail(chosen);
}
function renderMail(call) {
  const panel=$('mail-preview');panel.replaceChildren();
  let messages=[];
  if(call?.tool==='email.send')messages=[{from:call.result?.sender||title(call.agent),to:call.arguments?.recipient,subject:call.arguments?.subject,body:call.arguments?.body}];
  if(call?.tool==='email.inbox'&&Array.isArray(call.result))messages=call.result;
  panel.classList.toggle('hidden',!messages.length);
  for(const message of messages){
    const article=node('article','mail-message');article.append(node('h3','',message.subject||'(No subject)'));
    article.append(node('div','mail-meta','From: '+(message.from||'Unknown')+' · To: '+(message.to||title(call.agent))));
    if(message.inReplyTo)article.append(node('div','mail-meta','In reply to: '+message.inReplyTo));
    const hidden=message.body===undefined||message.body==='[redacted]';
    article.append(node('pre','mail-body',hidden?'This event did not record a mail body.':String(message.body)));
    panel.append(article);
  }
}
function renderDetails() {
  const agent=state.agents.find(agent=>agent.name===selectedAgent); if (!agent) return;
  $('detail-name').textContent=title(agent.name); const status=badge(agent.status); status.id='detail-status'; $('detail-status').replaceWith(status);
  $('detail-meta').textContent=['Person '+agent.name,agent.address||'Address not available',agent.run_id?'Run '+agent.run_id.slice(0,12):agent.events.length?'Legacy logs':'No run recorded',agent.last_update?'Last event '+clock(agent.last_update):'No timestamped event'].join(' · ');
  $('detail-background').textContent=agent.description||agent.task||'No resident background configured.';
  $('detail-intention').textContent=agent.intention||'Intentions are retained in the framework conversation.';
  $('detail-rest').textContent=agent.wake_at ? (agent.rest_reason||'Resting')+' · next wake '+clock(agent.wake_at) : agent.mode==='resident' ? 'Chooses what to do and when to return.' : 'Earlier task-based image.';
  $('permission-count').textContent='('+agent.tools.length+')'; $('permissions').replaceChildren(...agent.tools.map(tool=>node('span','permission',tool)));
  $('reply').textContent=agent.reply ? typeof agent.reply==='string' ? agent.reply : JSON.stringify(agent.reply,null,2) : 'No reflection yet.';
  $('agent-error').classList.toggle('hidden',!agent.error); $('agent-error').textContent=agent.error||'';
  const events=agent.events.filter(event=>!['tool_started','tool_finished','tool_failed','tool'].includes(event.event)).slice(-12).reverse();
  $('events').replaceChildren(...events.map(event=>{
    const item=node('div','event'); const kind=event.event||event.status||(event.error?'error':'message');
    let label=kind.replaceAll('_',' '); if(event.cycle)label+=' · moment '+event.cycle; else if(event.round)label+=' · round '+event.round; if(event.services?.length)label+=' · '+event.services.join(', '); if(event.seconds!==undefined)label+=' · '+event.seconds+' s';
    item.append(node('div','event-label',label),node('div','event-time',clock(event.timestamp))); return item;
  }));
  if (!events.length) $('events').append(node('p','task','Execution events will appear here.'));
}
function renderSales() {
  const sales=state.agents.flatMap(agent=>(agent.sales||[]).map(sale=>({...sale,agent:agent.name})));
  $('sale-count').textContent=sales.length+' sales';
  $('sales').replaceChildren(...sales.map(sale=>{
    const row=node('div','sale-row');
    row.append(node('strong','',sale.title||sale.product),node('span','',sale.buyer+' → '+title(sale.agent)),node('span','mono',(sale.amountMinor/100).toFixed(2)+' '+sale.currency),node('span','mono',sale.transfer));
    return row;
  }));
  if(!sales.length)$('sales').append(node('p','sales-empty','No verified sales yet. Residents decide whether to buy; only confirmed payments and deliveries appear here.'));
}
function render() {
  if (!state.agents.some(agent=>agent.name===selectedAgent)) selectedAgent=state.agents[0]?.name;
  $('nav-count').textContent=String(state.agents.length);
  $('stat-working').textContent=state.agents.filter(a=>['running','calling_tool'].includes(a.status)).length;
  $('stat-waiting').textContent=state.agents.filter(a=>['starting','waiting','paused','resting','recovering'].includes(a.status)).length;
  $('stat-completed').textContent=state.agents.filter(a=>['completed','failed','stopped','not_started'].includes(a.status)).length;
  $('stat-failures').textContent=state.agents.reduce((sum,a)=>sum+a.failure_count,0);
  const names=state.agents.map(a=>a.name+':'+a.display_name).join(','); if(names!==filterNames){const old=$('agent-filter').value;$('agent-filter').replaceChildren(new Option('All agents',''),...state.agents.map(a=>new Option(title(a.name),a.name)));$('agent-filter').value=old;filterNames=names;}
  const fresh=state.updated&&Date.now()-Date.parse(state.updated)<20000&&!state.error;
  $('connection').textContent=state.error?'Observation unavailable':fresh?'Live observation':state.updated?'Observation delayed':'Connecting';
  $('live-indicator').className='live-indicator '+(fresh?'live':state.error?'offline':'');
  $('updated').textContent=state.updated?'Updated '+clock(state.updated):'Waiting for an observation';
  $('error-banner').classList.toggle('hidden',!state.error);$('error-banner').textContent=state.error||'';
  $('legacy-banner').classList.toggle('hidden',!state.agents.some(a=>a.events.length&&!a.detailed_events));
  renderCards();renderCalls();renderDetails();renderSales();
}
for(const id of ['agent-filter','tool-filter','errors-only'])$(id).addEventListener('change',()=>{selectedCall=null;renderCalls();});
async function refresh() {
  try { const response=await fetch('/api/state',{signal:AbortSignal.timeout(12000)});if(!response.ok)throw new Error('Dashboard returned HTTP '+response.status);state=await response.json();render(); }
  catch(error) { $('connection').textContent='Dashboard disconnected';$('live-indicator').className='live-indicator offline';$('error-banner').textContent=String(error);$('error-banner').classList.remove('hidden'); }
  finally { setTimeout(refresh,2000); }
}
refresh();
