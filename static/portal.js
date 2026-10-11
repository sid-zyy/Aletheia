/* Notifications (bell + page) and the customer's portal additions: partial report and
   approved values (their test requests: request.js). */
(()=>{const s=document.createElement('style');s.textContent=`
.bell{position:relative;border:1px solid var(--ln);background:var(--cd);border-radius:12px;padding:7px 10px;cursor:pointer;display:inline-flex;align-items:center}
.bell i{position:absolute;top:-6px;right:-6px;background:var(--er);color:#fff;font-style:normal;font-size:11px;font-weight:700;border-radius:99px;padding:1px 6px;min-width:18px;text-align:center}
.bw{position:relative;display:inline-flex}.bdd{position:absolute;right:0;top:calc(100% + 8px);width:360px;max-width:calc(100vw - 32px);background:var(--cd);border:1px solid var(--ln);border-radius:16px;box-shadow:0 18px 40px -12px rgba(18,49,95,.35);z-index:30;overflow:hidden}
.bdh{display:flex;justify-content:space-between;align-items:center;padding:12px 16px;border-bottom:1px solid var(--ln)}.bda{display:block;text-align:center;padding:12px;border-top:1px solid var(--ln);font-weight:600;font-size:14px;color:var(--ac);text-decoration:none}.bda:hover{background:var(--cd2)}
.nr{display:grid;grid-template-columns:10px 1fr auto;gap:12px;align-items:start;width:100%;text-align:left;background:none;border:0;border-top:1px solid var(--ln);padding:14px 12px;cursor:pointer;font:inherit;color:var(--mu);border-radius:10px}
.adh+.nr,.bdh+.nr{border-top:0}.nr:hover{background:var(--cd2)}.nr .nd{width:8px;height:8px;border-radius:50%;margin-top:7px}.nr.un .nd{background:var(--ac)}.nr.un.act .nd{background:var(--er)}
.nr .nb{display:grid;gap:2px;min-width:0}.nr .nb b{font-size:14.5px;font-weight:600;color:var(--mu)}.nr.un .nb b{color:var(--tx);font-weight:700}.nr .nb>span{font-size:14px;overflow-wrap:anywhere}.nr.un .nb>span{color:var(--tx)}
.nr .nb em{font-style:normal;font-size:12px;font-weight:600;background:var(--ac2);color:var(--ac);border-radius:99px;padding:1px 8px;margin-left:6px}.nr small{font-size:12.5px;color:var(--mu)}.nr .nt2{font-size:12.5px;white-space:nowrap}.bdd .nr{border-radius:0;padding:12px 16px}
.nfo .nr.un .nb b{font-weight:600}.adh{font-size:13px;letter-spacing:.06em;text-transform:uppercase;color:var(--mu);margin:18px 0 4px}.card h2+.adh{margin-top:4px}
.tb2{display:grid;grid-template-columns:1.1fr 1fr 1.6fr auto;gap:14px;padding:14px 4px;border-top:1px solid var(--ln);align-items:start;font-size:14px}.tb2:first-of-type{border:0}
@media(max-width:900px){.tb2{grid-template-columns:1fr}}
.dotc{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px}.dotc.green{background:var(--ok)}.dotc.amber{background:#e08a00}.dotc.red{background:var(--er)}.dotc.none{background:var(--ln)}
.vt2{width:100%;border-collapse:collapse;font-size:13px;margin:6px 0 12px}.vt2 th,.vt2 td{border:1px solid var(--ln);padding:4px 7px;text-align:left}.vt2 th{background:var(--cd2);color:var(--mu);font-weight:600}
`;document.head.append(s)})();

