const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num = (value, digits=2) => Number(value).toLocaleString('ru-RU',{maximumFractionDigits:digits,minimumFractionDigits:digits});
const money = (value, currency='rub') => `${num(value)} ${currency.toLowerCase()==='rub'?'₽':esc(currency.toUpperCase())}`;
const time = value => new Date(value).toLocaleTimeString('ru-RU');
const sign = value => Number(value) < 0 ? 'negative' : 'positive';
let snapshot = null, selected = null, historyVersion = 0, historyBusy = false, lastHistory = 0;
$('today').textContent = new Date().toLocaleDateString('ru-RU',{day:'numeric',month:'long',year:'numeric'});
async function api(path, options){const response=await fetch(path, options);if(!response.ok)throw Error(`Ошибка сервера (${response.status})`);return response.json();}
function quotes(){
  if(!snapshot)return;
  const query=$('search').value.trim().toLowerCase();
  const items=snapshot.quotes.filter(q=>`${q.instrument.ticker} ${q.instrument.name}`.toLowerCase().includes(query));
  $('quotes').innerHTML=items.map(q=>`<button class="quote ${q.instrument.figi===selected?'selected':''}" data-figi="${esc(q.instrument.figi)}" aria-pressed="${q.instrument.figi===selected}"><span><b>${esc(q.instrument.ticker)}</b><small>${esc(q.instrument.name)}</small></span><span class="quote-price">${money(q.price,q.instrument.currency)}<small>${esc(time(q.time))}</small></span></button>`).join('')||'<p class="empty">Инструменты не найдены</p>';
  $('quotes').querySelectorAll('button').forEach(button=>button.onclick=()=>select(button.dataset.figi));
}
function select(figi){
  selected=figi; historyVersion++; lastHistory=0; historyBusy=false; quotes();
  const quote=snapshot?.quotes.find(q=>q.instrument.figi===figi);
  $('chart-title').textContent=quote?`${quote.instrument.ticker} · ${quote.instrument.name}`:figi;
  $('chart-price').textContent=quote?`${num(quote.price)} ${quote.instrument.currency.toUpperCase()}`:'—';
  $('chart').innerHTML='<p class="empty">Загрузка истории…</p>';
  loadHistory(false);
}
function chart(points){
  if(!points.length){$('chart').innerHTML='<p class="empty">За последние 24 часа нет завершённых свечей</p>';return;}
  const values=points.map(p=>Number(p[1]));const lo=Math.min(...values),hi=Math.max(...values),span=hi-lo||Math.max(1,hi*.01);
  const x=i=>8+i/Math.max(1,points.length-1)*590,y=v=>175-(v-lo)/span*150;
  const line=values.map((v,i)=>`${i?'L':'M'}${x(i).toFixed(2)},${y(v).toFixed(2)}`).join(' ');
  const labels=[0,1,2].map(i=>{const v=lo+span*i/2;return `<line x1="8" x2="600" y1="${y(v)}" y2="${y(v)}" stroke="#30353a" stroke-dasharray="3 5"/><text x="612" y="${y(v)+4}">${esc(num(v))}</text>`;}).join('');
  const stamp=i=>new Date(points[i][0]).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'});
  $('chart').innerHTML=`<svg viewBox="0 0 700 218" role="img" aria-label="График цены ${esc($('chart-title').textContent)}"><defs><linearGradient id="fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#f4cf57" stop-opacity=".20"/><stop offset="100%" stop-color="#f4cf57" stop-opacity="0"/></linearGradient></defs>${labels}<path d="${line} L${x(values.length-1)},190 L8,190 Z" fill="url(#fill)"/><path d="${line}" fill="none" stroke="#f4cf57" stroke-width="2.5" stroke-linejoin="round"/><circle cx="${x(values.length-1)}" cy="${y(values[values.length-1])}" r="3" fill="#f4cf57"/><text x="8" y="212">${stamp(0)}</text><text x="565" y="212">${stamp(points.length-1)}</text></svg>`;
}
async function loadHistory(refresh){
  if(!selected||historyBusy)return;historyBusy=true;lastHistory=Date.now();const version=historyVersion;
  try{const result=await api(`/api/history?figi=${encodeURIComponent(selected)}${refresh?'&refresh=1':''}`);if(version!==historyVersion)return;
    if(result.pending){setTimeout(()=>{if(version===historyVersion)loadHistory(false);},1500);return;}
    lastHistory=Date.now();if(result.error)$('chart').innerHTML=`<p class="empty">${esc(result.error)}</p>`;else chart(result.points);
  }catch(error){if(version===historyVersion){$('chart').innerHTML=`<p class="empty">${esc(error.message)}</p>`;lastHistory=Date.now();}}
  finally{if(version===historyVersion)historyBusy=false;}
}
function render(state){
  $('mode').textContent={demo:'Демонстрационный режим',readonly:'Т-Инвест · Только чтение',sandbox:'Т-Инвест · Песочница'}[state.mode];
  $('ticks').textContent=`${num(state.ticks,0)} событий`;
  $('status').textContent={loading:'Обновление…',ready:'Данные получены',error:'Нет соединения'}[state.status];
  $('status').className=state.status==='ready'?'positive':state.status==='error'?'negative':'';
  $('refresh').disabled=state.status==='loading';
  const latestError=[...state.logs].reverse().find(l=>l.level==='ERROR');
  const warnings=state.snapshot?.warnings||[];
  $('notice').hidden=state.status!=='error'&&!warnings.length&&state.mode!=='demo';
  $('notice').textContent=state.status==='error'?(latestError?.message?.includes('CERTIFICATE_VERIFY_FAILED')?'Не удалось проверить сертификат Т-Инвест. Необходимо настроить доверенный корневой сертификат на сервере.':latestError?.message||'Не удалось подключиться к брокеру.')+(state.snapshot?' Показаны последние полученные данные.':' Данные счёта ещё не получены.'):warnings.length?warnings.join(' · '):'Деморежим: цены и портфель смоделированы.';
  $('logs').innerHTML=[...state.logs].reverse().map(l=>`<div class="log"><time>${esc(time(l.time))}</time><span class="${l.level==='ERROR'?'negative':l.level==='WARN'?'':'positive'}">${esc(l.level)}</span><span>${esc(l.message)}</span></div>`).join('')||'<p class="empty">Нет событий</p>';
  if(!state.snapshot)return;snapshot=state.snapshot;
  $('account').textContent=snapshot.account;$('total').textContent=`${num(snapshot.total)} ₽`;$('cash').textContent=`${num(snapshot.currencies)} ₽`;
  $('returns').textContent=`${Number(snapshot.return_percent)>0?'+':''}${num(snapshot.return_percent)} %`;$('returns').className=sign(snapshot.return_percent);
  $('position-count').textContent=snapshot.positions.length;$('order-count').textContent=snapshot.orders.length;
  $('positions').innerHTML=snapshot.positions.map(p=>`<tr><td><b>${esc(p.instrument.ticker)}</b><small>${esc(p.instrument.name)}</small></td><td>${num(p.quantity,4).replace(/,?0+$/,'')} шт.</td><td>${money(p.average,p.instrument.currency)}</td><td>${money(p.current,p.instrument.currency)}</td><td class="${sign(p.pnl)}">${Number(p.pnl)>0?'+':''}${money(p.pnl,p.instrument.currency)}</td></tr>`).join('')||'<tr><td colspan="5" class="empty">В портфеле пока нет позиций</td></tr>';
  $('order-rows').innerHTML=snapshot.orders.map(o=>`<tr><td>${esc(o.ticker)}</td><td>${esc(o.side)}</td><td>${esc(o.lots)}</td><td>${esc(o.filled)}</td><td>${esc(o.status)}</td></tr>`).join('')||'<tr><td colspan="5" class="empty">Нет активных заявок</td></tr>';
  $('updated').textContent=`${state.status==='error'?'Последние данные':'Обновлено'}: ${time(snapshot.time)}`;quotes();
  if(!selected&&snapshot.quotes.length)select(snapshot.quotes[0].instrument.figi);
  if(selected){const q=snapshot.quotes.find(q=>q.instrument.figi===selected);if(q)$('chart-price').textContent=`${num(q.price)} ${q.instrument.currency.toUpperCase()}`;if(Date.now()-lastHistory>60000)loadHistory(true);}
}
async function poll(){try{render(await api('/api/state'));}catch(error){$('status').textContent='Сервер недоступен';$('notice').hidden=false;$('notice').textContent='Соединение с приложением прервано. Повторная попытка через 2 секунды.';$('refresh').disabled=false;}finally{setTimeout(poll,2000);}}
$('search').addEventListener('input',quotes);
$('refresh').onclick=async()=>{ $('refresh').disabled=true;try{await api('/api/refresh',{method:'POST',headers:{'X-PyVeighNa':'1'}});loadHistory(true);}catch(error){$('notice').hidden=false;$('notice').textContent=error.message;}finally{$('refresh').disabled=false;}};
poll();

if(document.modelContext?.registerTool){
  const lifecycle=new AbortController();
  try{Promise.resolve(document.modelContext.registerTool({
    name:'filter_watchlist',title:'Поиск инструмента',
    description:'Фильтрует видимый список котировок по тикеру или названию.',
    inputSchema:{type:'object',properties:{query:{type:'string',maxLength:100}},required:['query'],additionalProperties:false},
    annotations:{readOnlyHint:false,untrustedContentHint:true},
    execute(input){
      if(!input||typeof input.query!=='string'||input.query.length>100)throw Error('Укажите строку поиска до 100 символов');
      $('search').value=input.query;quotes();
      return {query:input.query,matches:snapshot?snapshot.quotes.filter(q=>`${q.instrument.ticker} ${q.instrument.name}`.toLowerCase().includes(input.query.trim().toLowerCase())).map(q=>q.instrument.ticker):[]};
    }
  },{signal:lifecycle.signal})).catch(()=>{});}catch{}
  window.addEventListener('pagehide',()=>lifecycle.abort(),{once:true});
}
