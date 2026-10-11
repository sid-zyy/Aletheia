/* Customer Request Form CPRI/QAF/01A. Only a customer raises a request: they fill in sheets 1 and 2 online, laid out as the
   printed form. The laboratory receives it in the intake inbox, records sheet 3 and creates the job, or returns it with the
   reason; the customer corrects it and sends it again. Uses the helpers in index.html: $, esc, api, go, head, toast. */
(()=>{const s=document.createElement('style');s.textContent=`
.qf{background:var(--cd);border:1px solid var(--ln);border-radius:12px;padding:22px 26px;margin-bottom:16px}
.qh{display:grid;grid-template-columns:1fr auto;gap:2px 20px;font-weight:700;font-size:13px;margin-bottom:14px;padding-bottom:10px;border-bottom:2px solid var(--tx)}
.qh .qt{grid-column:1/-1;text-align:center;font-size:16px;letter-spacing:.3px}.qh .qu{grid-column:1/-1;text-align:center;font-size:13px}
.qh .qn2{grid-column:1/-1;text-align:center;font-size:14px;margin-top:6px}
.qr{display:grid;grid-template-columns:minmax(170px,34%) 12px 1fr;gap:4px 8px;align-items:start;padding:8px 0;border-bottom:1px dashed var(--ln)}
.qr .ql{font-weight:600;font-size:14px;padding-top:7px}.qr .qc{font-weight:700;padding-top:7px}
.qr textarea{width:100%;min-height:64px;font:inherit;padding:8px 10px;border:1px solid var(--ln);border-radius:8px;background:var(--bg);color:var(--tx)}
.qg{font-weight:700;margin:16px 0 0;font-size:14.5px}.qnote{font-size:12.5px;color:var(--mu);margin-top:5px;line-height:1.45}
.qopt{display:flex;flex-direction:column;gap:6px;padding-top:6px}.qopt label{display:flex;gap:8px;align-items:flex-start;margin:0;font-weight:500;font-size:14px}
.qopt.row{flex-direction:row;gap:22px}.qagree{display:flex;gap:10px;align-items:flex-start;padding:10px 0;border-bottom:1px dashed var(--ln);font-size:14px}
.qreq{color:var(--er);font-weight:700}.qv{padding-top:7px;white-space:pre-wrap}.qv.na{color:var(--mu)}.qbad{outline:2px solid var(--er);outline-offset:2px;border-radius:6px}
.qtests{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:6px 14px;margin-top:8px}.qtests label{display:flex;gap:8px;margin:0;font-weight:500;font-size:13.5px}
.qsig{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:14px;font-size:14px}
@media(max-width:680px){.qr{grid-template-columns:1fr}.qr .qc{display:none}.qf{padding:16px}}`;document.head.append(s)})();

const QS={received:['uploaded','Waiting for the laboratory'],returned:['returned','Returned to you for correction'],used:['verified','Received by the laboratory'],replaced:['na','Replaced by a corrected request']};
const qHead=(F,sheet,lab)=>`<div class="qh"><div class="qt">${esc(T(F.form.org))}</div><div class="qu">${esc(T(F.form.unit))}</div><div>${T('Format No:')} ${esc(F.form.format_no)}</div>
 <div style="text-align:right">${esc(T(F.form.issue))}<br>${esc(T(F.form.issue_date))}</div><div class="qn2">${lab?T('(To be filled by the laboratory)'):esc(T(F.form.title))}</div><div></div><div style="text-align:right">${T('Sheet {n} of 3',{n:sheet})}</div></div>`;
const req=f=>f.optional||f.ro?'':`<span class="qreq" title="${T('Required')}" aria-label="${T('Required')}"> *</span>`;
const qShow=v=>v===''||v==null?'<span class="qv na">-</span>':`<div class="qv">${esc(v)}</div>`;

