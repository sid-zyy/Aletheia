/* User menu, the dashboard's "Your tasks", taking / assigning tests, (the customer's request form is in request.js),
   and the dashboard emblem. */
(()=>{const s=document.createElement('style');s.textContent=`
input.in,select{height:46px;box-sizing:border-box}
.fbar{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:14px;align-items:end}
.fbar>div{min-width:0;display:flex;flex-direction:column}.fbar label{margin:0 0 6px!important;font-size:13px;font-weight:600;color:var(--mu)}
.fbar .in,.fbar select,.fbar .btn{width:100%!important;min-width:0!important;max-width:100%;height:46px;margin:0}.fbar .btn{justify-content:center}
.um{position:relative}.umb{display:flex;align-items:center;gap:10px;border:1px solid var(--ln);background:var(--cd);border-radius:14px;padding:5px 10px 5px 5px;cursor:pointer;transition:box-shadow .15s}
.umb:hover,.umb[aria-expanded=true]{box-shadow:0 4px 14px -6px rgba(18,49,95,.35)}
.av{width:34px;height:34px;border-radius:10px;display:grid;place-items:center;color:#fff;font-weight:700;font-size:13px;letter-spacing:.02em;flex-shrink:0}
.av.lg{width:46px;height:46px;border-radius:13px;font-size:16px}
.umt{display:grid;text-align:left;line-height:1.2}.umt b{font-size:14px;white-space:nowrap;max-width:170px;overflow:hidden;text-overflow:ellipsis}.umt small{color:var(--mu);font-size:12px}
.ump{position:absolute;right:0;top:calc(100% + 8px);width:290px;background:var(--cd);border:1px solid var(--ln);border-radius:16px;box-shadow:0 18px 40px -12px rgba(18,49,95,.35);z-index:30;overflow:hidden}
.ump .uh{display:flex;gap:12px;align-items:center;padding:16px;background:var(--cd2);border-bottom:1px solid var(--ln)}.ump .uh div{min-width:0}.ump .uh b{display:block;font-size:15px}
.ump .uh small{display:block;color:var(--mu);font-size:12.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ump a,.ump button{display:flex;gap:10px;align-items:center;width:100%;padding:11px 16px;border:0;background:none;color:var(--tx);font:inherit;font-size:14px;text-align:left;cursor:pointer;text-decoration:none}
.ump a:hover,.ump button:hover{background:var(--cd2)}.ump .so{color:var(--er);border-top:1px solid var(--ln)}
@media(max-width:760px){.umt{display:none}.umb{padding:4px}}
.tasks{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px}
.tg{border:1px solid var(--ln);border-radius:14px;padding:14px 16px;background:var(--cd)}.tg h3{margin:0 0 8px;font-size:14.5px;display:flex;justify-content:space-between;gap:8px;align-items:center}
.tg h3 i{font-style:normal;font-size:12px;font-weight:700;border-radius:99px;padding:2px 9px;background:var(--ac2);color:var(--ac)}.tg.hot h3 i{background:var(--er2);color:var(--er)}
.ti{display:flex;justify-content:space-between;gap:8px;align-items:center;padding:7px 0;border-top:1px solid var(--ln);font-size:13.5px}.ti:first-of-type{border:0}
.hero svg.emb{position:absolute;right:clamp(8px,3vw,40px);top:50%;transform:translateY(-50%);width:min(34%,330px);height:auto;z-index:0}
@media(max-width:1100px){.hero svg.emb{opacity:.25;right:-40px}}
.ti a{color:var(--tx);text-decoration:none}.ti a:hover{color:var(--ac)}.ti small{display:block;color:var(--mu);font-size:12px}
`;document.head.append(s)})();

/* ---------------------------------------------------------------- user menu */
const ROLE_COL={admin:'#7c3aed',tester:'#1c4f9c',verifier:'#0f766e',approver:'#b45309',customer:'#be123c'};
const initials=n=>String(n||'?').replace(/^(dr|mr|mrs|ms|prof|sh|smt)\.?\s+/i,'').split(/[\s.]+/).filter(Boolean).slice(0,2).map(x=>x[0].toUpperCase()).join('')||'?';
function userChip(){if(!ME)return'';const c=ROLE_COL[ME.roles[0]]||'#1c4f9c',r=ME.roles.map(x=>ROLE_LBL[x]).join(', ');
 return `<div class="um"><button class="umb" id="umb" aria-haspopup="true" aria-expanded="false" onclick="umToggle(event)"><span class="av" style="background:${c}">${esc(initials(ME.full_name))}</span><span class="umt"><b>${esc(ME.full_name)}</b><small>${esc(r)}</small></span><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg></button>
 <div class="ump" id="ump" hidden><div class="uh"><span class="av lg" style="background:${c}">${esc(initials(ME.full_name))}</span><div><b>${esc(ME.full_name)}</b><small>${esc(ME.username)}${ME.employee_id?' &middot; '+esc(ME.employee_id):''}${ME.org?' &middot; '+esc(ME.org):''}</small><small>${ME.roles.map(x=>`<span class="rl" style="background:${ROLE_COL[x]}22;color:${ROLE_COL[x]}">${ROLE_LBL[x]}</span>`).join('')}</small></div></div>
 ${isCust()?`<a href="#/my">Open requests</a><a href="#/my/request">New test request</a>`:ME.roles.includes('admin')?`<a href="#/dashboard">Dashboard and tasks</a>`:`<a href="#/mywork">My work</a>`}
 <a href="#/notifications">Notifications</a><button onclick="umClose();pwView()">Change password</button><button class="so" onclick="logout()">Sign out</button></div></div>`}
