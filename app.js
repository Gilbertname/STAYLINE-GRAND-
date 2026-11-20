"use strict";
const $ = (selector, base=document) => base.querySelector(selector);
const state = {user: "", csrf: "", today: "", page: "dashboard", dashboard: null, rooms: [], guests: [], reservations: [], payments: [], role: "admin", ops: {}};
const labels = {dashboard:"營運總覽",reservations:"訂房管理",rooms:"客房管理",guests:"房客管理",payments:"收款紀錄",reports:"營運報表",employees:"員工與權限",schedules:"排班與請假",training:"員工培訓",payroll:"薪資管理",services:"客房服務",tickets:"顧客客服",requests:"入住／退房申請",attendance:"員工打卡",housekeeping:"房務清潔"};
const typeNames = {standard:"標準客房",deluxe:"豪華客房",suite:"行政套房"};
const hkNames = {clean:"已清潔",dirty:"待清潔",cleaning:"清潔中"};
const statusNames = {reserved:"已預訂",checked_in:"已入住",checked_out:"已退房",cancelled:"已取消"};
const payNames = {cash:"現金",card:"信用卡",transfer:"轉帳"};
const esc = value => String(value ?? "").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"})[c]);
const money = n => "NT$ " + Number(n || 0).toLocaleString("zh-TW");
const dateShort = value => value ? esc(value.slice(5).replace("-","/")) : "—";
const todayISO = () => state.today || new Date().toISOString().slice(0,10);
const nextDate = (s, days=1) => {const [y,m,d]=s.split("-").map(Number);return new Date(Date.UTC(y,m-1,d+days)).toISOString().slice(0,10)};
function toast(message, bad=false){
  const node=document.createElement("div");node.className="toast"+(bad?" error":"");node.textContent=message;$("#toastRoot").appendChild(node);setTimeout(()=>node.remove(),4200);
}
async function api(path,opts={}){
  const method=opts.method || "GET";
  const res=await fetch(path,{credentials:"same-origin",...opts,headers:{...(method!=="GET"?{"Content-Type":"application/json","X-CSRF-Token":state.csrf}:{}),...(opts.headers||{})}});
  let data;try{data=await res.json()}catch{throw Error("伺服器回應格式錯誤")}
  if(!res.ok){throw Error(data.error || "請求失敗")}
  return data;
}
const body = data => JSON.stringify(data);
async function init(){
  bindGlobalEvents();
  try{
    const me=await api("/api/me");await activate(me)
  }catch(error){toast("展示資料初始化失敗："+error.message,true)}
}
function showLogin(){toast("展示版已取消登入",true)}
function showAuth(setup){
  $("#appRoot").classList.add("hidden");$("#authRoot").classList.remove("hidden");
  $("#authContent").innerHTML=`<div class="auth-overline">WELCOME TO STAYLINE GRAND</div>
      <h2>${setup?"建立管理員帳號":"歡迎回來"}</h2>
      <p>${setup?"首次使用，請設定登入帳號及密碼。資料會安全儲存在本機資料庫。":"登入飯店管理後台，開始今天的營運工作。"}</p>
      <form id="authForm">
       <div class="field"><label for="authUser">管理員帳號</label><input name="username" id="authUser" autocomplete="username" required minlength="3" maxlength="40" placeholder="例如：admin"></div>
       <div class="field"><label for="authPass">密碼</label><input name="password" id="authPass" type="password" autocomplete="${setup?"new-password":"current-password"}" minlength="8" maxlength="128" required placeholder="${setup?"至少 8 個字元":"請輸入登入密碼"}"></div>
       ${setup?`<div class="field"><label for="confirmPassword">再次輸入密碼</label><input id="confirmPassword" type="password" autocomplete="new-password" minlength="8" required placeholder="確認管理員密碼"></div>`:""}
       <div id="authError"></div><button class="btn btn-primary" type="submit">${setup?"建立帳號並開始使用":"登入管理後台"} →</button>
      </form><div class="auth-note">私人本機版 · 沒有預設帳號密碼<br>請妥善保管資料庫與管理員密碼。</div>`;
  $("#authForm").addEventListener("submit",async ev=>{
    ev.preventDefault();const form=ev.currentTarget;
    const u=form.elements.namedItem("username").value.trim(),p=form.elements.namedItem("password").value;
    if(setup && p!==$("#confirmPassword").value){$("#authError").innerHTML='<div class="error-banner">兩次密碼不一致</div>';return}
    const btn=$("button[type=submit]",form);btn.disabled=true;
    try{const ret=await api(setup?"/api/setup":"/api/login",{method:"POST",body:body({username:u,password:p})});activate(ret);}
    catch(e){$("#authError").innerHTML=`<div class="error-banner">${esc(e.message)}</div>`}
    finally{btn.disabled=false}
  });
}
async function activate(info){
  state.user=info.username;state.role=info.role || "admin";state.csrf=info.csrf;state.today=info.today || todayISO();
  document.querySelectorAll("[data-page]").forEach(b=>{
    const page=b.dataset.page;
    b.classList.toggle("hidden",state.role==="housekeeping"&&!(["services","housekeeping","attendance"].includes(page)) || state.role!=="admin"&&page==="payroll");
  });
  $("#authRoot").classList.add("hidden");$("#appRoot").classList.remove("hidden");
  $("#usernameLabel").textContent=state.user;$("#todayLabel").textContent=`${state.today.replaceAll("-"," / ")}`;
  await refresh();
  navigate(state.role==="housekeeping"?"services":"dashboard");
}
async function refresh(){
  try{
    if(state.role==="housekeeping"){
      state.ops=await api("/api/ops/overview");
    }else{
      const [dashboard,rooms,guests,reservations,payments,ops]=await Promise.all([api("/api/dashboard"),api("/api/rooms"),api("/api/guests"),api("/api/reservations"),api("/api/payments"),api("/api/ops/overview")]);
      Object.assign(state,{dashboard,rooms,guests,reservations,payments,ops});
    }
  }catch(e){toast(e.message,true);throw e}
}
async function mutation(path,method="POST",value=null){
  try{await api(path,{method,...(value!==null?{body:body(value)}:{body:"{}"})});await refresh();render();toast("資料已成功更新");return true}
  catch(e){toast(e.message,true);return false}
}
function navigate(page){
  state.page=page;
  document.querySelectorAll("[data-page]").forEach(b=>b.classList.toggle("active",b.dataset.page===page));
  $("#topPage").textContent=labels[page];render();
}
function header(tag,title,desc,actions=""){
 return `<div class="page-header"><div><div class="eyebrow">${tag}</div><h1>${title}</h1><p class="subhead">${desc}</p></div><div class="header-actions">${actions}</div></div>`;
}
function kpi(label,value,hint,ico){return `<div class="kpi"><div class="kpi-top"><span class="kpi-label">${label}</span><span class="kpi-icon">${ico}</span></div><strong>${value}</strong><small>${hint}</small></div>`}
function tag(status){return `<span class="badge badge-${esc(status)}">${esc(statusNames[status]||hkNames[status]||status)}</span>`}
function empty(label="目前沒有資料",hint="新增資料後就會顯示在這裡。"){return `<div class="empty"><div class="empty-icon">✧</div><strong>${label}</strong>${hint}</div>`}
function table(headers,rows,emptyTitle="目前沒有紀錄"){
 return rows.length?`<div class="table-scroll"><table class="data-table"><thead><tr>${headers.map(h=>`<th>${h}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div><div class="record-count">共 ${rows.length} 筆資料</div>`:empty(emptyTitle);
}
function applyFilters(container){
 const needle=($("[data-search-input]",container)?.value||"").trim().toLocaleLowerCase();
 const active=$("[data-filter].active",container)?.dataset.filter||"all";
 let seen=0;
 container.querySelectorAll("tbody tr").forEach(tr=>{
  const searchText=(tr.dataset.search||tr.textContent).toLocaleLowerCase();
  const ok=searchText.includes(needle)&&(active==="all"||tr.dataset.status===active);
  tr.hidden=!ok;if(ok)seen++;
 });
 const count=$(".record-count",container);if(count)count.textContent=`顯示 ${seen} 筆資料`;
}
function filterTable(container){const input=$("[data-search-input]",container);
 if(input)input.addEventListener("input",()=>applyFilters(container));
}
function reservationRow(r,mini=false){
 const name=esc(r.guest_name),code=esc(r.code);
 return `<tr data-status="${esc(r.status)}" data-search="${code} ${name} ${esc(r.room_number)} ${esc(statusNames[r.status])}"><td class="primary-cell">${code}</td><td><strong>${name}</strong><div class="detail-hint">${esc(r.guest_phone||"尚無電話")}</div></td><td class="primary-cell">${esc(r.room_number)} <span class="detail-hint">${typeNames[r.room_type]}</span></td><td>${dateShort(r.check_in)} — ${dateShort(r.check_out)}</td>${mini?"":`<td class="money-cell">${money(r.bill_amount??r.total_amount)}<div class="detail-hint">已付 ${money(r.paid_amount)}${r.bill_amount>r.total_amount?` · 含服務費 ${money(r.bill_amount-r.total_amount)}`:""}</div></td>`}<td>${tag(r.status)}</td>${mini?"":`<td><div class="actions">${reservationActions(r)}</div></td>`}</tr>`;
}
function reservationActions(r){
 const id=r.id;
 if(r.status==="reserved")return `<button class="btn-link" data-action="edit-reservation" data-id="${id}">編輯</button><button class="btn-link" data-action="pay" data-id="${id}">收款</button><button class="btn-link" data-action="check-in" data-id="${id}">入住</button><button class="btn-link" data-action="cancel" data-id="${id}">取消</button>`;
 if(r.status==="checked_in")return `<button class="btn-link" data-action="pay" data-id="${id}">收款</button><button class="btn-link" data-action="check-out" data-id="${id}">退房</button>`;
 return `<span class="muted-cell">—</span>`;
}
function revenueChart(){
 const series=state.dashboard.daily_revenue;
 const max=Math.max(1,...series.map(s=>s.amount));
 return `<div class="chart">${series.map(r=>`<div class="bar-col"><div class="bar-value">${r.amount?money(r.amount).replace("NT$ ",""):"·"}</div><div class="bar-track"><div class="bar-fill" style="height:${Math.max(1,Math.round(r.amount/max*100))}%"></div></div><small>${dateShort(r.date)}</small></div>`).join("")}</div>`;
}
function dashboardView(){
 const d=state.dashboard;
 const rows=d.recent.map(r=>reservationRow(r,true));
 return header("OVERVIEW / 營運概況","早安，歡迎回到星嶼","今日的營運資訊已為你整理完畢。",`<button class="btn btn-primary" data-action="add-reservation"><span class="plus">＋</span> 建立新訂房</button>`)
 +`<section class="hero"><div><span>STAYLINE GRAND · OPERATIONS</span><h2>讓每一場美好旅程，從這裡開始。</h2><p>管理客房、掌握訂房、照顧每位入住旅客。</p></div><button data-action="add-reservation">＋ 快速建立訂房</button></section>`
 +`<div class="kpi-grid">${kpi("啟用客房",d.room_count,"飯店開放預訂客房","▤")}${kpi("目前已入住",d.occupied,"實際入住中的客房","⌂")}${kpi("今日預計入住",d.arrivals_today,"已預訂且今日抵達","⇥")}${kpi("本月實收",money(d.monthly_revenue),"依實際付款日期計算","＄")}</div>`
 +`<div class="split-grid"><section class="panel"><div class="panel-header"><div><h2>近七日收款趨勢</h2><p>依實際入帳金額統計（NT$）</p></div><span class="smallprint">過去 7 天</span></div><div class="panel-body">${revenueChart()}</div></section><section class="panel"><div class="panel-header"><div><h2>客房使用概況</h2><p>依實際已入住客房計算</p></div></div><div class="panel-body"><div class="stats-number">${d.occupancy_rate}% <span class="smallprint">住房率</span></div><div class="progress-bar"><div class="progress-fill" style="width:${d.occupancy_rate}%"></div></div><div class="progress-meta"><span>已入住 ${d.occupied} 間</span><span>尚未入住 ${d.available_now} 間</span></div><div class="mini-stats"><div class="mini-stat"><span>今日預計退房</span><strong>${d.departures_today} 筆</strong></div><div class="mini-stat"><span>有效訂單未收款</span><strong>${money(d.outstanding)}</strong></div></div></div></section></div>`
 +`<section class="panel"><div class="panel-header"><div><h2>最近訂房</h2><p>最新建立的訂房紀錄</p></div><button class="btn-link" data-go="reservations">查看所有訂單 →</button></div>${table(["訂單編號","房客","房間","入住期間","狀態"],rows,"尚未有任何訂房紀錄")}</section>`;
}
function reservationsView(){
 const entries=state.reservations.map(r=>reservationRow(r));
 return header("BOOKINGS / RESERVATIONS","訂房管理","建立訂單、辦理入住退房，以及追蹤每筆付款狀態。",`<button class="btn btn-primary" data-action="add-reservation">＋ 新增訂房</button>`)
 +`<section class="panel"><div class="panel-header"><div><h2>訂單清單</h2><p>所有訂房和入住狀態</p></div></div><div class="table-controls"><div class="search-box"><input data-search-input placeholder="搜尋訂單、房客、房號"></div><div class="filter-tabs">${["all","reserved","checked_in","checked_out","cancelled"].map(s=>`<button class="filter-tab ${s==="all"?"active":""}" data-filter="${s}">${s==="all"?"全部":statusNames[s]}</button>`).join("")}</div></div>${table(["訂單編號","房客","客房","入住 / 退房","總金額 / 已付","狀態","操作"],entries,"尚無訂單，請建立第一筆訂房")}</section>`;
}
function roomsView(){
 return header("INVENTORY / ROOMS","客房管理","管理房型、價格、房間清潔狀態與是否可供預訂。",`<button class="btn btn-primary" data-action="add-room">＋ 新增客房</button>`)
 +`<div class="room-grid">${state.rooms.map(r=>`<article class="room-card"><div class="room-card-top"><span class="room-symbol">▤</span>${!r.enabled?'<span class="badge badge-inactive">已停用</span>':r.occupied?'<span class="badge badge-occupied">入住中</span>':tag(r.housekeeping)}</div><div class="room-number">${esc(r.number)}</div><div class="room-type">${typeNames[r.room_type]} · ${r.floor} 樓 · ${r.capacity} 人</div><div class="room-card-line"></div><div class="room-card-bottom"><div class="room-card-price">${money(r.price)}<small> / 晚</small></div></div><div class="room-card-actions"><span class="room-attrs">${hkNames[r.housekeeping]}${r.occupied?" · 已入住":""}</span><span><button class="btn-link" data-action="edit-room" data-id="${r.id}">編輯</button><button class="btn-link" data-action="delete-room" data-id="${r.id}">刪除</button></span></div></article>`).join("")}</div>`;
}
function guestsView(){
 const rows=state.guests.map(g=>`<tr data-search="${esc(g.full_name)} ${esc(g.phone)} ${esc(g.email)}"><td class="primary-cell">${esc(g.full_name)}</td><td>${esc(g.phone||"—")}</td><td>${esc(g.email||"—")}</td><td>${esc(g.document_no||"—")}</td><td class="muted-cell">${dateShort(g.created_at)}</td><td><div class="actions"><button data-action="edit-guest" data-id="${g.id}" class="btn-link">編輯</button><button data-action="delete-guest" data-id="${g.id}" class="btn-link">刪除</button></div></td></tr>`);
 return header("GUESTS / DIRECTORY","房客管理","儲存旅客資料，方便日後為同一位旅客再次訂房。",`<button class="btn btn-primary" data-action="add-guest">＋ 新增房客</button>`)
 +`<section class="panel"><div class="panel-header"><div><h2>房客名單</h2><p>旅客聯絡方式及識別資料</p></div></div><div class="table-controls"><div class="search-box"><input data-search-input placeholder="搜尋姓名、電話、信箱"></div></div>${table(["姓名","電話","電子郵件","證件號碼","建立日期","操作"],rows,"目前沒有房客資料")}</section>`;
}
function paymentsView(){
 const rows=state.payments.map(p=>`<tr data-search="${esc(p.reservation_code)} ${esc(p.guest_name)} ${esc(p.room_number)}"><td class="primary-cell">#${p.id}</td><td>${esc(p.paid_at)}</td><td class="primary-cell">${esc(p.reservation_code)}</td><td>${esc(p.guest_name)}</td><td>${esc(p.room_number)}</td><td>${esc(payNames[p.method])}</td><td class="money-cell">${money(p.amount)}</td><td>${esc(p.note||"—")}</td></tr>`);
 const total=state.payments.reduce((sum,p)=>sum+p.amount,0);
 return header("BILLING / PAYMENTS","收款紀錄","登記住宿收費、查詢每筆付款明細。",`<button class="btn btn-primary" data-action="add-payment">＋ 登記收款</button>`)
 +`<div class="kpi-grid">${kpi("累計收款筆數",state.payments.length,"不含退款紀錄","▤")}${kpi("累計實收金額",money(total),"自建立資料庫起","＄")}${kpi("本月實收",money(state.dashboard.monthly_revenue),"本月所有收款","◷")}${kpi("未結清款項",money(state.dashboard.outstanding),"僅計算有效訂單","◇")}</div>`
 +`<section class="panel"><div class="panel-header"><div><h2>收款明細</h2><p>最新的收款記錄顯示在最上方</p></div></div><div class="table-controls"><div class="search-box"><input data-search-input placeholder="搜尋訂單、房客或房號"></div></div>${table(["編號","收款時間","訂單編號","房客","客房","付款方式","金額","備註"],rows,"目前沒有收款紀錄")}</section>`;
}
function reportsView(){
 const d=state.dashboard;
 const byType=Object.entries(typeNames).map(([type,label])=>{const rooms=state.rooms.filter(r=>r.room_type===type&&r.enabled);return `<tr><td class="primary-cell">${label}</td><td>${rooms.length} 間</td><td class="money-cell">${rooms.length?money(Math.round(rooms.reduce((a,r)=>a+r.price,0)/rooms.length)):"—"}</td><td>${rooms.filter(r=>r.occupied).length} 間</td></tr>`});
 return header("INSIGHTS / PERFORMANCE","營運報表","掌握客房使用率、各房型價格與每日收款狀況。",`<button class="btn btn-secondary" data-action="print">⎙ 列印報表</button>`)
 +`<div class="report-cards">${kpi("目前住房率",d.occupancy_rate+"%","已入住 / 啟用客房","⌂")}${kpi("本月實際收入",money(d.monthly_revenue),"按付款日彙總","＄")}${kpi("今日待辦",d.arrivals_today+d.departures_today,"預計入住與退房筆數","▣")}</div>`
 +`<section class="panel"><div class="panel-header"><div><h2>每日收款趨勢</h2><p>近七日實際已收款金額</p></div></div><div class="panel-body">${revenueChart()}</div></section>`
 +`<section class="panel"><div class="panel-header"><div><h2>房型概況</h2><p>僅統計目前啟用客房</p></div></div>${table(["房型","可用房數","平均每晚房價","目前已入住"],byType)}</section><p class="smallprint">※ 營收以付款日期計算；住房率是當下實際入住比例，非預訂率。此版本不提供會計稅務報表或退款沖帳功能。</p>`;
}
function render(){
 const funcs={dashboard:dashboardView,reservations:reservationsView,rooms:roomsView,guests:guestsView,payments:paymentsView,reports:reportsView};
 $("#mainContent").innerHTML=funcs[state.page]?funcs[state.page]():opsRender(state.page);
 filterTable($("#mainContent"));
}
function field(label,name,type="text",value="",attr="",full=false){return `<div class="field ${full?"full":""}"><label for="f_${name}">${label}</label><input id="f_${name}" name="${name}" type="${type}" value="${esc(value)}" ${attr}></div>`}
function selectField(label,name,options,chosen="",full=false){return `<div class="field ${full?"full":""}"><label for="f_${name}">${label}</label><select id="f_${name}" name="${name}">${options.map(o=>`<option value="${esc(o[0])}" ${String(o[0])===String(chosen)?"selected":""}>${esc(o[1])}</option>`).join("")}</select></div>`}
function textareaField(label,name,value=""){return `<div class="field full"><label for="f_${name}">${label}</label><textarea id="f_${name}" name="${name}" maxlength="500">${esc(value)}</textarea></div>`}
function openModal(title,html,onSubmit,saveText="儲存資料"){
 $("#modalHeader").innerHTML=`<h2>${esc(title)}</h2><button type="button" class="close-modal" aria-label="關閉">×</button>`;
 $("#modalBody").innerHTML=`<form id="modalForm" class="modal-form">${html}<div class="modal-actions"><button type="button" class="btn btn-secondary close-action">取消</button><button type="submit" class="btn btn-primary" id="modalSave">${saveText}</button></div></form>`;
 $("#modalOverlay").classList.remove("hidden");
 $("#modalForm").addEventListener("submit",async ev=>{
  ev.preventDefault();const save=$("#modalSave");save.disabled=true;
  try{const values=Object.fromEntries(new FormData(ev.currentTarget).entries());const ok=await onSubmit(values);if(ok)closeModal()}
  catch(e){toast(e.message,true)}finally{save.disabled=false}
 });
}
function closeModal(){$("#modalOverlay").classList.add("hidden");$("#modalBody").innerHTML=""}
function roomModal(id=0){
 const r=state.rooms.find(x=>x.id===id)||{number:"",room_type:"standard",floor:1,capacity:2,price:2200,enabled:1,housekeeping:"clean",bed_type:"double",description:""};
 const html=`<div class="form-grid">${field("房號 *","number","text",r.number,'required maxlength="12" pattern="[A-Za-z0-9-]+"')}${selectField("房型 *","room_type",Object.entries(typeNames),r.room_type)}${field("樓層 *","floor","number",r.floor,'required min="0" max="200"')}${field("最多入住人數 *","capacity","number",r.capacity,'required min="1" max="20"')}${field("每晚房價（NT$） *","price","number",r.price,'required min="1" max="1000000"')}${selectField("清潔狀態","housekeeping",Object.entries(hkNames),r.housekeeping)}${selectField("房間狀態","enabled",[["true","啟用"],["false","停用"]],String(!!r.enabled),true)}${selectField("床型","bed_type",[["single","單人床"],["double","雙人床"],["twin","兩張單人床"],["king","特大床"]],r.bed_type||"double")}${textareaField("客房描述","description",r.description||"")}</div>`;
 openModal(id?`編輯客房 ${r.number}`:"新增客房",html,v=>mutation(id?`/api/rooms/${id}`:"/api/rooms",id?"PUT":"POST",{number:v.number,room_type:v.room_type,floor:Number(v.floor),capacity:Number(v.capacity),price:Number(v.price),housekeeping:v.housekeeping,enabled:v.enabled==="true",bed_type:v.bed_type,description:v.description}));
}
function guestModal(id=0){
 const g=state.guests.find(x=>x.id===id)||{};
 const html=`<div class="form-grid">${field("房客姓名 *","full_name","text",g.full_name,'required maxlength="80"',true)}${field("聯絡電話","phone","text",g.phone,'maxlength="40"')}${field("電子郵件","email","email",g.email,'maxlength="120"')}${field("證件號碼","document_no","text",g.document_no,'maxlength="60"',true)}${textareaField("備註","notes",g.notes)}</div>`;
 openModal(id?"編輯房客資料":"新增房客",html,v=>mutation(id?`/api/guests/${id}`:"/api/guests",id?"PUT":"POST",v));
}
async function reservationModal(id=0){
 if(!state.guests.length){toast("請先新增一位房客，才能建立訂單",true);navigate("guests");return}
 const r=state.reservations.find(x=>x.id===id)||{};
 const start=r.check_in||todayISO(),end=r.check_out||nextDate(start);
 const guestOptions=state.guests.map(g=>[String(g.id),g.full_name+(g.phone?" — "+g.phone:"")]);
 const html=`<div class="form-grid">${selectField("房客 *","guest_id",guestOptions,r.guest_id||state.guests[0].id,true)}${field("入住日期 *","check_in","date",start,`required min="${todayISO()}"`)}${field("退房日期 *","check_out","date",end,`required min="${nextDate(todayISO())}"`)}<div class="field full"><label for="f_room_id">預訂客房 *</label><select id="f_room_id" name="room_id" required><option>載入房間中…</option></select><div class="form-note" id="availabilityNote">依照選定的入住日期即時檢查空房。</div></div>${field("成人數 *","adults","number",r.adults??1,'required min="1" max="20"')}${field("兒童數","children","number",r.children??0,'required min="0" max="20"')}${textareaField("特殊需求（選填）","requests",r.requests)}</div>`;
 openModal(id?`修改訂單 ${r.code}`:"新增訂房",html,v=>mutation(id?`/api/reservations/${id}`:"/api/reservations",id?"PUT":"POST",{guest_id:Number(v.guest_id),room_id:Number(v.room_id),check_in:v.check_in,check_out:v.check_out,adults:Number(v.adults),children:Number(v.children),requests:v.requests}));
 const form=$("#modalForm");
 let selectedId=r.room_id||0;
 let callId=0;
 async function available(){
  const thisCall=++callId;const start=form.elements.namedItem("check_in").value,end=form.elements.namedItem("check_out").value;const roomSelect=form.elements.namedItem("room_id");
  if(!start||!end||end<=start){roomSelect.innerHTML='<option value="">請先選擇有效日期</option>';$("#availabilityNote").textContent="退房日期必須晚於入住日期。";return}
  try{
   const results=await api(`/api/rooms/available?check_in=${encodeURIComponent(start)}&check_out=${encodeURIComponent(end)}&exclude_id=${id}`);
   if(callId!==thisCall||!document.body.contains(roomSelect))return;
   roomSelect.innerHTML=results.length?results.map(room=>`<option value="${room.id}">${esc(room.number)}｜${typeNames[room.room_type]}｜${room.capacity}人｜${money(room.price)}/晚</option>`).join(""):'<option value="">這段日期沒有空房</option>';
   const target=[...roomSelect.options].find(o=>o.value===String(selectedId));if(target)roomSelect.value=String(selectedId);
   const selected=results.find(x=>String(x.id)===roomSelect.value);
   $("#availabilityNote").textContent=selected?`共 ${results.length} 間可預訂；${Math.round((Date.parse(end)-Date.parse(start))/86400000)} 晚，共 ${money(selected.price*Math.round((Date.parse(end)-Date.parse(start))/86400000))}`:"目前沒有符合日期的可預訂客房。";
  }catch(err){if(callId!==thisCall)return;roomSelect.innerHTML='<option value="">無可用房間</option>';$("#availabilityNote").textContent=err.message}
 }
 form.elements.namedItem("check_in").addEventListener("change",()=>{selectedId=0;available()});form.elements.namedItem("check_out").addEventListener("change",()=>{selectedId=0;available()});
 form.elements.namedItem("room_id").addEventListener("change",()=>{selectedId=form.elements.namedItem("room_id").value;available()});
 await available();
}
function payModal(id=0){
 const valid=state.reservations.filter(r=>["reserved","checked_in"].includes(r.status)&&(r.bill_amount??r.total_amount)>r.paid_amount);
 if(!valid.length){toast("目前沒有需要收款的有效訂單",true);return}
 const selected=valid.find(r=>r.id===id)||valid[0];
 const choices=valid.map(r=>[r.id,`${r.code} · ${r.guest_name} · ${r.room_number}（剩餘 ${money((r.bill_amount??r.total_amount)-r.paid_amount)}）`]);
 const html=`<div class="form-grid">${selectField("選擇訂單 *","reservation_id",choices,selected.id,true)}${field("本次收款金額（NT$） *","amount","number",(selected.bill_amount??selected.total_amount)-selected.paid_amount,'required min="1" step="1"')}${selectField("付款方式 *","method",Object.entries(payNames),"cash")}${textareaField("收款備註（選填）","note","")}</div><div class="choice-note" id="paymentHelp">最多可收 ${money((selected.bill_amount??selected.total_amount)-selected.paid_amount)}，不可超收。</div>`;
 openModal("登記收款",html,v=>mutation("/api/payments","POST",{reservation_id:Number(v.reservation_id),amount:Number(v.amount),method:v.method,note:v.note}),"確認收款");
 $("#f_reservation_id").addEventListener("change",ev=>{
  const r=valid.find(r=>r.id===Number(ev.target.value));if(!r)return;
  $("#f_amount").value=(r.bill_amount??r.total_amount)-r.paid_amount;
  $("#paymentHelp").textContent=`最多可收 ${money((r.bill_amount??r.total_amount)-r.paid_amount)}，不可超收。`;
 });
}
function bindGlobalEvents(){
 document.querySelectorAll("[data-page]").forEach(b=>b.addEventListener("click",async()=>{try{await refresh()}catch(e){console.warn("展示資料刷新失敗",e)}navigate(b.dataset.page)}));
 $("#logoutBtn").addEventListener("click",async()=>{
  if(confirm("要清除這個瀏覽器的所有模擬訂單、員工與班次，恢復示範資料嗎？")){window.STAYLINE_DEMO_RESET();location.reload()}
 });
 $("#modalOverlay").addEventListener("click",ev=>{if(ev.target===$("#modalOverlay")||ev.target.closest(".close-modal,.close-action"))closeModal()});
 document.addEventListener("keydown",ev=>{if(ev.key==="Escape")closeModal()});
 $("#mainContent").addEventListener("click",async ev=>{
  const go=ev.target.closest("[data-go]");if(go){navigate(go.dataset.go);return}
  const filter=ev.target.closest("[data-filter]");if(filter){
   $("#mainContent").querySelectorAll("[data-filter]").forEach(b=>b.classList.toggle("active",b===filter));
   applyFilters($("#mainContent"));return;
  }
  const btn=ev.target.closest("[data-action]");if(!btn)return;
  const action=btn.dataset.action,id=Number(btn.dataset.id||0);
  if(action.startsWith("ops-"))return opsAction(action,id,btn);
  if(action==="add-room")return roomModal();
  if(action==="edit-room")return roomModal(id);
  if(action==="delete-room"){if(confirm("確定要刪除此客房？有訂單紀錄的房間無法刪除，請改為停用。"))await mutation(`/api/rooms/${id}`,"DELETE");return}
  if(action==="add-guest")return guestModal();
  if(action==="edit-guest")return guestModal(id);
  if(action==="add-reservation")return reservationModal();
  if(action==="edit-reservation")return reservationModal(id);
  if(action==="add-payment"||action==="pay")return payModal(id);
  if(action==="print")return window.print();
  if(action==="delete-guest"){
   if(confirm("確定要刪除此房客？有訂單紀錄的房客無法刪除。"))await mutation(`/api/guests/${id}`,"DELETE");return;
  }
  if(["check-in","check-out","cancel"].includes(action)){
   const msg={"check-in":"確定辦理入住？請先確認房客身分與房間已清潔。","check-out":"確定辦理退房？房間將標記為待清潔，未結清款項不可退房。","cancel":"確定取消此訂單？已有收款的訂單不可直接取消。"}[action];
   if(confirm(msg))await mutation(`/api/reservations/${id}/${action}`);return;
  }
 });
}
window.addEventListener("DOMContentLoaded",init);

// Vercel demo: reload cross-tab browser-local sample data automatically.
async function syncDemoFromStorage(){
  if(document.querySelector("#appRoot")?.classList.contains("hidden"))return;
  try{await refresh();render()}catch(e){console.warn("展示資料同步失敗",e)}
}
window.addEventListener("focus",syncDemoFromStorage);
document.addEventListener("visibilitychange",()=>{if(!document.hidden)syncDemoFromStorage()});
window.addEventListener("storage",e=>{if(e.key==="stayline-original-ui-demo-2026-v1")syncDemoFromStorage()});
