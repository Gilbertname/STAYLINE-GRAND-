"use strict";
/* STAYLINE v2 admin extension: staff, shifts, leave, training, payroll, services, tickets, housekeeping. */
const v2names={requested:"待處理",in_progress:"處理中",completed:"已完成",rejected:"已拒絕",pending:"待審核",approved:"已核准",active:"在職",inactive:"停用",open:"待回覆",replied:"已回覆",closed:"已結案"};
const serviceNames={food:"餐飲配送",laundry:"洗衣服務",cleaning:"客房清潔",maintenance:"設備維修"};
const staffRoleNames={admin:"管理員",frontdesk:"櫃檯",housekeeping:"房務"};
function obadge(s){return `<span class="ops-state ${esc(s)}">${esc(v2names[s]||s)}</span>`}
function opButton(action,label,id=0,variant=""){return `<button class="ops-mini ${variant}" data-action="ops-${action}" data-id="${Number(id)}">${esc(label)}</button>`}
function opTable(headers,rows){return `<section class="panel"><div class="table-controls"><div class="search-box"><input data-search-input placeholder="搜尋表格資料"></div></div>${table(headers,rows)}</section>`}
function opHeader(eyebrow,title,description,buttons=""){return header(eyebrow,title,description,buttons)}
function opEmployees(){const o=state.ops, admin=state.role==="admin";
 const employees=o.employees||[],accounts=o.staff_accounts||[];
 const rows=employees.map(e=>`<tr><td><strong>${esc(e.full_name)}</strong><div class="detail-hint">#${e.id}</div></td><td>${esc(e.department)}</td><td>${esc(e.position)}</td><td>${esc(e.phone||"—")}</td><td>${esc(e.shift_name||"未排班")}</td><td>${obadge(e.status)}</td><td>${admin?opButton("edit-employee","編輯",e.id):"—"}</td></tr>`);
 const acc=accounts.map(a=>`<tr><td>${esc(a.username)}</td><td>${esc(a.employee_name||"—")}</td><td>${esc(staffRoleNames[a.role]||a.role)}</td></tr>`);
 return opHeader("STAFF / EMPLOYEES","員工與權限","參考 SUNSET HEAVEN 的員工資料、部門與管理員職務分工。",admin?`${opButton("add-employee","＋ 新增員工",0,"primary")} ${opButton("add-account","＋ 建立員工帳號")}`:"")
 +`<div class="ops-grid"><div class="ops-card"><h3>員工總數</h3><strong>${employees.length}</strong><small>包含在職及離職</small></div><div class="ops-card"><h3>在職員工</h3><strong>${employees.filter(e=>e.status==="active").length}</strong><small>目前有安排工作的員工</small></div><div class="ops-card"><h3>系統員工帳號</h3><strong>${admin?accounts.length:"—"}</strong><small>可依角色區分櫃檯與房務操作</small></div></div>`
 +`<div class="ops-heading"><h2>員工名冊</h2></div>${opTable(["姓名","部門","職位","聯絡電話","班次","狀態","操作"],rows)}`
 +(admin?`<div class="ops-heading"><h2>員工登入權限</h2></div>${opTable(["帳號","對應員工","角色"],acc)}<p class="ops-note">請不要為真實員工使用容易猜測的密碼。本機展示版尚未實作帳號停權與自助重設密碼。</p>`:"");
}
function opSchedules(){const o=state.ops,admin=state.role==="admin";
 const shiftRows=(o.shifts||[]).map(s=>{const assigned=(o.employees||[]).filter(e=>Number(e.shift_id)===Number(s.id)).length;return `<tr><td><strong>${esc(s.name)}</strong></td><td>${esc(s.start_time)}</td><td>${esc(s.end_time)}</td><td>${assigned} 位</td><td>${admin?`${opButton("edit-shift","編輯",s.id)} ${opButton("delete-shift","刪除",s.id,"danger")}`:"—"}</td></tr>`});
 const leaveRows=(o.leaves||[]).map(l=>`<tr><td>${esc(l.employee_name)}</td><td>${esc(l.leave_type)}</td><td>${esc(l.start_date)} ～ ${esc(l.end_date)}</td><td>${obadge(l.status)}</td><td>${esc(l.notes||"—")}</td><td>${admin&&l.status==="pending"?opButton("leave-approve","核准",l.id)+opButton("leave-reject","退回",l.id):"—"}</td></tr>`);
 return opHeader("STAFF / SCHEDULE","排班與請假","設定班別、員工輪班及請假審核。",admin?`${opButton("add-shift","＋ 新增班次",0,"primary")} ${opButton("add-leave","＋ 登記請假")}`:"")
 +`<div class="ops-heading"><h2>班次設定</h2></div>${opTable(["班次","上班","下班","目前員工","操作"],shiftRows)}<p class="ops-note">修改班次時間會同步影響已被分配到此班次的員工。若要調整個別員工的班次，請前往「員工與權限」編輯該員工。仍有員工使用的班次不能刪除。</p><div class="ops-heading"><h2>請假紀錄</h2></div>${opTable(["員工","假別","日期","審核狀態","備註","操作"],leaveRows)}`;
}
function opTraining(){const training=state.ops.training||[],admin=state.role==="admin";
 const rows=training.map(t=>`<tr><td>${esc(t.employee_name)}</td><td>${esc(t.title)}</td><td>${esc(t.training_date)}</td><td>${esc(t.outcome||"—")}</td></tr>`);
 return opHeader("STAFF / DEVELOPMENT","員工培訓","登記新進訓練、服務品質課程及培訓結果。",admin?opButton("add-training","＋ 新增培訓紀錄",0,"primary"):"")+opTable(["員工","培訓名稱","培訓日期","成果"],rows);
}
function opPayroll(){if(state.role!=="admin")return empty("沒有權限","只有管理員能檢視薪資紀錄");
 const pay=state.ops.payroll||[],total=pay.reduce((sum,p)=>sum+p.amount,0);
 const rows=pay.map(p=>`<tr><td>${esc(p.employee_name)}</td><td>${esc(p.pay_period)}</td><td>${esc(p.paid_on)}</td><td class="money-cell">${money(p.amount)}</td><td>${esc(p.note||"—")}</td></tr>`);
 return opHeader("STAFF / PAYROLL","薪資管理","依月份登記員工薪資，此功能為內部記錄，不會自動匯款。",opButton("add-payroll","＋ 登記薪資",0,"primary"))
 +`<div class="ops-grid"><div class="ops-card"><h3>已登記薪資筆數</h3><strong>${pay.length}</strong></div><div class="ops-card"><h3>歷史登記總額</h3><strong>${money(total)}</strong></div><div class="ops-card"><h3>資料性質</h3><strong style="font-size:20px">示範記錄</strong><small>非薪轉、報稅或薪資單</small></div></div>`+opTable(["員工","薪資月份","發薪日期","登記金額","備註"],rows);
}
function opServices(){const services=state.ops.services||[];
 const rows=services.map(s=>`<tr><td><strong>#${s.id}</strong><div class="detail-hint">${esc(s.reservation_code)}</div></td><td>${esc(s.guest_name)} · ${esc(s.room_number)}</td><td>${esc(serviceNames[s.kind]||s.kind)}</td><td>${s.quantity}</td><td>${money(s.quantity*s.unit_price)}</td><td>${obadge(s.status)}</td><td>${esc(s.note||"—")}</td><td><div class="ops-row-actions">${["requested","in_progress"].includes(s.status)?`${opButton("service-progress","接單",s.id)}${opButton("service-complete","完成",s.id,"primary")}${state.role!=="housekeeping"?opButton("service-reject","拒絕",s.id,"danger"):""}`:"—"}</div></td></tr>`);
 return opHeader("SERVICE / REQUESTS","客房服務","顧客入住後可提交餐飲、洗衣、清潔或設備維修要求；完成後計入帳單。")
 +`<div class="ops-grid"><div class="ops-card"><h3>待處理</h3><strong>${services.filter(s=>s.status==="requested").length}</strong></div><div class="ops-card"><h3>處理中</h3><strong>${services.filter(s=>s.status==="in_progress").length}</strong></div><div class="ops-card"><h3>已完成</h3><strong>${services.filter(s=>s.status==="completed").length}</strong></div></div>`
 +`<div class="ops-info">餐飲配送 NT$ 300/份、洗衣服務 NT$ 200/份；清潔與維修示範為免費。<strong>只有「已完成」的服務才會加到顧客帳單。</strong></div>`
 +opTable(["服務單","房客 / 房號","類型","數量","費用","狀態","備註","操作"],rows);
}
function opTickets(){const tickets=state.ops.tickets||[];
 const rows=tickets.map(t=>`<tr><td>#${t.id}</td><td>${esc(t.guest_name)}</td><td><strong>${esc(t.subject)}</strong><div class="detail-hint">${esc(t.message)}</div></td><td>${obadge(t.status)}</td><td>${esc(t.reply||"—")}</td><td>${esc(t.created_at)}</td><td>${opButton("ticket-reply","回覆 / 結案",t.id)}</td></tr>`);
 return opHeader("SERVICE / HELP DESK","顧客客服","處理顧客在訂房網站提出的問題與意見。")+opTable(["編號","顧客","問題內容","狀態","回覆內容","建立時間","操作"],rows);
}
function opHousekeeping(){const rooms=state.role==="housekeeping"?(state.ops.rooms||[]):state.rooms;
 const rows=rooms.map(r=>`<tr><td><strong>${esc(r.number)}</strong></td><td>${esc(typeNames[r.room_type]||r.room_type)}</td><td>${r.floor}樓</td><td>${r.occupied?obadge("checked_in"):"空房"}</td><td>${esc(hkNames[r.housekeeping])}</td><td><div class="ops-row-actions">${["clean","cleaning","dirty"].map(v=>v===r.housekeeping?"":opButton("room-"+v, hkNames[v],r.id)).join("")}</div></td></tr>`);
 return opHeader("SERVICE / HOUSEKEEPING","房務清潔","管理待清潔、清潔中與已清潔房間。房務角色僅可處理相關任務。")
 +`<div class="ops-grid"><div class="ops-card"><h3>待清潔</h3><strong>${rooms.filter(r=>r.housekeeping==="dirty").length}</strong></div><div class="ops-card"><h3>清潔中</h3><strong>${rooms.filter(r=>r.housekeeping==="cleaning").length}</strong></div><div class="ops-card"><h3>已清潔</h3><strong>${rooms.filter(r=>r.housekeeping==="clean").length}</strong></div></div>`+opTable(["房號","房型","樓層","入住狀態","清潔狀態","更新狀態"],rows);
}
function opRequests(){const reqs=state.ops.guest_requests||[];
 const rows=reqs.map(r=>`<tr><td>#${r.id}</td><td>${esc(r.guest_name)} · ${esc(r.room_number)}</td><td>${esc(r.reservation_code)}</td><td>${r.request_type==="check_in"?"入住":"退房"}</td><td>${obadge(r.status)}</td><td>${esc(r.staff_note||"—")}</td><td>${r.status==="pending"?`${opButton("request-approve","確認並辦理",r.id,"primary")}${opButton("request-reject","拒絕申請",r.id,"danger")}`:"—"}</td></tr>`);
 return opHeader("FRONT DESK / REQUESTS","入住／退房申請","顧客於會員網站提出申請後，由櫃檯檢查房況或帳單，再決定是否批准。")
 +`<div class="ops-info">核准入住：必須在入住日期範圍內、房間乾淨且可用；核准退房：必須先結清住宿費與已完成的客房服務費。</div>`+opTable(["申請單","顧客 / 房號","訂單","申請","狀態","櫃檯備註","操作"],rows);
}
function opAttendance(){const attendance=state.ops.attendance||[],staff=state.role!=="admin";
 const rows=attendance.map(a=>`<tr><td>${esc(a.employee_name)}</td><td>${esc(a.work_date)}</td><td>${esc(a.clock_in)}</td><td>${esc(a.clock_out||"尚未下班")}</td></tr>`);
 return opHeader("STAFF / ATTENDANCE","員工打卡","員工可登記當日上下班時間；本機測試版不提供 GPS 或生物辨識考勤。",staff?`${opButton("clock-in","◷ 上班打卡",0,"primary")} ${opButton("clock-out","◷ 下班打卡")}`:"")+opTable(["員工","日期","上班時間","下班時間"],rows);
}
function opsRender(page){const actions={employees:opEmployees,schedules:opSchedules,training:opTraining,payroll:opPayroll,services:opServices,tickets:opTickets,requests:opRequests,attendance:opAttendance,housekeeping:opHousekeeping};return actions[page]?actions[page]():empty("頁面不存在")}
function employeeSelect(chosen){const employees=state.ops.employees||[];return selectField("選擇員工 *","employee_id",employees.map(e=>[e.id,`${e.full_name} / ${e.position}`]),chosen||employees[0]?.id||"",true)}
function requireEmployees(){if(!(state.ops.employees||[]).length){toast("請先建立員工資料",true);return false}return true}
async function opsAction(action,id,btn){
 const admin=state.role==="admin";
 if(action==="ops-clock-in"||action==="ops-clock-out"){
   return mutation(`/api/ops/attendance/${action==="ops-clock-in"?"clock-in":"clock-out"}`,"POST",{});
 }
 if(action==="ops-request-approve"||action==="ops-request-reject"){
   const status=action==="ops-request-approve"?"approved":"rejected";
   if(confirm(status==="approved"?"確定已確認房客身分，並按系統規則辦理入住／退房？":"確定拒絕這筆申請？"))return mutation(`/api/ops/requests/${id}`,"PATCH",{status});return;
 }
 if(action==="ops-add-employee"||action==="ops-edit-employee"){
   if(!admin)return toast("僅管理員可編輯員工資料",true);
   const r=(state.ops.employees||[]).find(x=>x.id===id)||{full_name:"",position:"櫃檯人員",department:"前台",phone:"",email:"",hire_date:todayISO(),status:"active",shift_id:state.ops.shifts?.[0]?.id||0};
   const html=`<div class="form-grid">${field("姓名 *","full_name","text",r.full_name,'required maxlength="80"')}${field("職位 *","position","text",r.position,'required maxlength="80"')}${field("部門 *","department","text",r.department,'required maxlength="80"')}${field("電話","phone","tel",r.phone,'maxlength="40"')}${field("信箱","email","email",r.email,'maxlength="120"')}${field("到職日 *","hire_date","date",r.hire_date,"required")}${selectField("班次","shift_id",[[0,"未排班"],...(state.ops.shifts||[]).map(s=>[s.id,`${s.name} ${s.start_time}–${s.end_time}`])],r.shift_id||0)}${selectField("狀態","status",[["active","在職"],["inactive","停用"]],r.status)}</div>`;
   return openModal(id?"修改員工資料":"新增員工",html,v=>mutation(id?`/api/ops/employees/${id}`:"/api/ops/employees",id?"PUT":"POST",{...v,shift_id:Number(v.shift_id)}));
 }
 if(action==="ops-add-account"){
   if(!admin||!requireEmployees())return;
   const html=`<div class="form-grid">${employeeSelect()}${field("登入帳號 *","username","text","",'required minlength="3" pattern="[A-Za-z0-9_]+"')}${field("密碼 *","password","password","",'required minlength="8"')}${selectField("登入角色","role",[["frontdesk","櫃檯職員"],["housekeeping","房務職員"]],"frontdesk")}</div><p class="ops-note">櫃檯帳號可管理預訂與房客；房務帳號只能檢視服務工單、更新清潔狀態。</p>`;
   return openModal("建立員工登入帳號",html,v=>mutation("/api/ops/accounts","POST",{employee_id:Number(v.employee_id),username:v.username,password:v.password,role:v.role}));
 }
 if(action==="ops-add-shift"||action==="ops-edit-shift"){
   if(!admin)return toast("僅管理員可編輯班次",true);
   const editing=action==="ops-edit-shift";
   const r=editing?(state.ops.shifts||[]).find(s=>s.id===id):null;
   if(editing&&!r)return toast("找不到這個班次，請重新整理",true);
   const assigned=editing?(state.ops.employees||[]).filter(e=>Number(e.shift_id)===id).length:0;
   const message=editing?`<p class="ops-note">目前有 ${assigned} 位員工使用此班次；修改上／下班時間將同步影響他們。</p>`:"";
   return openModal(editing?"編輯班次":"建立班次",`<div class="form-grid">${field("班次名稱","name","text",r?.name||"早班B",'required maxlength="50"')}${field("上班時間","start_time","time",r?.start_time||"08:00","required")}${field("下班時間","end_time","time",r?.end_time||"16:00","required")}</div>${message}`,v=>mutation(editing?`/api/ops/shifts/${id}`:"/api/ops/shifts",editing?"PUT":"POST",v));
 }
 if(action==="ops-delete-shift"){
   if(!admin)return toast("僅管理員可刪除班次",true);
   const r=(state.ops.shifts||[]).find(s=>s.id===id);
   if(!r)return toast("找不到這個班次，請重新整理",true);
   const assigned=(state.ops.employees||[]).filter(e=>Number(e.shift_id)===id).length;
   if(assigned)return toast(`「${r.name}」仍有 ${assigned} 位員工使用，請先在「員工與權限」調整員工班次`,true);
   if(confirm(`確定刪除班次「${r.name}」？此操作無法復原。`))return mutation(`/api/ops/shifts/${id}`,"DELETE");
   return;
 }
 if(action==="ops-add-leave"){
   if(!admin||!requireEmployees())return;
   return openModal("登記請假",`<div class="form-grid">${employeeSelect()}${selectField("請假類型","leave_type",[["事假","事假"],["病假","病假"],["特休","特休"],["其他","其他"]],"事假")}${field("開始日期","start_date","date",todayISO(),"required")}${field("結束日期","end_date","date",todayISO(),"required")}${textareaField("備註","notes","")}</div>`,v=>mutation("/api/ops/leaves","POST",{...v,employee_id:Number(v.employee_id)}));
 }
 if(action==="ops-leave-approve"||action==="ops-leave-reject"){
   if(!admin)return; if(confirm(action.endsWith("approve")?"核准這張假單？":"退回這張假單？"))await mutation(`/api/ops/leaves/${id}`,"PATCH",{status:action.endsWith("approve")?"approved":"rejected"});return;
 }
 if(action==="ops-add-training"){
   if(!admin||!requireEmployees())return;
   return openModal("新增培訓紀錄",`<div class="form-grid">${employeeSelect()}${field("培訓項目","title","text","顧客服務與接待",'required maxlength="100"')}${field("日期","training_date","date",todayISO(),"required")}${textareaField("培訓結果","outcome","")}</div>`,v=>mutation("/api/ops/training","POST",{...v,employee_id:Number(v.employee_id)}));
 }
 if(action==="ops-add-payroll"){
   if(!admin||!requireEmployees())return;
   return openModal("登記薪資（不會實際轉帳）",`<div class="form-grid">${employeeSelect()}${field("薪資月份","pay_period","month",todayISO().slice(0,7),"required")}${field("薪資金額 NT$","amount","number",30000,'required min="0" step="1"')}${field("登記發薪日","paid_on","date",todayISO(),"required")}${textareaField("備註","note","")}</div>`,v=>mutation("/api/ops/payroll","POST",{...v,employee_id:Number(v.employee_id),amount:Number(v.amount)}));
 }
 if(["ops-service-progress","ops-service-complete","ops-service-reject"].includes(action)){
   const status=action.endsWith("progress")?"in_progress":action.endsWith("complete")?"completed":"rejected";
   if(confirm(`要把服務單 #${id} 更新為「${v2names[status]}」嗎？${status==="completed"?"完成後費用將加入帳單。":""}`))await mutation(`/api/ops/services/${id}`,"PATCH",{status});return;
 }
 if(action==="ops-ticket-reply"){
   const t=(state.ops.tickets||[]).find(x=>x.id===id);if(!t)return;
   return openModal(`處理顧客問題 #${id}`,`<div class="ops-info"><strong>${esc(t.subject)}</strong><p>${esc(t.message)}</p></div><div class="form-grid">${textareaField("回覆內容","reply",t.reply||"")}${selectField("工單狀態","status",[["open","待回覆"],["replied","已回覆"],["closed","已結案"]],t.status)}</div>`,v=>mutation(`/api/ops/tickets/${id}`,"PATCH",v));
 }
 if(action.startsWith("ops-room-")){
   const housekeeping=action.replace("ops-room-","");await mutation(`/api/ops/rooms/${id}/housekeeping`,"PATCH",{housekeeping});return;
 }
}