function umToggle(e){e.stopPropagation();const p=$('#ump'),b=$('#umb');if(!p)return;p.hidden=!p.hidden;b.setAttribute('aria-expanded',String(!p.hidden))}
function umClose(){const p=$('#ump');if(p){p.hidden=true;$('#umb').setAttribute('aria-expanded','false')}}
document.addEventListener('click',e=>{if(!e.target.closest||!e.target.closest('.um'))umClose()});
document.addEventListener('keydown',e=>{if(e.key=='Escape')umClose()});
addEventListener('hashchange',umClose);

/* ---------------------------------------------------------------- dashboard: what waits on me */
async function dashTasks(){if(!ME||isCust())return;const h=$('#app .hero');if(!h)return;let w;try{w=await api('/api/my-work')}catch(e){return}
 const it=(x,extra='')=>`<div class="ti"><a href="${x.href||'#/job/'+x.id}"><b>${esc(x.series)}</b>${x.name?` &middot; ${esc(x.name)}`:''}<small>${extra}</small></a>${x._btn||''}</div>`,
  G=(t,list,line,hot,more)=>list&&list.length?`<div class="tg ${hot?'hot':''}"><h3>${t}<i>${list.length}</i></h3>${list.slice(0,5).map(x=>it(x,line(x))).join('')}${list.length>5?`<div class="ti"><a class="lk" style="padding:0" href="#/${more||'mywork'}">${list.length-5} more&hellip;</a></div>`:''}</div>`:'',
  ago=t=>t?dur((Date.now()-new Date(t))/36e5)+' ago':'';
 const take=x=>Object.assign(x,{_btn:`<button class="btn g s" onclick='takeTest(${x.id},"${x.key}",${JSON.stringify(x.name)})'>Take</button>`});
 const assign=x=>Object.assign(x,{_btn:`<a class="btn g s" href="#/job/${x.id}">Assign</a>`});
 let g='';
 if(ME.roles.includes('admin'))g+=G('Reports to approve',w.to_approve,x=>`${esc(x.customer||'')} &middot; report generated ${ago(x.at)}`,1)+G('Tests not assigned',(w.unassigned||[]).map(assign),x=>'',0,'dashboard')+
  G('Customer requests waiting',(w.requests||[]).map(x=>({...x,series:x.org||'Customer',name:'Request '+x.id,href:'#/intake/r'+x.id})),x=>ago(x.at))+G('Awaiting verification',w.awaiting_verification,x=>`uploaded by ${esc(x.by||'-')} ${ago(x.at)}`)+
  G('Locked accounts',(w.locked_accounts||[]).map(x=>({...x,href:'#/users'})),x=>`until ${esc((x.at||'').slice(11,16))}`,1)+
  G('Customer tickets to answer',(w.tickets||[]).map(x=>({...x,href:'#/tickets/'+x.id})),x=>ago(x.at),1,'tickets');
 if(ME.roles.includes('tester'))g+=G('Returned to you',w.returned,x=>`<span style="color:var(--er)">${esc(x.note||'')}</span>`,1)+G('To test',w.assigned,x=>'assigned '+ago(x.at),1)+
  G('Available to take',(w.available||[]).map(take),x=>'not assigned')+G('Intake to complete',w.intake,x=>'intake not confirmed against the original')+
  G('Customer requests waiting',(w.requests||[]).map(x=>({...x,series:x.org||'Customer',name:'Request '+x.id,href:'#/intake/r'+x.id})),x=>ago(x.at)+' &middot; open it when the sample arrives');
 if(ME.roles.includes('verifier'))g+=G('To verify',w.to_verify,x=>`uploaded by ${esc(x.by||'-')} ${ago(x.at)}`,1)+G('Ready for your sign-off',w.to_signoff,x=>'every test verified');
 if(ME.roles.includes('approver')&&!ME.roles.includes('admin'))g+=G('Reports to approve',w.to_approve,x=>'report generated '+ago(x.at),1);
 const c=document.createElement('div');c.className='card';c.id='tasks';
 c.innerHTML=`<div class="wh"><h2 style="margin:0">Your tasks</h2>${ME.roles.includes('admin')?'':'<a class="lk" href="#/mywork">Open My work</a>'}</div>${g?`<div class="tasks">${g}</div>`:'<p class="note">Nothing is waiting on you right now.</p>'}`;
 h.after(c)}