/* one field of the form; p = id prefix; ro = show the value only */
function qField(f,v,p,ro,F){if(ro)f={...f,ro:1};const id=p+f.key,note=f.note?`<div class="qnote">${esc(T(f.note))}</div>`:'';v=v==null?'':v;
 if(f.kind=='agree')return `<div class="qagree" data-k="${f.key}">${ro?(v?'&#9745;':'&#9744;'):`<input type="checkbox" id="${id}" ${v?'checked':''}>`}<label for="${id}" style="margin:0;font-weight:500">${esc(T(f.label))}${req(f)}${note}</label></div>`;
 let inp;
 if(ro)inp=qShow(v);
 else if(f.kind=='state')inp=`<select id="${id}"><option value="">${T('Choose...')}</option>${F.states.map(s=>`<option value="${esc(s)}" ${s==v?'selected':''}>${esc(T(s))}</option>`).join('')}</select>`;
 else if(f.kind=='yesno')inp=`<div class="qopt row">${['Yes','No'].map(o=>`<label><input type="radio" name="${id}" value="${o}" ${v==o?'checked':''}> ${T(o)}</label>`).join('')}</div>`;
 else if(f.kind=='choice')inp=`<div class="qopt${f.options.length<3?' row':''}">${f.options.map(o=>`<label><input type="radio" name="${id}" value="${esc(o)}" ${v==o?'checked':''}> ${esc(T(o))}</label>`).join('')}</div>`;
 else if(f.wide)inp=`<textarea id="${id}">${esc(v)}</textarea>`;
 else inp=`<input class="in" id="${id}" value="${esc(v)}" ${f.kind=='pin'?'inputmode="numeric" maxlength="6"':f.kind=='email'?'type="email"':f.kind=='phone'?'type="tel"':f.kind=='count'?'type="number" min="1"':''}>`;
 const na=f.na_ok&&!ro?`<label style="display:flex;gap:6px;align-items:center;margin:6px 0 0;font-weight:500;font-size:13px"><input type="checkbox" id="${id}_na" ${String(v).startsWith('Not applicable:')?'checked':''} onchange="$('#${id}_nr').style.display=this.checked?'':'none'"> ${T('Not applicable')}</label><input class="in" id="${id}_nr" placeholder="${T('Reason it does not apply')}" style="margin-top:6px;${String(v).startsWith('Not applicable:')?'':'display:none'}" value="${esc(String(v).replace(/^Not applicable: ?/,''))}">`:'';
 return `<div class="qr" data-k="${f.key}"><div class="ql">${esc(T(f.label))}${req(f)}</div><div class="qc">:</div><div>${inp}${na}${note}</div></div>`}

function qFields(fields,vals,p,ro,F,after={}){let g=null,h='';
 for(const f of fields){if(f.group!==g){g=f.group;if(g)h+=`<div class="qg">${esc(T(g))}</div>`}h+=qField(f,vals[f.key],p,ro,F)+(after[f.key]||'')}return h}
function qCollect(fields,p){const b={na:{}};for(const f of fields){const id=p+f.key;
  if(f.kind=='agree'){const e=$('#'+id);b[f.key]=!!(e&&e.checked);continue}
  if(f.kind=='yesno'||f.kind=='choice'){const e=document.querySelector(`[name="${id}"]:checked`);b[f.key]=e?e.value:'';continue}
  const e=$('#'+id);b[f.key]=e?e.value:'';const n=$('#'+id+'_na');if(n&&n.checked)b.na[f.key]=$('#'+id+'_nr').value}
 return b}
/* rows that only apply after a certain answer (e.g. the decision rule when a statement of conformity is wanted) */
function qWhen(fields,p,root){const upd=()=>{for(const f of fields){if(!f.when)continue;const e=document.querySelector(`[name="${p+f.when[0]}"]:checked`),r=root.querySelector(`[data-k="${f.key}"]`);if(r)r.style.display=e&&e.value==f.when[1]?'':'none'}};
 root.addEventListener('change',upd);upd()}
