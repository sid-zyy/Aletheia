/* Workflow in the page: per-test verification card on the job page, strict intake, "My work" queues, test bays.
   The server enforces every rule (ownership, separation of duties, locks); this file shows the state and the next step. */
const WSTATE={not_started:'Not started',uploaded:'Awaiting verification',returned:'Returned to tester',verified:'Verified',na:'Not applicable'};
const SECN={request:'Customer request form',proforma:'Proforma for transformers',work:'Work instruction',losses:'Losses datasheet',resistance:'Losses logsheet (resistance)',noload:'Losses logsheet (no-load)',
 routine:'Routine test logsheet',sc:'Short-circuit logsheet',temp:'Temperature-rise logsheet',pressure:'Pressure / oil-leakage logsheet',ids:'Identifiers on each sheet',other:'Additional log sheets'};
const secName=k=>SECN[k]||k;
(()=>{const s=document.createElement('style');s.textContent=`
.wt{width:100%;border-collapse:collapse;font-size:14px}.wt td{padding:10px 8px;border-top:1px solid var(--ln);vertical-align:top}.wt tr:first-child td{border-top:0}
.wt .acts{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end}.wt small{display:block;color:var(--mu);font-size:12px;line-height:1.35}
.wt .rsn{color:var(--er)}.wh{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:12px}
.ib{display:flex;gap:12px;align-items:center;justify-content:space-between;flex-wrap:wrap;padding:12px 14px;border-radius:12px;margin-bottom:14px;font-size:14px}
.ib.ok{background:var(--ok2);color:var(--ok)}.ib.no{background:var(--wn2);color:var(--wn)}
.vt{width:100%;border-collapse:collapse;font-size:13px}.vt td{padding:5px 8px;border-bottom:1px solid var(--ln)}.vt td:first-child{color:var(--mu);font-family:ui-monospace,Consolas,monospace;font-size:12px}
.ifm{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:4px 16px}.ifm .w{grid-column:1/-1}
.ifm label{display:block;font-size:13px;font-weight:600;color:var(--mu);margin:12px 0 6px}.ifm .nab{font-size:12px;font-weight:500}
.errs{background:var(--er2);color:var(--er);border-radius:12px;padding:12px 16px;font-size:14px;margin:14px 0}.errs ul{margin:6px 0 0;padding-left:18px}
.warns{background:var(--wn2);color:var(--wn);border-radius:12px;padding:12px 16px;font-size:14px;margin:14px 0}
.okb{background:var(--ok2);color:var(--ok);border-radius:12px;padding:12px 16px;font-size:14px;margin:14px 0}
.qi{display:flex;justify-content:space-between;gap:10px;padding:9px 0;border-top:1px solid var(--ln);font-size:14px;cursor:pointer}.qi:first-of-type{border:0}.qi:hover{color:var(--ac)}
body.no-data-write [onclick^="pick(ACC"],body.no-data-write #dz,body.no-data-write [onclick^="editSec"],body.no-data-write [onclick^="rmSec"],body.no-data-write [onclick^="rmImp"],body.no-data-write [onclick^="delSrc"],body.no-data-write [onclick^="readAI"],
body.no-job-delete [onclick^="delJob"],body.no-job-edit [onclick^="editJob"],body.no-data-check [onclick^="runChecks"],body.no-data-check [onclick^="act('validate'"],
body.no-report-generate [onclick^="act('generate'"],body.no-report-approve [onclick^="discard"],body.no-job-create [href="#/new"],body.no-job-create [href="#/intake"],body.no-job-create [onclick^="demo()"]{display:none!important}
`;document.head.append(s)})();
/* hide what the role cannot use: one class per missing permission (the server refuses these calls anyway) */
function roleClasses(){for(const p of['data.write','job.delete','job.edit','data.check','report.generate','report.approve','job.create'])document.body.classList.toggle('no-'+p.replace('.','-'),!!ME&&!can(p))}
const bay=()=>{try{return +localStorage.getItem('aletheia.bay')||null}catch(e){return null}};
const setBay=v=>{try{v?localStorage.setItem('aletheia.bay',v):localStorage.removeItem('aletheia.bay')}catch(e){}};