/* ---------------------------------------------------------------- tests: take one (engineer) or assign (admin) */
async function takeTest(id,key,name){modal(`<h2>Take: ${esc(name)}</h2><p class="note">The test is assigned to you; you upload its logsheet when it is done.</p>
 <div style="display:flex;gap:10px;justify-content:flex-end;margin-top:16px"><button class="btn g" onclick="closeModal()">Cancel</button><button class="btn" id="tk_ok">Take this test</button></div>`);
 $('#tk_ok').onclick=async()=>{try{await api(`/api/jobs/${id}/assign`,{key});closeModal();toast('Assigned to you');route()}catch(e){toast(e,1)}}}
async function giveBack(id,key){try{await api(`/api/jobs/${id}/assign`,{key,user_id:null});toast('Given back');job(id)}catch(e){toast(e,1)}}
async function assignModal(id,key,name,all){const t=await api('/api/testers');
 modal(`<h2>${all?'Assign the whole job':'Assign: '+esc(name)}</h2><p class="note">${all?'Every planned test nobody has started or taken goes to this engineer (tests they are not certified for are skipped).':'The engineer is notified.'}</p>
 <div class="frm"><label for="as_u">Test engineer</label><select id="as_u">${all?'':'<option value="">Nobody (remove the assignment)</option>'}${t.filter(x=>all||!x.tests.length||x.tests.includes(key)).map(x=>`<option value="${x.id}">${esc(x.name)}${x.tests.length?' ('+esc(x.tests.join(', '))+')':''}</option>`).join('')}</select></div>
 <div style="display:flex;gap:10px;justify-content:flex-end;margin-top:16px"><button class="btn g" onclick="closeModal()">Cancel</button><button class="btn" id="as_ok">Assign</button></div>`);
 $('#as_ok').onclick=async()=>{try{const r=await api(`/api/jobs/${id}/assign`,all?{all:true,user_id:+$('#as_u').value}:{key,user_id:+$('#as_u').value||null});
  closeModal();toast(all?`Assigned ${r.assigned.length} test${r.assigned.length==1?'':'s'}${r.skipped.length?'; skipped: '+r.skipped.join(', '):''}`:'Assignment saved');job(id)}catch(e){toast(e,1)}}}

/* ---------------------------------------------------------------- customer: fill in the request online */
/* ---------------------------------------------------------------- dashboard emblem: a seal in the manner of the CPRI emblem */
function heroArt(){
 /* background: a short-circuit current as on an oscillogram (asymmetric, decaying DC offset), stretching with the banner */
 let d='',d2='';for(let x=0;x<=1200;x+=4){const t=x/1200*9*Math.PI,on=x>140,env=on?Math.exp(-(x-140)/520):0,y=on?-(Math.sin(t-1.2)-Math.sin(-1.2)*env)*34*(0.55+0.45*env):0,y2=on?-(Math.sin(t+0.9)-Math.sin(0.9)*env)*30*(0.55+0.45*env):0;
  d+=(x?'L':'M')+x+' '+(300+y).toFixed(1);d2+=(x?'L':'M')+x+' '+(300+y2).toFixed(1)}
 return `<svg class="sc" viewBox="0 0 1200 360" preserveAspectRatio="xMidYMax slice" aria-hidden="true"><g fill="none" stroke-linejoin="round"><path d="${d}" stroke="#8fd8ff" stroke-opacity=".35" stroke-width="2"/><path d="${d2}" stroke="#ffb3a7" stroke-opacity=".2" stroke-width="1.6" stroke-dasharray="6 6"/><path d="M0 300H1200" stroke="#ffffff" stroke-opacity=".08"/></g></svg>`+emblem()}
