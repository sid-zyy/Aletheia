/* Aletheia assistant: a rule-based helper (no AI model). It matches keywords in what the user types and drives the
   same API and pages as the rest of the app: open the customer requests, search records, list open jobs, show status, explain
   the workflow. Uses the helpers defined in index.html: $, esc, api, go, badge, ST.
   Staff and customers each get their own version (customers: their jobs, a new request, a ticket). It is built again whenever
   the page is rebuilt (signing in, switching roles), so it is always there. */
let box,log,inp,panel,opener,flow=null,started=false;
function assistantMount(){
if(document.getElementById('cb')&&box&&document.body.contains(box))return;
box=document.createElement('div');box.id='cb';flow=null;started=false;
box.innerHTML=`<button class="cbf" id="cbo" aria-expanded="false" aria-controls="cbp" aria-label="Open the assistant">
 <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7.9 20A9 9 0 1 0 4 16.1L2 22z"/><path d="M8 12h.01M12 12h.01M16 12h.01" stroke-width="2.6"/></svg></button>
 <section class="cbp" id="cbp" role="dialog" aria-label="Aletheia assistant" hidden>
  <header><div><b>Aletheia assistant</b><span>${isCust()?'Your jobs, requests and reports':'Reports, records and help'}</span></div><button class="cbx" id="cbc" aria-label="Close the assistant">&times;</button></header>
  <div class="cbl" id="cbl" aria-live="polite"></div>
  <div class="cbq" id="cbq"></div>
  <form class="cbi" id="cbf"><input id="cbt" autocomplete="off" placeholder="${isCust()?'Ask, or type a series or sample number':'Ask, or type a series, customer or sample'}" aria-label="Message the assistant"><button class="btn s" aria-label="Send">Send</button></form>
 </section>`;
document.body.append(box);
log=$('#cbl');inp=$('#cbt');panel=$('#cbp');opener=$('#cbo');
opener.onclick=()=>toggle(panel.hidden);$('#cbc').onclick=()=>toggle(false);
panel.addEventListener('keydown',e=>{if(e.key=='Escape'&&!$('#ov')){e.stopPropagation();toggle(false)}});
$('#cbf').onsubmit=e=>{e.preventDefault();const t=inp.value.trim();if(!t)return;inp.value='';say(esc(t),'me');send(t)};
panel.addEventListener('click',e=>{const j=e.target.closest('[data-job]'),a=e.target.closest('[data-a]');
 if(j)return go((isCust()?'my/':'job/')+j.dataset.job);
 if(a){const label=a.textContent;$('#cbq').innerHTML='';send(label,a.dataset.a)}})}

/* ---------- rendering */
const say=(html,who='bot')=>{const m=document.createElement('div');m.className='cbm '+who;m.innerHTML=html;log.append(m);log.scrollTop=log.scrollHeight;return m};
const chips=list=>{$('#cbq').innerHTML=list.map(([t,a])=>`<button type="button" data-a="${esc(a)}">${esc(t)}</button>`).join('');log.scrollTop=log.scrollHeight};
const STAFF_MAIN=[['Customer requests','requests'],['Search records','search'],['In progress','pending'],['Status summary','status'],['How it works','how']];
const CUST_MAIN=[['My jobs','myjobs'],['Released reports','reports'],['New test request','newreq'],['Raise a ticket','ticket'],['How it works','how']];
let MAIN=STAFF_MAIN;
const think=async()=>{const t=say('<i class="cbd"></i><i class="cbd"></i><i class="cbd"></i>');
 await new Promise(r=>setTimeout(r,matchMedia('(prefers-reduced-motion: reduce)').matches?0:350));t.remove()};
const jobRow=j=>`<button type="button" class="cbj" data-job="${j.id}"><b>${esc(j.series)}</b><span>${isCust()?'Sample '+esc(j.sample):esc(j.customer)} &middot; ${esc(j.rating)}</span>${isCust()?`<span class="st ${j.stage==4?'s4':'s1'}">${j.stage==4?'Report released':'In progress'}</span>`:badge(j)}</button>`;
const jobList=(l,more)=>l.slice(0,5).map(jobRow).join('')+(l.length>5?`<button type="button" class="lk" data-a="${esc(more)}">Show all ${l.length} in Records &amp; Search</button>`:'');