/* ---------------------------------------------------------------- job page: tests and verification */
async function wfCard(j){if(isCust())return;const id=j.id,nx=$('.card.next');if(!nx)return;
 const [bays,testers]=await Promise.all([can('data.write')?api('/api/bays'):[],can('job.assign')?api('/api/testers'):[]]);
 const keys=[...new Set([...(j.plan.length?j.plan:j.progress.map(p=>p.key)),...Object.keys(j.meta).filter(k=>k!='request')])];
 const st=k=>(j.meta[k]||{}).state||'not_started',n=s=>keys.filter(k=>st(k)==s).length,ver=can('section.verify');
 const row=k=>{const m=j.meta[k]||{},s=st(k),a=j.assign[k],mine=m.uploaded_by_id==ME.id,acts=[];
  if(ver&&!j.released){if(s=='uploaded'&&!mine&&k in j.data)acts.push(`<button class="btn s" onclick="wfReview(${id},'${k}')">Check and verify</button>`);
   if(s=='verified'||s=='na')acts.push(`<button class="btn g s" onclick="wfReason(${id},'${k}','reopen')">Reopen</button>`);
   if(s=='not_started'||s=='uploaded'||s=='returned')acts.push(`<button class="lk" onclick="wfReason(${id},'${k}','na')">Not applicable</button>`)}
  const cert=!(ME.test_types||'')||(ME.test_types||'').split(',').includes(k);
  if(!j.released&&k!='ids'&&k!='other'){
   if(ME.roles.includes('admin'))acts.push(`<button class="btn g s" onclick='assignModal(${id},"${k}",${JSON.stringify(secName(k))})'>${a?'Reassign':'Assign'}</button>`);
   else if(ME.roles.includes('tester')&&!a&&s=='not_started'&&cert)acts.push(`<button class="btn g s" onclick='takeTest(${id},"${k}",${JSON.stringify(secName(k))})'>Take this test</button>`);
   else if(a&&a.user_id==ME.id&&s=='not_started')acts.push(`<button class="lk" onclick="giveBack(${id},'${k}')">Give back</button>`)}
  return `<tr><td><b>${esc(secName(k,j))}</b>${!j.plan.length||j.plan.includes(k)||k=='ids'||k=='other'?'':' <small style="display:inline">(not in the test plan)</small>'}
   ${m.uploaded_by?`<small>Uploaded by ${esc(m.uploaded_by)}${m.bay?' in '+esc(m.bay):''}${m.uploaded_at?' &middot; '+esc(m.uploaded_at.slice(0,16).replace('T',' ')):''}${m.file?` &middot; <a class="lk" style="padding:0;font-size:12px" href="/api/files/${m.file_id}">${esc(m.file)}</a>`:''} &middot; rev ${m.revision}</small>`:''}
   ${m.verified_by?`<small>Verified by ${esc(m.verified_by)} &middot; ${esc((m.verified_at||'').slice(0,16).replace('T',' '))}</small>`:''}
   ${a?`<small>Assigned to ${esc(a.name)}${a.bay?' &middot; '+esc(a.bay):''}</small>`:''}${m.note&&(s=='returned'||s=='na'||s=='uploaded')?`<small class="${s=='returned'?'rsn':''}">${s=='returned'?'Returned: ':s=='na'?'Reason: ':'Reopened: '}${esc(m.note)}</small>`:''}</td>
   <td style="white-space:nowrap"><span class="pst ${s=='returned'?'returned':s}">${WSTATE[s]}</span></td><td><div class="acts">${acts.join('')}</div></td></tr>`};
 const it=j.intake||{},iok=it.valid&&it.checked_by;
 const intake=`<div class="ib ${iok?'ok':'no'}"><span>${iok?`Intake complete: received ${esc((it.arrived_at||'').replace('T',' '))} by ${esc(it.received_by)}${it.opened_by?`, box opened by ${esc(it.opened_by)}`:''}; checked against the original form by ${esc(it.checked_by)}.`
  :it.valid?'Intake details are complete. Read them back against the customer\'s original form, then confirm.':'Intake details are incomplete. The report cannot be released until every required field is filled in and checked.'}</span>
  <span style="display:flex;gap:8px">${!j.released&&can('job.edit')?`<a class="btn g s" href="#/intake/${id}">${it.valid?'Review intake':'Complete intake'}</a>`:''}${!j.released&&can('job.edit')&&it.valid&&!it.checked_by?`<button class="btn s" onclick="wfChecked(${id})">Checked against the original</button>`:''}</span></div>`;
 const so=j.signoff?`<span class="pst verified">Signed off by ${esc(j.signoff.by)}</span>`:ver&&!j.released&&!j.signoff_blockers.length&&j.stage>=2?`<button class="btn s" onclick="wfSignoff(${id})">Sign off: all data correct</button>`:`<span class="note" style="margin:0">${j.signoff_blockers.length?`${j.signoff_blockers.length} item${j.signoff_blockers.length==1?'':'s'} before sign-off`:j.stage<2?'Run the checks before sign-off':''}</span>`;
 let ab=null;if(j.amend){const b=ab=document.createElement('div');b.className='card';b.style.borderColor='var(--wn)';
  b.innerHTML=`<h2 style="margin:0 0 6px">Amendment open</h2><p style="margin:0">Opened ${esc(j.amend.opened_at.replace('T',' '))} by ${esc(j.amend.opened_by)} with ${esc(j.amend.second_signer)}: <b>${esc(j.amend.reason)}</b></p><p class="note">Reopened: ${j.amend.sections.map(k=>esc(k=='request'?'Customer request / intake':secName(k))).join(', ')}. Version ${j.amend.from_version} remains the valid report until the corrected version is released.</p>`}
 const c=document.createElement('div');c.className='card';c.id='wf';
 c.innerHTML=`<div class="wh"><div><h2 style="margin:0">Tests and verification</h2><span class="note">${n('verified')} of ${keys.length-n('na')} verified &middot; ${n('uploaded')} awaiting verification &middot; ${n('returned')} returned &middot; ${n('not_started')} not started${n('na')?` &middot; ${n('na')} not applicable`:''}</span></div>
  <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">${can('data.write')&&!j.released&&bays.some(b=>b.active)?`<label class="note" style="margin:0" for="wfbay">Recording bay</label><select id="wfbay" style="width:auto;padding:7px 10px" onchange="setBay(this.value)"><option value="">Not recorded</option>${bays.filter(b=>b.active).map(b=>`<option value="${b.id}" ${bay()==b.id?'selected':''}>${esc(b.name)}</option>`).join('')}</select>`:''}${so}<button class="lk" onclick="wfHistory(${id})">Section history</button>${j.ever_released&&can('data.export')?`<a class="lk" href="/api/jobs/${id}/package.zip" title="Every released version, its manifest, source files, history and audit, with checksums">Record package (zip)</a>`:''}${!j.released&&ME.roles.includes('admin')?`<button class="btn g s" onclick="assignModal(${id},null,'',1)">Assign whole job</button>`:''}${j.released&&can('report.amend')?`<button class="btn g s" onclick='amendModal(${id},${JSON.stringify(Object.keys(j.meta).filter(k=>k!="request"))})'>Amend this report</button>`:''}</div></div>
  ${intake}<div class="scroll"><table class="wt">${keys.map(row).join('')}</table></div>`;
 nx.after(c);if(ab)nx.after(ab)}