const qProblems=(e,w,okText)=>(e.length?`<div class="errs" role="alert"><b>${e.length==1?T('1 thing to correct'):T('{n} things to correct',{n:e.length})}</b><ul>${e.map(x=>`<li>${esc(TF(x))}</li>`).join('')}</ul></div>`:`<div class="okb">${T(okText)}</div>`)+(w.length?`<div class="warns"><b>${T('Please check')}</b><ul>${w.map(x=>`<li>${esc(TF(x))}</li>`).join('')}</ul></div>`:'');

/* ---------------------------------------------------------------- customer: raise (or correct) a request */
async function custRequestPage(fid){const [F,old]=await Promise.all([api('/api/intake/fields'),fid?api('/api/customer/requests/'+fid):null]);
 const v=old?{...old.values}:{customer:ME.org||'',email:ME.email||'',contact:ME.full_name||'',signed_name:ME.full_name||''},plan=old?old.plan:[];
 const s1=F.fields.filter(f=>f.sheet==1),s2=F.fields.filter(f=>f.sheet==2);
 const ticks=`<div class="qr"><div class="ql">${T('Tests to be carried out')}<div class="qnote" style="font-weight:400">${T('Tick each test you need; the laboratory plans the job from these.')}</div></div><div class="qc">:</div><div class="qtests">${Object.entries(F.tests).map(([k,l])=>`<label><input type="checkbox" name="cp" value="${k}" ${plan.includes(k)?'checked':''}> ${esc(T(l))}</label>`).join('')}</div></div>`;
 $('#app').innerHTML=`<button class="back" onclick="go('my')">&larr; ${T('Open requests')}</button>`+head(T(old?'Correct and send again':'New test request'),
  old&&old.note?`${T('Returned by the laboratory:')} <b>${esc(old.note)}</b>`:T('Customer Request Form {fmt}, filled in online for {org}. Every value is checked as you type; the laboratory receives it and records the rest when the sample arrives.',{fmt:esc(F.form.format_no),org:esc(ME.org||T('your organisation'))}))+
 `<div class="qf" id="qs1">${qHead(F,1)}${qFields(s1,v,'c_',false,F,{tests:ticks})}</div>
  <div class="qf" id="qs2">${qHead(F,2)}${qFields(s2,v,'c_',false,F)}<div class="qsig"><div></div><div style="text-align:right">${T('Customers Name & Signature with Date')}<br><b id="qsn">${esc(v.signed_name||'')}</b> &middot; ${new Date().toLocaleDateString(LOC())}</div></div></div>
  <div class="qf" style="opacity:.75">${qHead(F,3,1)}<p class="note" style="margin:0">${T("Physical condition of the sample on receipt, the laboratory's capability and the acceptance of the job are recorded by the laboratory when your sample arrives.")}</p></div>
  <div id="cv"></div><div class="card" style="display:flex;justify-content:flex-end;gap:10px;flex-wrap:wrap"><button class="btn g" id="cck">${T('Check for problems')}</button><button class="btn lg" id="csd">${T(old?'Send the corrected request':'Send the request')}</button></div>`;
 qWhen(F.fields,'c_',$('#app'));
 const collect=()=>({...qCollect(F.fields,'c_'),plan:[...document.querySelectorAll('[name=cp]:checked')].map(x=>x.value),...(old?{replaces:old.id}:{})});
 const show=r=>{const e=r.errors||r.error||[];$('#cv').innerHTML=qProblems(e,r.warnings||[],'Everything is filled in correctly.');
  document.querySelectorAll('.qr,.qagree').forEach(x=>{const f=F.fields.find(f=>f.key==x.dataset.k);x.classList.toggle('qbad',!!f&&e.some(m=>m.startsWith(f.label)||m.includes(f.label)))})};
 let tm;$('#app').addEventListener('input',()=>{const n=$('#c_signed_name');if(n)$('#qsn').textContent=n.value;clearTimeout(tm);tm=setTimeout(()=>api('/api/customer/requests/check',collect()).then(show).catch(()=>{}),700)});
 $('#cck').onclick=async()=>{try{show(await api('/api/customer/requests/check',collect()))}catch(e){toast(e,1)}};
 $('#csd').onclick=async()=>{const b=collect();try{await api('/api/customer/requests',b);toast(T('Request sent to the laboratory'));go('my')}
  catch(e){try{show(await api('/api/customer/requests/check',b))}catch(x){toast(e,1)}scrollTo(0,$('#cv').offsetTop-80)}}}