/* ---------------------------------------------------------------- notifications */
let BELL_T=null,NF='unread';
const NKIND={assigned:'Test assigned to you',returned:'Returned for correction',uploaded:'Test to verify',signoff:'Ready for approval',approve:'Report ready for sign-off',form:'New test request',released:'Report released',progress:'Update',approved:'Test approved'};
const nTitle=n=>isCust()?T({returned:'Request returned to you',progress:'Request received',released:'Your test report is ready'}[n.kind]||'Notice'):NKIND[n.kind]||'Notice';
function bell(){return ME?`<span class="bw"><button class="bell" id="bellB" onclick="bellOpen(event)" title="${T('Notifications')}" aria-label="${T('Notifications')}" aria-haspopup="true" aria-expanded="false"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M6 8a6 6 0 1112 0c0 7 3 8 3 8H3s3-1 3-8"/><path d="M10 20a2 2 0 004 0"/></svg><i id="bellN" style="display:none"></i></button><div class="bdd" id="bdd" hidden></div></span>`:''}
async function bellCount(){if(!ME)return;try{const r=await(await fetch('/api/notifications?unread=1&limit=1',{cache:'no-store'})).json(),e=$('#bellN');if(e){e.textContent=r.unread>99?'99+':r.unread;e.style.display=r.unread?'':'none'}}catch(e){}
 clearTimeout(BELL_T);BELL_T=setTimeout(bellCount,60000)}
/* open the page a notification is about, marking it read first */
async function nOpen(id,target){try{await api('/api/notifications/read',{ids:[id]})}catch(e){}bellCount();const d=$('#bdd');if(d)d.hidden=true;if(target){const h='#/'+target;if(location.hash==h)route();else location.hash=h}else if(location.hash.startsWith('#/notifications'))notificationsPage()}
const nWhen=t=>{const d=t.slice(0,10),now=new Date(Date.now()-new Date().getTimezoneOffset()*6e4).toISOString().slice(0,10);return d==now?t.slice(11,16):new Date(d+'T12:00').toLocaleDateString(LOC(),{day:'numeric',month:'short'})+' '+t.slice(11,16)};
const nRow=n=>`<button class="nr ${n.read_at?'':'un'} ${n.action?'act':''}" onclick='nOpen(${n.id},${JSON.stringify(n.target||'')})'><span class="nd" aria-hidden="true"></span><span class="nb"><b>${esc(nTitle(n))}${n.count>1?` <em>${T('{n} updates',{n:n.count})}</em>`:''}</b><span>${esc(TF(n.message))}</span>${n.series?`<small>${esc(n.series)}</small>`:''}</span><span class="nt2">${esc(nWhen(n.created_at))}</span></button>`;
async function bellOpen(e){e.stopPropagation();const d=$('#bdd'),b=$('#bellB');if(!d)return;if(!d.hidden){d.hidden=true;b.setAttribute('aria-expanded','false');return}
 d.hidden=false;b.setAttribute('aria-expanded','true');d.innerHTML=`<p class="note" style="padding:12px 16px;margin:0">${T('Loading…')}</p>`;
 try{const r=await api('/api/notifications?unread=1&limit=5');d.innerHTML=`<div class="bdh"><b>${T('Notifications')}</b><span class="note" style="margin:0">${T('{n} unread',{n:r.unread})}</span></div>${r.items.map(nRow).join('')||`<p class="note" style="padding:6px 16px 14px;margin:0">${T('Nothing unread.')}</p>`}<a class="bda" href="#/notifications">${T('View all notifications')}</a>`}catch(x){d.innerHTML=`<p class="note" style="padding:12px 16px">${esc([].concat(x).map(TF).join(' '))}</p>`}}