/* released reports are superseded, never edited: an approver and a second approver sign the reason */
function amendModal(id,keys){modal(`<h2>Amend the released report</h2><p class="note">The released version stays valid, stored and verifiable until the corrected version is released; it is then marked superseded with your reason. Only the tests you name reopen; they go through upload, verification, sign-off and approval again.</p>
 <div class="frm"><label for="am_r">Reason (printed on the new version)</label><textarea class="in" id="am_r" rows="3" style="resize:vertical"></textarea>
 <label>Tests to correct</label><div class="chk">${keys.map(k=>`<label><input type="checkbox" name="am_k" value="${k}"> ${esc(secName(k))}</label>`).join('')}<label><input type="checkbox" name="am_k" value="request"> Customer request / intake details</label></div>
 <div class="row2"><div><label for="am_p">Your password</label><input class="in" id="am_p" type="password" autocomplete="current-password"></div><div></div></div>
 <p class="note" style="margin-top:14px"><b>Second signer:</b> another approver confirms at this workstation with their own password.</p>
 <div class="row2"><div><label for="am_u">Second approver's username</label><input class="in" id="am_u" autocomplete="off"></div><div><label for="am_q">Their password</label><input class="in" id="am_q" type="password" autocomplete="off"></div></div></div>
 <div style="display:flex;gap:10px;justify-content:flex-end;margin-top:16px"><button class="btn g" onclick="closeModal()">Cancel</button><button class="btn" id="am_ok">Open the amendment</button></div>`);
 $('#am_ok').onclick=async()=>{try{await api(`/api/jobs/${id}/amend`,{reason:$('#am_r').value,sections:[...document.querySelectorAll('[name=am_k]:checked')].map(x=>x.value),password:$('#am_p').value,second:{username:$('#am_u').value,password:$('#am_q').value}});
  closeModal();toast('Amendment opened: the named tests are reopened');job(id)}catch(e){toast(e,1);$('#am_p').value='';$('#am_q').value=''}}}