/* the customer's requests, on their "Open requests" page */
async function custForms(){const l=await api('/api/customer/request-forms'),el=document.createElement('div');
 el.innerHTML=`<div class="card"><div class="wh"><h2 style="margin:0">${T('Test requests')}</h2></div>
  <p class="note">${T('Fill in the Customer Request Form online; the laboratory receives it and opens the job when your sample arrives.')}</p>${l.length?l.map(f=>{const [c,t]=QS[f.status]||['uploaded',f.status];
   return `<div class="ps"><span>${T('Request {id}',{id:f.id})} <small class="sby">${T('sent {at}',{at:esc(f.at.replace('T',' ').slice(0,16))})}</small>${f.status=='returned'&&f.note?`<div class="note" style="margin:2px 0 0;color:var(--er)">${T('Reason:')} ${esc(f.note)}</div>`:''}</span>
    <span style="display:flex;gap:8px;align-items:center"><span class="pst ${c}">${f.status=='used'&&f.series?T('Job {s}',{s:esc(f.series)}):esc(T(t))}</span>${f.status=='returned'?`<a class="btn g s" href="#/my/request/${f.id}">${T('Correct and send again')}</a>`:''}</span></div>`}).join(''):`<div class="empty">${T('No requests yet.')}</div>`}</div>`;
 $('#app').append(el)}

/* ---------------------------------------------------------------- laboratory: the intake inbox and receiving a request */
async function intakePage(arg){if(arg&&String(arg).startsWith('r'))return receivePage(+String(arg).slice(1));if(arg)return jobIntakePage(+arg);
 const l=await api('/api/request-forms'),waiting=l.filter(f=>f.status=='received'),other=l.filter(f=>f.status!='received').slice(0,15);
 const row=f=>`<div class="row" style="grid-template-columns:1.3fr 1.6fr 1fr 150px" tabindex="0" onclick="go('intake/r${f.id}')"><div><b>${esc(f.org||'Customer')}</b><span class="m">request ${f.id} &middot; ${esc(f.sent_by||'')}</span></div>
  <div><b>${esc(f.sample||'')}</b><span class="m">${esc(f.rating||'')}</span></div><div class="m">${esc(f.at.replace('T',' ').slice(0,16))}</div><div>${f.status=='received'?'<span class="btn s">Open</span>':`<span class="pst ${(QS[f.status]||['na'])[0]}">${f.series?esc(f.series):esc(f.status)}</span>`}</div></div>`;
 $('#app').innerHTML=head('Customer requests','Only customers raise test requests (Customer Request Form CPRI/QAF/01A, filled in online). Open one when the sample arrives: record sheet 3, choose the test plan and accept it, or return it to the customer with the reason.')+
  `<div class="card"><h2>Waiting for intake (${waiting.length})</h2><div class="tb">${waiting.map(row).join('')||'<div class="empty">No requests waiting. Customers raise them from their portal.</div>'}</div></div>`+
  (other.length?`<div class="card"><h2>Recently handled</h2><div class="tb">${other.map(row).join('')}</div></div>`:'')}