document.addEventListener('click',e=>{const d=$('#bdd');if(d&&!d.hidden&&!(e.target.closest&&e.target.closest('.bw')))d.hidden=true});
async function notificationsPage(){const r=await api('/api/notifications?limit=200'),items=r.items.filter(n=>NF=='all'||NF=='unread'&&!n.read_at||NF=='action'&&n.action&&!n.read_at);
 const lday=t=>new Date(t-new Date(t).getTimezoneOffset()*6e4).toISOString().slice(0,10),today=lday(Date.now()),yest=lday(Date.now()-864e5),bucket=n=>{const d=n.created_at.slice(0,10);return d==today?'Today':d==yest?'Yesterday':'Earlier'};
 const byDay=l=>['Today','Yesterday','Earlier'].map(b=>[b,l.filter(n=>bucket(n)==b)]).filter(([,x])=>x.length).map(([b,x])=>`<h3 class="adh">${T(b)}</h3>${x.map(nRow).join('')}`).join('');
 const act=items.filter(n=>n.action&&!n.read_at),info=items.filter(n=>!(n.action&&!n.read_at)),cnt=k=>r.items.filter(n=>k=='all'||!n.read_at&&(k=='unread'||n.action)).length;
 $('#app').innerHTML=head(T('Notifications'),T('{n} unread. Click a notification to open what it is about.',{n:r.unread}),r.unread?`<button class="btn g" onclick="api('/api/notifications/read',{all:true}).then(()=>{notificationsPage();bellCount()})">${T('Mark all as read')}</button>`:'')+
 `<div class="tabs">${[['unread','Unread'],['action','Needs action'],['all','All']].map(([k,l])=>`<button class="tab ${NF==k?'on':''}" onclick="NF='${k}';notificationsPage()">${T(l)}<i>${cnt(k)}</i></button>`).join('')}</div>
 ${act.length?`<div class="card"><h2>${T('Needs your action')}</h2>${byDay(act)}</div>`:''}
 ${info.length?`<div class="card nfo"><h2>${T(act.length?'For information':NF=='all'?'All notifications':'Unread')}</h2>${byDay(info)}</div>`:''}
 ${items.length?'':`<div class="card empty">${T(NF=='unread'?'Nothing unread.':NF=='action'?'Nothing needs your action.':'No notifications yet.')}</div>`}`;bellCount()}

/* ---------------------------------------------------------------- customer: approved values, partial report, request forms */
async function custExtras(id,j){const [vals,ps]=await Promise.all([api(`/api/jobs/${id}/approved-values`),api(`/api/jobs/${id}/partials`)]),el=document.createElement('div');
 const item=x=>x.columns?`<b style="font-size:13px">${esc(x.label)}</b><div class="scroll"><table class="vt2"><tr>${x.columns.map(c=>`<th>${esc(c)}</th>`).join('')}</tr>${x.rows.map(r=>`<tr>${r.map(v=>`<td>${v==null?'NA':esc(v)}</td>`).join('')}</tr>`).join('')}</table></div>`
  :`<div class="ps"><span>${esc(x.label)}</span><b>${x.value==null||x.value===''?'NA':esc(x.value)}</b></div>`;
 el.innerHTML=(ps.length?`<div class="card"><div class="wh"><h2 style="margin:0">${T('Partial report')}</h2><a class="btn" href="/api/jobs/${id}/partial.pdf?dl=1">${T('Download partial report (PDF)')}</a></div><p class="note">${T('Built from the approved tests only; marked PARTIAL, NOT FINAL. Version {v} of {at}, fingerprint',{v:ps[0].version,at:esc(ps[0].at.replace('T',' ').slice(0,16))})} <span class="hash">${esc(ps[0].sha256.slice(0,16))}&hellip;</span>${ps.length>1?`. ${T('Earlier:')} ${ps.slice(1).map(p=>`<a class="lk" style="padding:0 4px" href="/api/jobs/${id}/partial.pdf?v=${p.version}">v${p.version}</a>`).join('')}`:''}</p></div>`:'')+
  (vals.length?`<div class="card"><h2>${T('Approved values')}</h2>${vals.map(v=>`<details class="xs"><summary><b>${esc(T(v.name))}</b><span class="pst verified">${T('Approved')}</span></summary><div style="padding:8px 14px">${v.items.map(item).join('')}</div></details>`).join('')}</div>`:'');
 $('#app').append(el)}
