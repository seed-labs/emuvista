const $ = id => document.getElementById(id);
const labels = {running:'Working',calling_tool:'Calling tool',waiting:'Waiting for services',starting:'Starting',paused:'Between rounds',container_paused:'Container paused',completed:'Completed',failed:'Failed',stopped:'Stopped',not_started:'Not started',unavailable:'Unavailable',unknown:'Unknown',suspended:'Paused',success:'Success',error:'Error',denied:'Denied',interrupted:'Interrupted'};
let state = {agents:[]}, selectedAgent = null, selectedCall = null, filterNames = '';
function node(tag, cls, text) { const el = document.createElement(tag); if (cls) el.className = cls; if (text !== undefined) el.textContent = text; return el; }
function title(name) { return name ? name[0].toUpperCase()+name.slice(1) : '—'; }
function badge(status) { return node('span','status '+status,labels[status]||status); }
function clock(value) { if (!value) return 'Not recorded'; const date = new Date(value); return Number.isNaN(date.getTime()) ? 'Not recorded' : date.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}); }
function duration(call) { if (call.duration_ms !== undefined && call.duration_ms !== null) return call.duration_ms < 1000 ? call.duration_ms+' ms' : (call.duration_ms/1000).toFixed(1)+' s'; if (call.status==='running' && call.timestamp) return Math.max(0,(Date.now()-Date.parse(call.timestamp))/1000).toFixed(1)+' s'; return '—'; }
function allCalls() { return state.agents.flatMap(agent => agent.calls.map((call,index)=>({...call,agent:agent.name,key:agent.name+':'+(agent.run_id||'legacy')+':'+call.id,order:index}))).sort((a,b)=> a.timestamp && b.timestamp ? b.timestamp.localeCompare(a.timestamp) : a.timestamp ? -1 : b.timestamp ? 1 : b.order-a.order); }
function renderCards() {
  $('agents').replaceChildren(...state.agents.map(agent=>{
    const card=node('button','agent'+(agent.name===selectedAgent?' selected':'')); card.type='button'; card.setAttribute('aria-pressed',String(agent.name===selectedAgent)); card.dataset.agent=agent.name;
    const top=node('div','agent-top'); top.append(node('span','avatar',agent.name[0].toUpperCase()));
    const identity=node('div'); const asn=agent.service.match(/^hnode_(\d+)_/); identity.append(node('span','agent-name',title(agent.name)),node('span','agent-address',agent.address||(asn?'AS '+asn[1]:'Address pending'))); top.append(identity);
    const tool=node('div','current-tool',agent.active_tools.length ? agent.active_tools.map(call=>call.tool).join(' · ') : 'No active tool');
    if (!agent.active_tools.length && agent.calls.length) tool.title='Latest: '+agent.calls[agent.calls.length-1].tool;
    const footer=node('div','agent-footer'); const count=node('span'); count.append(node('b','',String(agent.tool_count)),' calls'); footer.append(count,node('span','',agent.round ? 'Round '+agent.round : 'Awaiting run'));
    card.append(top,badge(agent.status),tool,node('p','agent-task',agent.task),footer);
    card.addEventListener('click',()=>{selectedAgent=agent.name;render();}); return card;
  }));
}
function renderCalls() {
  const calls=allCalls(); $('call-count').textContent=calls.length+' calls';
  const visible=calls.filter(call=>(!$('agent-filter').value||call.agent===$('agent-filter').value)&&(!$('errors-only').checked||['error','denied','interrupted'].includes(call.status))).slice(0,150);
  $('empty-calls').classList.toggle('hidden',visible.length>0);
  if (!visible.length) { $('empty-calls').querySelector('strong').textContent=calls.length ? 'No matching calls' : 'No tool calls yet'; }
  $('calls').replaceChildren(...visible.map(call=>{
    const row=node('tr',call.key===selectedCall?'selected':''); row.tabIndex=0;
    row.append(node('td','time',clock(call.timestamp)),node('td','',title(call.agent)),node('td','mono',call.tool),node('td',''),node('td','number mono',duration(call))); row.children[3].append(badge(call.status));
    const choose=()=>{selectedCall=call.key;renderCalls();}; row.addEventListener('click',choose);row.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();choose();}}); return row;
  }));
  const chosen=calls.find(call=>call.key===selectedCall);
  if (chosen) { const {key,order,...detail}=chosen; $('call-detail').textContent=JSON.stringify(detail,null,2); }
  else $('call-detail').textContent='Arguments, outcome summaries and errors appear here. Mail bodies and credentials are omitted.';
}
function renderDetails() {
  const agent=state.agents.find(agent=>agent.name===selectedAgent); if (!agent) return;
  $('detail-name').textContent=title(agent.name); const status=badge(agent.status); status.id='detail-status'; $('detail-status').replaceWith(status);
  $('detail-meta').textContent=[agent.address||'Address not available',agent.run_id?'Run '+agent.run_id.slice(0,12):agent.events.length?'Legacy logs':'No run recorded',agent.last_update?'Last event '+clock(agent.last_update):'No timestamped event'].join(' · ');
  $('detail-task').textContent=agent.task||'No task configured.';
  $('permission-count').textContent='('+agent.tools.length+')'; $('permissions').replaceChildren(...agent.tools.map(tool=>node('span','permission',tool)));
  $('reply').textContent=agent.reply ? typeof agent.reply==='string' ? agent.reply : JSON.stringify(agent.reply,null,2) : 'No model reply yet.';
  $('agent-error').classList.toggle('hidden',!agent.error); $('agent-error').textContent=agent.error||'';
  const events=agent.events.filter(event=>!['tool_started','tool_finished','tool_failed','tool'].includes(event.event)).slice(-12).reverse();
  $('events').replaceChildren(...events.map(event=>{
    const item=node('div','event'); const kind=event.event||event.status||(event.error?'error':'message');
    let label=kind.replaceAll('_',' '); if(event.round)label+=' · round '+event.round; if(event.services?.length)label+=' · '+event.services.join(', '); if(event.seconds!==undefined)label+=' · '+event.seconds+' s';
    item.append(node('div','event-label',label),node('div','event-time',clock(event.timestamp))); return item;
  }));
  if (!events.length) $('events').append(node('p','task','Execution events will appear here.'));
}
function render() {
  if (!state.agents.some(agent=>agent.name===selectedAgent)) selectedAgent=state.agents[0]?.name;
  $('nav-count').textContent=String(state.agents.length);
  $('stat-working').textContent=state.agents.filter(a=>['running','calling_tool'].includes(a.status)).length;
  $('stat-waiting').textContent=state.agents.filter(a=>['starting','waiting','paused'].includes(a.status)).length;
  $('stat-completed').textContent=state.agents.filter(a=>a.status==='completed').length;
  $('stat-failures').textContent=state.agents.reduce((sum,a)=>sum+a.failure_count,0);
  const names=state.agents.map(a=>a.name).join(','); if(names!==filterNames){const old=$('agent-filter').value;$('agent-filter').replaceChildren(new Option('All agents',''),...state.agents.map(a=>new Option(title(a.name),a.name)));$('agent-filter').value=old;filterNames=names;}
  const fresh=state.updated&&Date.now()-Date.parse(state.updated)<20000&&!state.error;
  $('connection').textContent=state.error?'Observation unavailable':fresh?'Live observation':state.updated?'Observation delayed':'Connecting';
  $('live-indicator').className='live-indicator '+(fresh?'live':state.error?'offline':'');
  $('updated').textContent=state.updated?'Updated '+clock(state.updated):'Waiting for an observation';
  $('error-banner').classList.toggle('hidden',!state.error);$('error-banner').textContent=state.error||'';
  $('legacy-banner').classList.toggle('hidden',!state.agents.some(a=>a.events.length&&!a.detailed_events));
  renderCards();renderCalls();renderDetails();
}
$('agent-filter').addEventListener('change',renderCalls);$('errors-only').addEventListener('change',renderCalls);
async function refresh() {
  try { const response=await fetch('/api/state',{signal:AbortSignal.timeout(12000)});if(!response.ok)throw new Error('Dashboard returned HTTP '+response.status);state=await response.json();render(); }
  catch(error) { $('connection').textContent='Dashboard disconnected';$('live-indicator').className='live-indicator offline';$('error-banner').textContent=String(error);$('error-banner').classList.remove('hidden'); }
  finally { setTimeout(refresh,2000); }
}
refresh();