function labBlock(F,vals,testers,plan,assignable){
 return `<div class="qf" id="qs3">${qHead(F,3,1)}${qFields(F.lab,vals,'l_',false,F)}
  <div class="qr"><div class="ql">Name &amp; signature of Test Engineer/Test In charge for accepting the job, with date</div><div class="qc">:</div><div class="qv">${esc(vals.received_by||ME.full_name)} &middot; ${esc((vals.recorded_at||new Date().toISOString()).slice(0,10))}</div></div></div>
  <div class="card"><h2>Test plan</h2><p class="note">The tests this job needs (as ticked by the customer). Each must be uploaded and verified, or marked not applicable with a reason, before the report is built.${assignable?' Tick the tests you will do yourself; the administrator assigns the others, or colleagues take them.':''}</p>
  <div class="scroll"><table class="wt">${Object.entries(F.tests).map(([k,l])=>`<tr><td><label style="display:flex;gap:8px;align-items:center;margin:0;font-weight:500"><input type="checkbox" name="pl" value="${k}" ${plan.includes(k)?'checked':''}> ${esc(l)}</label></td>${assignable?`<td style="text-align:right"><label style="display:inline-flex;gap:6px;align-items:center;margin:0;font-weight:500;font-size:13px"><input type="checkbox" id="as_${k}"> I will do this test</label></td>`:''}</tr>`).join('')}</table></div></div>`}
const labCollect=F=>({...qCollect(F.lab,'l_'),plan:[...document.querySelectorAll('[name=pl]:checked')].map(x=>x.value)});

async function receivePage(fid){const [F,r]=await Promise.all([api('/api/intake/fields'),api(`/api/request-forms/${fid}/read`,{})]);
 const s1=F.fields.filter(f=>f.sheet==1),s2=F.fields.filter(f=>f.sheet==2),v=r.values,open=r.status=='received';
 $('#app').innerHTML=`<button class="back" onclick="go('intake')">&larr; Customer requests</button>`+head(`Customer request ${fid}`,`Sent ${esc(r.at.replace('T',' ').slice(0,16))} and signed by ${esc(v.signed_name||'')}. The customer's answers are shown as sent; the laboratory does not change them.`+(open?'':''))+
  (open?'':`<div class="ib ${r.status=='returned'?'no':'ok'}" style="margin-bottom:16px"><span>${r.status=='used'?`Already accepted${r.job?`: job <b>${esc(r.job.series)}</b>`:''}.`:r.status=='returned'?`Returned to the customer${r.note?`: ${esc(r.note)}`:''}.`:r.status=='replaced'?'Replaced by a corrected request from the customer.':'Status: '+esc(r.status)}</span>${r.job?`<a class="btn g s" href="#/job/${r.job.id}">Open the job</a>`:''}</div>`)+
  (r.problems.length?`<div class="errs"><b>This request has problems the customer must correct</b><ul>${r.problems.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></div>`:'')+
  `<div class="qf">${qHead(F,1)}${qFields(s1,v,'v_',true,F,{tests:`<div class="qr"><div class="ql">Tests ticked by the customer</div><div class="qc">:</div><div class="qv">${r.plan.map(k=>esc(F.tests[k]||k)).join(', ')||'-'}</div></div>`})}</div>
  <div class="qf">${qHead(F,2)}${qFields(s2,v,'v_',true,F)}<div class="qsig"><div></div><div style="text-align:right">Customers Name &amp; Signature with Date<br><b>${esc(v.signed_name||'')}</b> &middot; ${esc(String(v.signed_at||r.at).slice(0,10))}</div></div></div>`+
  (open?labBlock(F,{condition:'Suitable for Testing',capability:'Yes'},null,r.plan,true)+
   `<div id="iv"></div><div class="card" style="display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap"><button class="btn g" id="iret">Return to the customer</button><span style="display:flex;gap:10px"><button class="btn g" id="ick">Check for problems</button><button class="btn lg" id="isv">Accept request</button></span></div>`:'');
 if(!open)return;qWhen(F.lab,'l_',$('#app'));
 const body=()=>{const b={...labCollect(F),customer_form_id:fid,assign:{}};b.plan.forEach(k=>{if($('#as_'+k)&&$('#as_'+k).checked)b.assign[k]=ME.id});if($('#icw')&&$('#icw').checked)b.confirm_warnings=true;return b};
 const show=x=>{const w=x.warnings||[],e=(x.errors||x.error||[]).filter(m=>!/^Confirm: /.test(m));
  $('#iv').innerHTML=qProblems(e,[],'Nothing missing, nothing wrong.')+(w.length?`<div class="warns"><b>Please confirm</b><ul>${w.map(m=>`<li>${esc(m)}</li>`).join('')}</ul><label style="display:flex;gap:8px;align-items:center;margin-top:8px;font-weight:600"><input type="checkbox" id="icw"> I have checked these with the customer</label></div>`:'')};
 $('#ick').onclick=async()=>{try{show(await api('/api/intake/check',body()))}catch(e){toast(e,1)}};
 $('#isv').onclick=async()=>{const b=body();try{const x=await api('/api/intake',b);toast(`Request accepted: series ${x.series} and sample ${x.sample} assigned`);go('job/'+x.id)}
  catch(e){try{show(await api('/api/intake/check',b))}catch(_){toast(e,1)}scrollTo(0,$('#iv').offsetTop-80)}};
 $('#iret').onclick=async()=>{const why=prompt('What must the customer correct? They see this reason.');if(!why)return;
  try{await api(`/api/request-forms/${fid}/return`,{reason:why});toast('Returned to the customer');go('intake')}catch(e){toast(e,1)}}}

