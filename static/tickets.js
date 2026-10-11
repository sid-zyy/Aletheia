/* Customer tickets: a customer raises a ticket (optionally about one of their jobs); it goes to the administrators, who
   answer in the same thread and close it. Customers see the laboratory's replies signed by the laboratory, never staff names.
   Uses the helpers in index.html: $, esc, api, go, head, toast. */
const TST={open:['uploaded','Waiting for the laboratory'],answered:['verified','Answered'],closed:['na','Closed']};
const tStatus=s=>{const [c,t]=TST[s]||['uploaded',s];return `<span class="pst ${c}">${isCust()?T(t):{open:'Open: to answer',answered:'Answered',closed:'Closed'}[s]||s}</span>`};

const tickets=()=>{const p=location.hash.slice(2).split('?')[0].split('/');return p[1]=='new'?ticketNew(+p[2]||null):p[1]?ticketPage(+p[1]):ticketsPage()};
async function ticketsPage(){const st=(location.hash.split('?')[1]||'').replace('status=',''),r=await api('/api/tickets'+(st?'?status='+st:'')),cust=isCust();
 const f=(k,l)=>`<a class="btn ${st==k?'':'g'} s" href="#/tickets${k?'?status='+k:''}">${T(l)}</a>`;
 $('#app').innerHTML=head(cust?T('Tickets'):'Customer tickets',cust?T('Ask the laboratory a question or report a problem. The laboratory answers here; you are notified of every answer.'):'Questions and problems raised by customers. Answer them here; the customer is notified. Open tickets are waiting for you.',
   cust?`<a class="btn" href="#/tickets/new">${T('Raise a ticket')}</a>`:'')+
  `<div class="card"><div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px">${f('','All')}${f('open',cust?'Waiting for the laboratory':'Open')}${f('answered','Answered')}${f('closed','Closed')}</div>
   <div class="tb">${r.tickets.length?r.tickets.map(t=>`<div class="row" style="grid-template-columns:1.8fr 1.2fr 1fr 190px" tabindex="0" onclick="go('tickets/${t.id}')">
    <div><b>${esc(t.subject)}</b><span class="m">${T('Ticket {id}',{id:t.id})} &middot; ${esc(T(t.category))}${t.series?' &middot; '+esc(t.series):''}</span></div>
    <div>${cust?'':`<b>${esc(t.org||'')}</b>`}<span class="m">${t.messages==1?T('1 message'):T('{n} messages',{n:t.messages})}</span></div><div class="m">${esc(t.updated_at.replace('T',' ').slice(0,16))}</div><div>${tStatus(t.status)}</div></div>`).join('')
    :`<div class="empty">${cust?T('No tickets yet. Raise one if you have a question about a request, a job or a report.'):'No tickets here.'}</div>`}</div></div>`}

async function ticketNew(jobId){const [r,jobs]=await Promise.all([api('/api/tickets'),api('/api/jobs')]);
 $('#app').innerHTML=`<button class="back" onclick="go('tickets')">&larr; ${T('Tickets')}</button>`+head(T('Raise a ticket'),T("It goes to the laboratory's administrators. Describe the question or problem; mention the request or report it concerns."))+
  `<div class="card"><div class="frm"><div class="row2"><div><label for="tk_cat">${T('What is it about?')}<span style="color:var(--er)"> *</span></label><select id="tk_cat"><option value="">${T('Choose...')}</option>${r.categories.map(c=>`<option value="${esc(c)}">${esc(T(c))}</option>`).join('')}</select></div>
   <div><label for="tk_job">${T('Job (optional)')}</label><select id="tk_job"><option value="">${T('Not about one job')}</option>${jobs.map(j=>`<option value="${j.id}" ${j.id==jobId?'selected':''}>${esc(j.series)} &middot; ${esc(j.rating||'')}</option>`).join('')}</select></div></div>
   <div><label for="tk_sub">${T('Subject')}<span style="color:var(--er)"> *</span></label><input class="in" id="tk_sub" maxlength="150" placeholder="${T('In a few words')}"></div>
   <div><label for="tk_msg">${T('Message')}<span style="color:var(--er)"> *</span></label><textarea id="tk_msg" rows="7" style="width:100%;font:inherit;padding:10px;border:1px solid var(--ln);border-radius:8px;background:var(--bg);color:var(--tx)"></textarea></div></div>
   <div style="display:flex;justify-content:flex-end;gap:10px;margin-top:14px"><button class="btn g" onclick="go('tickets')">${T('Cancel')}</button><button class="btn" id="tk_send">${T('Send to the laboratory')}</button></div></div>`;
 $('#tk_send').onclick=async()=>{try{const x=await api('/api/tickets',{category:$('#tk_cat').value,job_id:+$('#tk_job').value||null,subject:$('#tk_sub').value,message:$('#tk_msg').value});toast(T('Ticket sent to the laboratory'));go('tickets/'+x.id)}catch(e){toast(e,1)}}}

async function ticketPage(id){const t=await api('/api/tickets/'+id),cust=isCust();
 $('#app').innerHTML=`<button class="back" onclick="go('tickets')">&larr; ${T('Tickets')}</button>`+head(esc(t.subject),`${T('Ticket {id}',{id:t.id})} &middot; ${esc(T(t.category))}${t.series?` &middot; ${T('job')} <a class="lk" style="padding:0" href="#/${cust?'my':'job'}/${t.job_id}">${esc(t.series)}</a>`:''}${cust?'':` &middot; ${esc(t.org||'')}`} &middot; ${T('raised {at}',{at:esc(t.created_at.replace('T',' ').slice(0,16))})}`,tStatus(t.status))+
  `<div class="card">${t.messages.map(m=>`<div style="padding:12px 14px;margin-bottom:10px;border-radius:10px;border:1px solid var(--ln);background:${m.from_lab?'var(--cd2)':'var(--cd)'}">
    <div style="display:flex;justify-content:space-between;gap:10px;font-size:13px;margin-bottom:6px"><b>${esc(m.from_lab?T(m.author||''):m.author||'')}${m.from_lab&&!cust?' (laboratory)':''}</b><span class="m">${esc(m.at.replace('T',' ').slice(0,16))}</span></div>
    <div style="white-space:pre-wrap">${esc(m.body)}</div></div>`).join('')}
   <label for="tk_rep" style="margin-top:8px">${T(t.status=='closed'?'Reply (re-opens the ticket)':'Reply')}</label><textarea id="tk_rep" rows="4" style="width:100%;font:inherit;padding:10px;border:1px solid var(--ln);border-radius:8px;background:var(--bg);color:var(--tx)"></textarea>
   <div style="display:flex;justify-content:flex-end;gap:10px;margin-top:12px">${t.status=='closed'?(cust?'':`<button class="btn g" id="tk_re">Re-open</button>`):`<button class="btn g" id="tk_close">${T('Close the ticket')}</button>`}<button class="btn" id="tk_send">${T('Send reply')}</button></div></div>`;
 $('#tk_send').onclick=async()=>{try{await api(`/api/tickets/${id}/messages`,{message:$('#tk_rep').value});toast(T('Reply sent'));ticketPage(id)}catch(e){toast(e,1)}};
 if($('#tk_close'))$('#tk_close').onclick=async()=>{try{await api(`/api/tickets/${id}/close`,{});toast(T('Ticket closed'));ticketPage(id)}catch(e){toast(e,1)}};
 if($('#tk_re'))$('#tk_re').onclick=async()=>{try{await api(`/api/tickets/${id}/reopen`,{});ticketPage(id)}catch(e){toast(e,1)}}}