/* ---------- answers */
async function search(term){
 if(!term){flow={search:1};say('What should I look for? A series number, sample code, customer or rating all work.');return chips([['Cancel','cancel']])}
 const l=await api('/api/jobs?q='+encodeURIComponent(term));
 if(!l.length){say(`No records match <b>${esc(term)}</b>.`);return chips([['Customer requests','requests'],['Search again','search'],['Import an old register','register']])}
 say(`${l.length} record${l.length==1?'':'s'} match <b>${esc(term)}</b>:`+jobList(l,'all:'+term));chips(MAIN)}
async function pending(){const l=(await api('/api/jobs')).filter(j=>j.stage<4&&!j.archived);
 if(!l.length){say('Nothing is in progress: every record has been approved.');return chips(MAIN)}
 say(`${l.length} report${l.length==1?' is':'s are'} still in progress (most recently updated first):`+jobList(l,'records'));chips(MAIN)}
async function status(){const s=await api('/api/stats');
 if(!s.total){say('There are no records yet. A job starts when a customer raises a test request and the laboratory receives it.');return chips([['Customer requests','requests'],['How it works','how']])}
 say(`<b>${s.total}</b> record${s.total==1?'':'s'} in total:<dl class="cbs">${ST.map((n,i)=>`<dt>${esc(n)}</dt><dd>${s.by_stage[i]}</dd>`).join('')}</dl>`+
  (s.historical?`Plus <b>${s.historical}</b> historical record${s.historical==1?'':'s'} imported from registers. `:'')+
  (s.turnaround_h?`From request to release takes ${dur(s.turnaround_h.avg)} on average (${s.turnaround_h.n} released). `:'')+
  (s.avg_gen_ms!=null?`Building the PDF itself takes about ${s.avg_gen_ms} ms.`:''));chips(MAIN)}
const HELP={
 how:`A report goes through five steps:<ol class="cbo"><li><b>Request captured</b>: series, sample, customer and rating.</li><li><b>Data imported</b>: log sheets as CSV, Excel, JSON or a database, or scans read and checked by hand.</li><li><b>Validated</b>: the checks compare every value with the documented limits (IS 1180 references) and the proforma.</li><li><b>Report ready</b>: once every flagged item is reviewed, the PDF is generated.</li><li><b>Approved</b>: a reviewer approves and releases it, giving their name and employee ID.</li></ol>`,
 import:`Open the job and drop its files on the upload area. Data files (CSV, Excel, JSON, SQLite) are imported directly. PDFs and photos are attached as source documents; you can type their values in, or ask the scan reader for a proposal you check before saving. A blank template is under <b>Records &amp; Search</b>.`,
 checks:`<b>Run checks</b> compares the data with the limits. A <b>data error</b> (for example an average that does not match its readings) blocks the report until it is corrected. A <b>requirement not met</b> is a result: confirm the reading and the report states that the sample does not comply. <b>Review</b> items must each be marked as reviewed, one by one, before the report can be built. They are listed in the report.`,
 approve:`When the report is generated, open the job, check the preview, enter your name and <b>employee ID</b> (both are required and are printed on the report) and click <b>Approve and release</b>. The test engineer named on the report cannot approve it. Then copy the customer link and send it to the customer: they can verify and download the report. Every step is recorded in the job history.`,
 verify:`Each approved report carries a verification link and code. Opening it shows whether the PDF matches the one the lab issued, so changed copies can be detected.`,
 register:`Under <b>Records &amp; Search</b>, use <b>Import existing register</b> to bring in older records from a CSV, Excel or SQLite file. Download the register template there to see the expected columns.`,
 help:`I can help you:<ul class="cbo"><li>open the <b>customer requests</b> waiting for intake</li><li><b>search</b> records by series, sample code, customer or rating</li><li>list reports <b>in progress</b> and give a <b>status summary</b></li><li>explain importing, checks, approval and verification</li><li>open a page: dashboard, records, preview or architecture</li></ul>I match keywords rather than understanding full sentences, so short requests work best.`};