async function wfDo(id,k,act,b,msg){try{await api(`/api/jobs/${id}/sections/${k}/${act}`,b||{});closeModal();toast(msg);job(id)}catch(e){toast(e,1)}}
function wfReason(id,k,act){const t={reopen:['Reopen for correction','Why must it be corrected? The tester sees this.','Reopen'],na:['Mark as not applicable','Why does this test not apply to this job? It is recorded with the report.','Mark not applicable'],
 ret:['Return to the tester','What is wrong? Be specific (cell, hour, reading). The tester sees this.','Return']}[act];
 modal(`<h2>${t[0]}: ${esc(secName(k))}</h2><div class="frm"><label for="wr">${t[1]}</label><textarea class="in" id="wr" rows="3" style="resize:vertical"></textarea></div><div style="display:flex;gap:10px;justify-content:flex-end;margin-top:16px"><button class="btn g" onclick="closeModal()">Cancel</button><button class="btn" id="wrok">${t[2]}</button></div>`);
 $('#wrok').onclick=()=>wfDo(id,k,act=='ret'?'return':act,{reason:$('#wr').value,revision:WREV},t[2]=='Return'?'Returned to the tester':t[2]=='Reopen'?'Reopened':'Marked not applicable')}
let WREV=null;
/* verifier: the values as stored, next to the original file, then verify or return */
async function wfReview(id,k){const j=await api('/api/jobs/'+id),m=j.meta[k],rows=flat(j.data[k]||{});WREV=m.revision;
 modal(`<h2>Verify: ${esc(secName(k,j))}</h2><p class="note">Compare every value with the source${m.file?`: <a class="lk" style="padding:0" href="/api/files/${m.file_id}">${esc(m.file)}</a> (SHA-256 ${esc((m.file_sha256||'').slice(0,12))}&hellip;)`:''}. Uploaded by ${esc(m.uploaded_by||'-')}${m.bay?' in '+esc(m.bay):''}, revision ${m.revision}.</p>
  <div style="max-height:46vh;overflow:auto;border:1px solid var(--ln);border-radius:10px"><table class="vt">${rows.map(([p,v])=>`<tr><td>${esc(p)}</td><td>${v==null||v===''?'<i style="color:var(--wn)">NA</i>':esc(v)}</td></tr>`).join('')}</table></div>
  <div style="display:flex;gap:10px;justify-content:flex-end;margin-top:16px;flex-wrap:wrap"><button class="btn g" onclick="closeModal()">Cancel</button><button class="btn g" style="color:var(--er)" onclick="wfReason(${id},'${k}','ret')">Return with a reason</button><button class="btn" id="wvok">Values match the source: verify</button></div>`);
 $('#wvok').onclick=()=>wfDo(id,k,'verify',{revision:m.revision},'Verified')}