/* the emblem: a seal in the manner of the CPRI emblem (rings, lettering, lightning, ribbon) around a distribution transformer */
function emblem(){const cx=200,cy=180,F='font-family="Inter,Segoe UI,sans-serif"';
 const bush=x=>`<path d="M${x-3} ${cy-8}V${cy-44}h6v36z" fill="#d7e6fb"/>${[18,26,34,42].map(o=>`<ellipse cx="${x}" cy="${cy-o}" rx="9" ry="3" fill="#fff" fill-opacity=".92"/>`).join('')}<circle cx="${x}" cy="${cy-50}" r="3.4" fill="#ff8a7a"/>`;
 const fins=x0=>[0,1,2,3,4].map(i=>`<path d="M${x0+i*4} ${cy}V${cy+50}" stroke="#cfe0f7" stroke-width="2"/>`).join('');
 const bolt='M0 0L44-20L34-2L70-15L12 26L24 6Z';
 return `<svg class="emb" viewBox="0 0 400 380" role="img" aria-label="Aletheia emblem: a transformer within a seal reading Short Circuit Laboratory, Test, Verify, Release, CPRI Bengaluru">
 <defs><path id="emT" d="M${cx-110} ${cy+40}A117 117 0 1 1 ${cx+110} ${cy+40}"/><path id="emB" d="M${cx-131} ${cy}A131 131 0 0 0 ${cx+131} ${cy}"/><path id="emR" d="M${cx-96} ${cy+150}Q${cx} ${cy+176} ${cx+96} ${cy+150}"/>
 <radialGradient id="emG" cx="50%" cy="45%" r="60%"><stop offset="0" stop-color="#2d6fc4" stop-opacity=".6"/><stop offset="1" stop-color="#0b2347" stop-opacity="0"/></radialGradient></defs>
 <circle cx="${cx}" cy="${cy}" r="185" fill="url(#emG)"/>
 <path d="${bolt}" transform="translate(${cx-196} ${cy+64}) rotate(-8)" fill="#ff6b5e"/><path d="${bolt}" transform="translate(${cx+196} ${cy+64}) scale(-1 1) rotate(-8)" fill="#ff6b5e"/>
 <circle cx="${cx}" cy="${cy}" r="150" fill="#0d2a55" fill-opacity=".6" stroke="#fff" stroke-opacity=".9" stroke-width="3"/>
 <circle cx="${cx}" cy="${cy}" r="140" fill="none" stroke="#fff" stroke-opacity=".45" stroke-width="1.2"/>
 <circle cx="${cx}" cy="${cy}" r="102" fill="#0b2347" fill-opacity=".65" stroke="#fff" stroke-opacity=".75" stroke-width="2"/>
 <text ${F} font-size="11.5" font-weight="700" letter-spacing="1.6" fill="#fff"><textPath href="#emT" startOffset="50%" text-anchor="middle">SHORT CIRCUIT LABORATORY • TEST • VERIFY • RELEASE</textPath></text>
 <text ${F} font-size="12" font-weight="600" letter-spacing="3" fill="#cfe0f7"><textPath href="#emB" startOffset="50%" text-anchor="middle">CPRI • BENGALURU</textPath></text>
 ${[cx-30,cx,cx+30].map(bush).join('')}<rect x="${cx-45}" y="${cy-8}" width="90" height="62" rx="5" fill="#1c4f9c" stroke="#d7e6fb" stroke-width="2"/>
 <path d="M${cx-45} ${cy+8}H${cx+45}M${cx-45} ${cy+38}H${cx+45}" stroke="#d7e6fb" stroke-opacity=".5"/>${fins(cx-66)}${fins(cx+50)}
 <path d="M${cx-48} ${cy+54}h96v7h-96z" fill="#d7e6fb"/><path d="M${cx-8} ${cy+14}l9-4-3 9 7-2-12 14 3-9-6 2z" fill="#ff8a7a"/>
 <text x="${cx}" y="${cy+84}" text-anchor="middle" ${F} font-size="10.5" font-weight="600" letter-spacing="1.5" fill="#cfe0f7">IS 1180 · IS 2026</text>
 <path d="M${cx-118} ${cy+132}L${cx-142} ${cy+150}L${cx-118} ${cy+168}L${cx-104} ${cy+162}Z" fill="#9b1c1c"/><path d="M${cx+118} ${cy+132}L${cx+142} ${cy+150}L${cx+118} ${cy+168}L${cx+104} ${cy+162}Z" fill="#9b1c1c"/>
 <path d="M${cx-110} ${cy+132}Q${cx} ${cy+158} ${cx+110} ${cy+132}L${cx+110} ${cy+162}Q${cx} ${cy+188} ${cx-110} ${cy+162}Z" fill="#c0392b" stroke="#fff" stroke-opacity=".8" stroke-width="1.5"/>
 <text ${F} font-size="15" font-weight="800" letter-spacing="4" fill="#fff" dominant-baseline="middle"><textPath href="#emR" startOffset="50%" text-anchor="middle">ALETHEIA</textPath></text></svg>`}