const PAGES=[[/dashboard|home/,'dashboard','the dashboard'],[/records?|archive/,'records','Records & Search'],[/preview|pdf/,'preview','Report Preview'],[/architect/,'arch','the architecture page'],[/workflow/,'workflow','Report Workflow']];

/* ---------- the customer's assistant: only their own organisation's jobs, through the same pages */
const CUST_HELP={
 how:`How your test job goes:<ol class="cbo"><li><b>Raise a test request</b> online (the Customer Request Form). The laboratory checks it; if something is missing it is returned to you with the reason.</li><li>When your sample arrives, the laboratory <b>accepts the request</b> and gives the job its series number.</li><li>The tests are carried out and checked. On each job you see which tests are approved, and their values, as soon as they are approved.</li><li>When the <b>final report is released</b> you are notified; download it from the job, and anyone can check it is genuine with its verification link.</li></ol>`,
 help:`I can:<ul class="cbo"><li>list <b>your jobs</b> and show their progress</li><li>find a job by its <b>series or sample number</b></li><li>show your <b>released reports</b></li><li>open a <b>new test request</b> or <b>raise a ticket</b> to the laboratory</li></ul>`};
async function custJobs(term,released){let l=await api('/api/jobs'+(term?'?q='+encodeURIComponent(term):''));if(released)l=l.filter(j=>j.stage==4);
 if(!l.length){say(term?`None of your jobs match <b>${esc(term)}</b>.`:released?'No report has been released yet. You are notified when one is.':'You have no jobs yet. A job starts when the laboratory accepts your test request.');return chips(CUST_MAIN)}
 say((released?`${l.length} released report${l.length==1?'':'s'} (open a job to download it):`:term?`${l.length} job${l.length==1?'':'s'} match <b>${esc(term)}</b>:`:`Your ${l.length} job${l.length==1?'':'s'}, most recent first:`)+l.slice(0,6).map(jobRow).join(''));chips(CUST_MAIN)}
async function custHandle(t,click){const lo=t.toLowerCase();
 if(/^(hi|hello|hey|good (morning|afternoon|evening))\b/.test(lo)){say('Hello! What would you like to do?');return chips(CUST_MAIN)}
 if(lo=='newreq'||/\b(new|raise|send|submit)\b.*\brequest\b|\brequest\b.*\bnew\b/.test(lo)){say('Opening a new test request.');return go('my/request')}
 if(lo=='ticket'||/\b(ticket|problem|complain\w*|question|contact|query)\b/.test(lo)){say('Opening a new ticket to the laboratory.');return go('tickets/new')}
 if(lo=='reports'||/\b(released|download|final report|certificate)\b/.test(lo))return custJobs('',true);
 if(lo=='myjobs'||/\b(my jobs?|jobs?|progress|status|pending|open)\b/.test(lo))return custJobs('');
 if(/\b(how|steps?|process|works?)\b/.test(lo)){say(CUST_HELP.how);return chips(CUST_MAIN)}
 if(/\b(help|what can you|options|menu)\b/.test(lo)){say(CUST_HELP.help);return chips(CUST_MAIN)}
 const term=searchTerm(t);if(term)return custJobs(term);
 say('Sorry, I didn\'t understand that. Try one of these, or type <i>help</i>.');chips(CUST_MAIN)}