/* an existing job: the customer's request as held, the laboratory's part to record or correct, and (if the job has no
   request yet, e.g. it was opened from a data file) a waiting customer request to link */
async function jobIntakePage(id){const [F,j,inbox]=await Promise.all([api('/api/intake/fields'),api('/api/jobs/'+id),api('/api/request-forms')]);
 const rq=j.data.request||{},has=!!rq.signed_name,it=j.intake||{},waiting=inbox.filter(f=>f.status=='received');
 $('#app').innerHTML=`<button class="back" onclick="go('job/${id}')">&larr; ${esc(j.series)}</button>`+head('Intake details',`The customer's request for ${esc(j.series)} and the laboratory's part (sheet 3). The report is a legal document: the intake must be complete and checked before release.`)+
  (has?`<details class="card"><summary><b>Customer's request (as sent, signed by ${esc(rq.signed_name)})</b></summary>${['1','2'].map(n=>`<div class="qf" style="margin-top:12px">${qHead(F,n)}${qFields(F.fields.filter(f=>f.sheet==n),rq,'v_',true,F)}</div>`).join('')}</details>`
   :`<div class="card"><h2>Customer's request</h2><p class="note">This job holds no request raised by the customer. Link the customer's waiting request to it${waiting.length?'':' (none is waiting: ask the customer to raise one from their portal)'}.</p>${waiting.length?`<select id="ifid"><option value="">Choose the customer's request...</option>${waiting.map(f=>`<option value="${f.id}">${esc(f.org||'')} &middot; request ${f.id} &middot; ${esc(f.sample||'')} ${esc(f.rating||'')}</option>`).join('')}</select>`:''}</div>`)+
  labBlock(F,it,null,j.plan||[],false)+
  `<div id="iv"></div><div class="card" style="display:flex;justify-content:flex-end;gap:10px;flex-wrap:wrap"><button class="btn lg" id="isv">Save intake details</button></div>`;
 qWhen(F.lab,'l_',$('#app'));
 const body=()=>{const b={...labCollect(F),arrived_at:it.arrived_at};const s=$('#ifid');if(s&&s.value)b.customer_form_id=+s.value;if($('#icw')&&$('#icw').checked)b.confirm_warnings=true;return b};
 const show=x=>{const w=x.warnings||[],e=(x.errors||x.error||[]).filter(m=>!/^Confirm: /.test(m));
  $('#iv').innerHTML=qProblems(e,[],'Nothing missing, nothing wrong.')+(w.length?`<div class="warns"><b>Please confirm</b><ul>${w.map(m=>`<li>${esc(m)}</li>`).join('')}</ul><label style="display:flex;gap:8px;align-items:center;margin-top:8px;font-weight:600"><input type="checkbox" id="icw"> I have checked these with the customer</label></div>`:'')};
 $('#isv').onclick=async()=>{try{await api(`/api/jobs/${id}/intake`,body());toast('Intake details saved');go('job/'+id)}catch(e){show({error:[].concat(e)});scrollTo(0,$('#iv').offsetTop-80)}}}