async function wfAssign(id,k,uid){try{await api(`/api/jobs/${id}/assign`,{key:k,user_id:uid?+uid:null});toast(uid?'Assigned':'Assignment removed')}catch(e){toast(e,1)}job(id)}
async function wfSignoff(id){try{await api(`/api/jobs/${id}/signoff`,{});toast('Signed off');job(id)}catch(e){toast(e,1)}}
async function wfChecked(id){try{await api(`/api/jobs/${id}/intake/checked`,{});toast('Intake confirmed against the original form');job(id)}catch(e){toast(e,1)}}
async function wfHistory(id){const h=await api(`/api/jobs/${id}/history`);
 modal(`<h2>Section history</h2><p class="note">Every revision of every test's data, oldest first. Nothing here can be changed or deleted.</p><div style="max-height:60vh;overflow:auto"><table class="ut"><thead><tr><th>When</th><th>Test</th><th>Rev</th><th>State</th><th>Who / what</th></tr></thead><tbody>${h.map(x=>`<tr><td style="white-space:nowrap">${esc(x.at.replace('T',' '))}</td><td>${esc(secName(x.key))}</td><td>${x.revision}</td><td>${esc(x.state)}</td><td>${esc(x.by||'-')}<div class="note" style="margin:0">${esc(x.event||'')}${x.data_sha256?` &middot; data ${esc(x.data_sha256.slice(0,10))}&hellip;`:''}</div></td></tr>`).join('')}</tbody></table></div><div style="text-align:right;margin-top:14px"><button class="btn" onclick="closeModal()">Close</button></div>`);const m=$('#ov .md');if(m)m.style.maxWidth='1000px'}

/* ---------------------------------------------------------------- intake: nothing missing, nothing wrong */
/* ---------------------------------------------------------------- My work */
async function myWork(){const w=await api('/api/my-work'),age=t=>t?dur((Date.now()-new Date(t))/36e5)+' ago':'';
 const L=(title,items,line,empty)=>items?`<div class="card"><h2>${title} <span class="note" style="font-weight:400">(${items.length}${items.length?', oldest first':''})</span></h2>${items.length?items.map(x=>`<div class="qi" onclick="go('job/${x.id}')"><span><b>${esc(x.series)}</b> &middot; ${line(x)}</span><span class="note" style="margin:0">${age(x.at)}</span></div>`).join(''):`<p class="note">${empty}</p>`}</div>`:'';
 $('#app').innerHTML=head('My work',`What is waiting on you, ${esc(ME.full_name)}, oldest first.`)+
  L('Returned to you for correction',w.returned,x=>`${esc(x.name)}: <span style="color:var(--er)">${esc(x.note||'')}</span>`,'Nothing returned.')+
  L('Sections waiting for verification',w.to_verify,x=>`${esc(x.name)} (uploaded by ${esc(x.by||'-')})`,'Nothing to verify.')+
  L('Jobs ready for your sign-off',w.to_signoff,()=>'every test verified','None ready.')+
  L('Reports waiting for approval',w.to_approve,()=>'report generated, approval due','Nothing to approve.')+
  L('Tests assigned to you, not yet uploaded',w.assigned,x=>esc(x.name)+(x.bay?' &middot; '+esc(x.bay):''),'Nothing assigned.')+
  L('Tests nobody has taken (open the job to take one)',w.available,x=>esc(x.name),'Every planned test has someone.')+
  L('Tests not assigned (open the job to assign)',w.unassigned,x=>esc(x.name),'Every planned test is assigned.')+
  L('Intake to complete or check',w.intake,()=>'intake details incomplete or not checked against the original','All intakes complete.')+
  L('Your recent uploads',w.uploaded,x=>`${esc(x.name)} &middot; ${WSTATE[x.state]||x.state}`,'No uploads yet.')}

/* ---------------------------------------------------------------- Admin: test bays (on the Users page) */
async function bayCard(){const el=$('#baysCard');if(!el)return;const b=await api('/api/bays');
 el.innerHTML=`<div class="card"><div class="wh"><h2 style="margin:0">Test bays (${b.length})</h2><button class="btn g s" onclick="addBay()">Add bay</button></div>${b.length?b.map(x=>`<div class="src"><span>${esc(x.name)}${x.active?'':' <span class="rl" style="background:var(--cd2);color:var(--mu)">retired</span>'}</span><button class="lk" onclick="api('/api/bays/${x.id}',{active:${x.active?'false':'true'}}).then(bayCard).catch(e=>toast(e,1))">${x.active?'Retire':'Reactivate'}</button></div>`).join(''):'<p class="note">No bays yet. Testers record the bay with each upload; bays are retired, never deleted.</p>'}</div>`}
async function addBay(){const n=prompt('Name of the test bay (e.g. Bay 3, SC test cell 1)');if(!n)return;try{await api('/api/bays',{name:n});bayCard()}catch(e){toast(e,1)}}