/* ---------- routing what the user typed or clicked */
/* words dropped from a search, compared one word at a time so names like "A.P. Transformers" stay intact */
const STOP=new Set('please can could would you i want to what about is are there where which do does have has my get search for find look up show me open the a an by with of any all record records report reports job jobs customer series sample code number'.split(' '));
const searchTerm=t=>t.split(/\s+/).map(w=>w.replace(/^["'(]+|[?!,"')]+$/g,'').replace(/^([^.]+)\.$/,'$1')).filter(w=>w&&!STOP.has(w.toLowerCase())).join(' ');
async function handle(t,click){t=t.trim();if(!t)return;const lo=t.toLowerCase();
 if(isCust())return custHandle(t,click);
 if(lo=='cancel'){flow=null;say('Cancelled. What would you like to do?');return chips(MAIN)}
 if(flow&&flow.search){flow=null;return search(t)}
 flow=null;
 if(lo.startsWith('all:')){q=t.slice(4);sg='';return go('records')}
 if(lo=='requests'||/\b(new|create|start|begin|add|request|intake)\b/.test(lo)){say('Only a customer raises a test request, from their portal. Opening the customer requests waiting for intake.');return go('intake')}
 if(/^(hi|hello|hey|good (morning|afternoon|evening))\b/.test(lo)){say('Hello! What would you like to do?');return chips(MAIN)}
 if(/\b(status|summary|stats?|how many|overview|count)\b/.test(lo))return status();
 if(/\b(pending|in progress|progress|open jobs|unfinished|outstanding|to ?do|waiting|ongoing)\b/.test(lo))return pending();
 if(/\bregister|old records|legacy\b/.test(lo)){say(HELP.register);return chips([['Go to Records','records'],...MAIN.slice(0,2)])}
 if(/\b(import|upload|log ?sheets?|scans?|files?)\b/.test(lo)){say(HELP.import);return chips(MAIN)}
 if(/\b(checks?|validat\w*|flag\w*|fail\w*|warn\w*|mark as reviewed)\b/.test(lo)){say(HELP.checks);return chips(MAIN)}
 if(/\b(approv\w*|release|sign)\b/.test(lo)){say(HELP.approve);return chips(MAIN)}
 if(/\b(verif\w*|authentic\w*|qr|tamper\w*)\b/.test(lo)){say(HELP.verify);return chips(MAIN)}
 if(/\b(how|steps?|process|workflow works)\b/.test(lo)&&!/\bsearch|find\b/.test(lo)){say(HELP.how);return chips(MAIN)}
 if(/\b(help|what can you|options|menu)\b/.test(lo)){say(HELP.help);return chips(MAIN)}
 const pg=!/\b(search|find|look)\b/.test(lo)&&PAGES.find(([re])=>re.test(lo));
 if(pg&&(click||/\b(go|open|show|take me)\b/.test(lo)||lo.split(/\s+/).length<=2)){say(`Opening ${esc(pg[2])}.`);return go(pg[1])}
 const term=searchTerm(t);
 if(/\b(search|find|look ?up)\b/.test(lo))return search(term);
 /* anything else: treat it as a search, and say so */
 const l=term?await api('/api/jobs?q='+encodeURIComponent(term)):[];
 if(l.length){say(`I searched the records for <b>${esc(term)}</b>:`+jobList(l,'all:'+term));return chips(MAIN)}
 say(`Sorry, I didn't understand that${term?`, and no records match <b>${esc(term)}</b>`:''}. Try one of these, or type <i>help</i>.`);chips(MAIN)}

async function send(t,click){if(click)say(esc(t),'me');
 try{await think();await handle(click?click:t,!!click)}catch(e){say(`Something went wrong: ${esc([].concat(e).join(' '))}`);chips(MAIN)}}
function toggle(open){panel.hidden=!open;opener.setAttribute('aria-expanded',open);box.classList.toggle('on',open);
 if(open&&!started){started=true;MAIN=isCust()?CUST_MAIN:STAFF_MAIN;
  say(isCust()?'Hello, I\'m the Aletheia assistant. I can show your jobs and released reports, open a new test request, or raise a ticket to the laboratory.'
   :'Hello, I\'m the Aletheia assistant. I can open the customer requests, find existing reports, or explain how the app works.');chips(MAIN)}
 if(open)inp.focus();else opener.focus()}

/* a press anywhere outside the assistant minimises it; pointerdown runs before the chat re-renders its own buttons */
document.addEventListener('pointerdown',e=>{if(panel&&!panel.hidden&&!box.contains(e.target))toggle(false)});
