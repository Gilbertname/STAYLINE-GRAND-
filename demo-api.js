/* STAYLINE GRAND 2.5 — PUBLIC, ISOLATED DEMO DATA ADAPTER
   No real accounts, identity checks, server requests, payments, or shared database.
   Preserves the original application's HTML, CSS, navigation and UI handlers.
*/
(()=>{
'use strict';
const KEY='stayline-original-ui-demo-2026-v1';
const ts=()=>{const parts=Object.fromEntries(new Intl.DateTimeFormat('en-US',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date()).map(x=>[x.type,x.value]));return `${parts.year}-${parts.month}-${parts.day}`};
const stamp=()=>new Date().toISOString().slice(0,19).replace('T',' ');
const days=(a,b)=>Math.round((Date.parse(b)-Date.parse(a))/86400000);
const newId=a=>Math.max(0,...a.map(x=>Number(x.id)||0))+1;
const seeds=[['101','standard',1,2,2200],['102','standard',1,2,2200],['103','standard',1,2,2200],['104','deluxe',1,3,3500],['201','standard',2,2,2400],['202','standard',2,2,2400],['203','deluxe',2,3,3500],['204','deluxe',2,3,3500],['301','suite',3,4,5800],['302','suite',3,4,5800],['303','deluxe',3,3,3800],['304','deluxe',3,3,3800]];
const initial=()=>({
 rooms:seeds.map((s,i)=>({id:i+1,number:s[0],room_type:s[1],floor:s[2],capacity:s[3],price:s[4],enabled:1,housekeeping:'clean',bed_type:s[1]==='suite'?'king':'double',description:'AI 生成客房風格示範，僅供作品展示',created_at:stamp()})),
 guests:[{id:1,full_name:'展示旅客',phone:'',email:'demo@example.invalid',document_no:'',notes:'虛構示範資料',created_at:stamp()}],
 memberGuestId:1,reservations:[],payments:[],verifications:[],services:[],tickets:[],requests:[],
 shifts:[{id:1,name:'早班',start_time:'07:00',end_time:'15:00'},{id:2,name:'中班',start_time:'15:00',end_time:'23:00'},{id:3,name:'夜班',start_time:'23:00',end_time:'07:00'},{id:4,name:'早班B',start_time:'08:00',end_time:'16:00'}],
 employees:[{id:1,full_name:'示範櫃檯員工',department:'前台',position:'櫃檯人員',phone:'',email:'',hire_date:ts(),status:'active',shift_id:1}],
 accounts:[],leaves:[],training:[],payroll:[],attendance:[]
});
let db;
try{db=JSON.parse(localStorage.getItem(KEY)||'null')||initial()}catch{db=initial()}
const save=()=>{try{localStorage.setItem(KEY,JSON.stringify(db))}catch(e){console.warn('示範資料未能暫存',e)}};
window.STAYLINE_DEMO_RESET=()=>{db=initial();save()};
function fail(message,status=400){const e=new Error(message);e.status=status;throw e}
function requireRow(a,id,msg='找不到紀錄'){const o=a.find(x=>x.id===Number(id));if(!o)fail(msg,404);return o}
function roomOf(r){return requireRow(db.rooms,r.room_id)}
function guestOf(r){return requireRow(db.guests,r.guest_id)}
function paid(rid){return db.payments.filter(p=>p.reservation_id===rid).reduce((a,p)=>a+p.amount,0)}
function serviceCharge(rid){return db.services.filter(s=>s.reservation_id===rid&&s.status==='completed').reduce((a,s)=>a+s.quantity*s.unit_price,0)}
function freeRoom(r,checkIn,checkOut,exclude=0){return r.enabled&& !db.reservations.some(o=>o.room_id===r.id&&o.id!==exclude&&['reserved','checked_in'].includes(o.status)&&o.check_in<checkOut&&o.check_out>checkIn)}
function resRow(r){const room=roomOf(r),g=guestOf(r);return {...r,guest_name:g.full_name,guest_phone:g.phone,room_number:room.number,room_type:room.room_type,housekeeping:room.housekeeping,paid_amount:paid(r.id),services_amount:serviceCharge(r.id),bill_amount:r.total_amount+serviceCharge(r.id)}}
function guestRow(r){const x=resRow(r);return {...x}}
function payRow(p){const r=requireRow(db.reservations,p.reservation_id);return {...p,reservation_code:r.code,guest_name:guestOf(r).full_name,room_number:roomOf(r).number}}
function overview(){const decorate=(o,extra)=>({...o,...extra});return {
 employees:db.employees.map(e=>decorate(e,{shift_name:db.shifts.find(s=>s.id===Number(e.shift_id))?.name||'未排班'})),
 shifts:db.shifts,staff_accounts:db.accounts.map(a=>decorate(a,{employee_name:db.employees.find(x=>x.id===a.employee_id)?.full_name||''})),
 leaves:db.leaves.map(l=>decorate(l,{employee_name:db.employees.find(e=>e.id===l.employee_id)?.full_name||''})),
 training:db.training.map(t=>decorate(t,{employee_name:db.employees.find(e=>e.id===t.employee_id)?.full_name||''})),
 payroll:db.payroll.map(p=>decorate(p,{employee_name:db.employees.find(e=>e.id===p.employee_id)?.full_name||''})),
 services:db.services.map(s=>{const r=requireRow(db.reservations,s.reservation_id);return decorate(s,{reservation_code:r.code,room_number:roomOf(r).number,guest_name:guestOf(r).full_name})}),
 guest_requests:db.requests.map(s=>{const r=requireRow(db.reservations,s.reservation_id);return decorate(s,{reservation_code:r.code,room_number:roomOf(r).number,guest_name:guestOf(r).full_name})}),
 tickets:db.tickets.map(t=>decorate(t,{guest_name:db.guests.find(g=>g.id===t.guest_id)?.full_name||''})),
 attendance:db.attendance.map(a=>decorate(a,{employee_name:db.employees.find(e=>e.id===a.employee_id)?.full_name||''}))
}}
function dashboard(){const active=db.rooms.filter(r=>r.enabled),orders=db.reservations,checked=orders.filter(r=>r.status==='checked_in'),revenue=db.payments.reduce((n,p)=>n+p.amount,0);const now=ts();return {
 room_count:active.length,occupied:checked.length,available_now:Math.max(0,active.length-checked.length),occupancy_rate:active.length?Math.round(checked.length/active.length*100):0,
 arrivals_today:orders.filter(r=>r.check_in===now&&r.status==='reserved').length,departures_today:orders.filter(r=>r.check_out===now&&r.status==='checked_in').length,
 monthly_revenue:db.payments.filter(p=>p.paid_at.slice(0,7)===now.slice(0,7)).reduce((n,p)=>n+p.amount,0),
 outstanding:orders.filter(r=>['reserved','checked_in'].includes(r.status)).reduce((n,r)=>n+r.total_amount+serviceCharge(r.id)-paid(r.id),0),
 daily_revenue:Array.from({length:7},(_,i)=>{const d=new Date(Date.now()-(6-i)*864e5).toISOString().slice(0,10);return {date:d,amount:db.payments.filter(p=>p.paid_at.slice(0,10)===d).reduce((n,p)=>n+p.amount,0)}}),recent:orders.slice().reverse().slice(0,6).map(resRow)
}}
function newReservation(data,portal=false){const room=requireRow(db.rooms,data.room_id,'無此客房');const ci=String(data.check_in||''),co=String(data.check_out||'');if(!ci||!co||ci<ts()||days(ci,co)<=0||days(ci,co)>365)fail('入住／退房日期無效');if(!freeRoom(room,ci,co))fail('這段日期已有訂單，請選其他客房',409);const count=Number(data.adults||1)+Number(data.children||0);if(count>room.capacity||count<1)fail('超出房間容納人數');const student=portal&&data.student_discount===true;
 if(student&&room.room_type!=='standard')fail('學生優惠僅適用標準客房');if(student&&(!data.student_name||!data.student_school||!data.student_valid_until))fail('請填寫示範學生資料');
 const original=room.price*days(ci,co),discount=student?Math.round(original*.1):0;
 const g=portal?db.memberGuestId:Number(data.guest_id);requireRow(db.guests,g);
 const r={id:newId(db.reservations),code:'DEMO'+Date.now().toString(36).toUpperCase().slice(-7),guest_id:g,room_id:room.id,check_in:ci,check_out:co,adults:Number(data.adults)||1,children:Number(data.children)||0,price_per_night:room.price,total_amount:original-discount,discount_type:student?'student':'none',discount_amount:discount,source:portal?'web':'frontdesk',status:'reserved',requests:String(data.requests||''),expected_arrival_time:String(data.expected_arrival_time||'15:00'),created_at:stamp()};
 db.reservations.push(r);if(student)db.verifications.push({id:newId(db.verifications),reservation_id:r.id,student_name:data.student_name,school_name:data.student_school,valid_until:data.student_valid_until,status:'pending',created_at:stamp()});return {id:r.id,code:r.code}
}
function checkout(r){const v=db.verifications.find(v=>v.reservation_id===r.id);return {...resRow(r),verification_status:v?.status||'not_required',school_name:v?.school_name||'',valid_until:v?.valid_until||'',outstanding:Math.max(0,r.total_amount+serviceCharge(r.id)-paid(r.id)),simulation:true}}
function recordPayment(r,amount,method,note){if(!['reserved','checked_in'].includes(r.status))fail('此訂單狀態不可付款');const due=r.total_amount+serviceCharge(r.id)-paid(r.id);if(amount<=0||amount>due)fail('付款金額必須大於 0 且不得超過尾款');const p={id:newId(db.payments),reservation_id:r.id,amount,method,note:String(note||'模擬付款，非真實交易'),paid_at:stamp()};db.payments.push(p);return {id:p.id}}
function handle(path,method,v){const url=new URL(path,location.href),p=url.pathname,qs=url.searchParams,parts=p.split('/').filter(Boolean),id=Number(parts[2]),sub=parts[3];
 if(p==='/api/bootstrap')return {needs_setup:false};
 if(p==='/api/me'||p==='/api/login'||p==='/api/setup')return {username:'展示管理員',role:'admin',csrf:'demo',today:ts()};
 if(p==='/api/logout')return {ok:true};
 if(p==='/api/dashboard')return dashboard();
 if(p==='/api/rooms/available'||p==='/api/public/rooms'){const a=qs.get('check_in'),b=qs.get('check_out');return db.rooms.filter(r=>!a||!b||freeRoom(r,a,b,Number(qs.get('exclude_id')||0)))}
 if(p==='/api/rooms'&&method==='GET')return db.rooms.map(r=>({...r,occupied:db.reservations.some(x=>x.room_id===r.id&&x.status==='checked_in')?1:0}));
 if(p==='/api/rooms'&&method==='POST'){if(db.rooms.some(r=>r.number===v.number))fail('房號已存在');const r={...v,id:newId(db.rooms),enabled:Number(v.enabled!==false),created_at:stamp()};db.rooms.push(r);return {id:r.id}}
 if(parts[1]==='rooms'&&parts.length===3){const r=requireRow(db.rooms,id);if(method==='DELETE'){if(db.reservations.some(x=>x.room_id===id))fail('有訂房紀錄的房間無法刪除');db.rooms=db.rooms.filter(x=>x.id!==id);return {ok:true}}if(method==='PUT'){if(db.rooms.some(x=>x.id!==id&&x.number===v.number))fail('房號已存在');Object.assign(r,v,{enabled:Number(v.enabled!==false)});return {ok:true}}}
 if(p==='/api/guests'&&method==='GET')return db.guests.slice().reverse();
 if(p==='/api/guests'&&method==='POST'){if(!v.full_name)fail('請輸入房客姓名');const x={...v,id:newId(db.guests),created_at:stamp()};db.guests.push(x);return {id:x.id}}
 if(parts[1]==='guests'&&parts.length===3){const g=requireRow(db.guests,id);if(method==='PUT'){Object.assign(g,v);return {ok:true}}if(method==='DELETE'){if(db.reservations.some(r=>r.guest_id===id))fail('此房客已有訂單');db.guests=db.guests.filter(x=>x.id!==id);return {ok:true}}}
 if(p==='/api/reservations'&&method==='GET')return db.reservations.slice().reverse().map(resRow);
 if(p==='/api/reservations'&&method==='POST')return newReservation(v);
 if(parts[1]==='reservations'&&parts.length>=3){const r=requireRow(db.reservations,id);if(method==='PUT'){if(!freeRoom(requireRow(db.rooms,v.room_id),v.check_in,v.check_out,id))fail('日期撞期');const room=requireRow(db.rooms,v.room_id);if(days(v.check_in,v.check_out)<1)fail('日期不正確');Object.assign(r,v,{total_amount:room.price*days(v.check_in,v.check_out),discount_type:'none',discount_amount:0});return {ok:true}}if(method==='POST'&&sub){if(sub==='check-in'){if(r.status!=='reserved')fail('訂單無法入住');r.status='checked_in'}else if(sub==='check-out'){if(r.status!=='checked_in')fail('尚未入住');if(r.total_amount+serviceCharge(r.id)-paid(r.id)>0)fail('退房前請先結清款項');r.status='checked_out';roomOf(r).housekeeping='dirty'}else if(sub==='cancel'){if(paid(r.id)>0)fail('已有收款記錄，不可取消');r.status='cancelled'}return {ok:true}}}
 if(p==='/api/payments'&&method==='GET')return db.payments.slice().reverse().map(payRow);
 if(p==='/api/payments'&&method==='POST')return recordPayment(requireRow(db.reservations,v.reservation_id),Number(v.amount),v.method,v.note);
 if(p==='/api/ops/overview')return overview();
 if(p==='/api/ops/employees'&&method==='POST'){const x={...v,id:newId(db.employees),status:v.status||'active'};db.employees.push(x);return {id:x.id}}
 if(p==='/api/ops/shifts'&&method==='POST'){if(db.shifts.some(s=>s.name===v.name))fail('班次名稱已存在');const x={...v,id:newId(db.shifts)};db.shifts.push(x);return {id:x.id}}
 if(p==='/api/ops/accounts'&&method==='POST'){db.accounts.push({id:newId(db.accounts),employee_id:Number(v.employee_id),username:v.username,role:v.role});return {ok:true}}
 if(p==='/api/ops/leaves'&&method==='POST'){db.leaves.push({...v,id:newId(db.leaves),status:'pending'});return {ok:true}}
 if(p==='/api/ops/training'&&method==='POST'){db.training.push({...v,id:newId(db.training)});return {ok:true}}
 if(p==='/api/ops/payroll'&&method==='POST'){db.payroll.push({...v,id:newId(db.payroll)});return {ok:true}}
 if(p==='/api/ops/attendance/clock-in'&&method==='POST'){db.attendance.push({id:newId(db.attendance),employee_id:1,work_date:ts(),clock_in:stamp(),clock_out:''});return {ok:true}}
 if(p==='/api/ops/attendance/clock-out'&&method==='POST'){const a=db.attendance.slice().reverse().find(a=>!a.clock_out);if(!a)fail('請先上班打卡');a.clock_out=stamp();return {ok:true}}
 if(parts[0]==='api'&&parts[1]==='ops'&&parts.length>=4){const kind=parts[2],iid=Number(parts[3]);
  if(kind==='employees'&&method==='PUT'){Object.assign(requireRow(db.employees,iid),v);return {ok:true}}
  if(kind==='shifts'){const s=requireRow(db.shifts,iid);if(method==='PUT'){if(db.shifts.some(x=>x.id!==iid&&x.name===v.name))fail('班次名稱重複');Object.assign(s,v);return {ok:true}}if(method==='DELETE'){if(db.employees.some(x=>Number(x.shift_id)===iid))fail('有員工正在使用此班次');db.shifts=db.shifts.filter(x=>x.id!==iid);return {ok:true}}}
  if(kind==='leaves'){requireRow(db.leaves,iid).status=v.status;return {ok:true}}
  if(kind==='services'){requireRow(db.services,iid).status=v.status;return {ok:true}}
  if(kind==='tickets'){Object.assign(requireRow(db.tickets,iid),v);return {ok:true}}
  if(kind==='requests'){const req=requireRow(db.requests,iid);req.status=v.status;const r=requireRow(db.reservations,req.reservation_id);if(v.status==='approved'){if(req.request_type==='check_in')r.status='checked_in';else if(req.request_type==='check_out'){if(r.total_amount+serviceCharge(r.id)-paid(r.id)>0)fail('仍有未結清款項');r.status='checked_out';roomOf(r).housekeeping='dirty'}}return {ok:true}}
  if(kind==='rooms'&&parts[4]==='housekeeping'){requireRow(db.rooms,iid).housekeeping=v.housekeeping;return {ok:true}}
 }
 // guest portal — visitor is always a fictional demo member
 if(p==='/api/portal/me')return {csrf:'demo',guest:requireRow(db.guests,db.memberGuestId),today:ts(),username:'demo'};
 if(p==='/api/portal/login'||p==='/api/portal/register'||p==='/api/portal/logout')return {csrf:'demo',ok:true};
 if(p==='/api/portal/reservations')return db.reservations.filter(r=>r.guest_id===db.memberGuestId).slice().reverse().map(guestRow);
 if(p==='/api/portal/payments')return db.payments.filter(p=>db.reservations.some(r=>r.id===p.reservation_id&&r.guest_id===db.memberGuestId)).map(payRow);
 if(p==='/api/portal/services'&&method==='GET')return overview().services.filter(s=>db.reservations.some(r=>r.id===s.reservation_id&&r.guest_id===db.memberGuestId));
 if(p==='/api/portal/requests'&&method==='GET')return db.requests.filter(s=>db.reservations.some(r=>r.id===s.reservation_id&&r.guest_id===db.memberGuestId));
 if(p==='/api/portal/tickets'&&method==='GET')return db.tickets.filter(t=>t.guest_id===db.memberGuestId);
 if(p==='/api/portal/tickets'&&method==='POST'){db.tickets.push({...v,id:newId(db.tickets),guest_id:db.memberGuestId,reply:'',status:'open',created_at:stamp()});return {ok:true}}
 if(p==='/api/portal/profile'&&method==='PUT'){Object.assign(requireRow(db.guests,db.memberGuestId),v);return {ok:true}}
 if(p==='/api/portal/book'&&method==='POST')return newReservation(v,true);
 if(p==='/api/portal/cancel'&&method==='POST'){const r=requireRow(db.reservations,v.reservation_id);if(r.guest_id!==db.memberGuestId)fail('非本人的訂單');if(paid(r.id)>0)fail('此訂單已付款');r.status='cancelled';return {ok:true}}
 if(p==='/api/portal/checkout'&&method==='GET'){const r=requireRow(db.reservations,Number(qs.get('reservation_id')));return checkout(r)}
 if(p==='/api/portal/pay'&&method==='POST'){const r=requireRow(db.reservations,v.reservation_id),x=checkout(r);if(r.guest_id!==db.memberGuestId)fail('不能支付其他人的訂單');if(v.method==='pay_at_hotel')return {status:'pay_at_hotel',simulation:true};if(x.outstanding<=0)fail('已結清');if(x.discount_type==='student'&&x.verification_status!=='approved')fail('學生優惠尚待示範審核，請先前往管理後台');if(!['demo_card','demo_transfer'].includes(v.method))fail('無效的模擬付款方式');recordPayment(r,x.outstanding,v.method==='demo_card'?'card':'transfer','SIMULATION ONLY');return {status:'paid_demo',simulation:true}}
 if(p==='/api/portal/services'&&method==='POST'){const r=requireRow(db.reservations,v.reservation_id);if(r.guest_id!==db.memberGuestId||r.status!=='checked_in')fail('僅已入住訂單可申請');const costs={food:300,laundry:200,cleaning:0,maintenance:0};if(!(v.kind in costs))fail('無此服務');db.services.push({...v,id:newId(db.services),quantity:Number(v.quantity),unit_price:costs[v.kind],status:'requested',created_at:stamp()});return {ok:true}}
 if(p==='/api/portal/requests'&&method==='POST'){const r=requireRow(db.reservations,v.reservation_id);if(r.guest_id!==db.memberGuestId)fail('不能代他人操作');db.requests.push({...v,id:newId(db.requests),status:'pending'});return {ok:true}}
 if(p==='/api/student-reviews')return db.verifications.slice().reverse().map(x=>{const r=requireRow(db.reservations,x.reservation_id);return {...x,code:r.code,reservation_status:r.status,discount_amount:r.discount_amount,member_name:guestOf(r).full_name,room_number:roomOf(r).number}});
 if(p==='/api/student-review'&&method==='POST'){const x=db.verifications.find(x=>x.reservation_id===Number(v.reservation_id));if(!x||x.status!=='pending')fail('找不到待處理申請');if(!['approved','rejected'].includes(v.status))fail('無效狀態');const r=requireRow(db.reservations,x.reservation_id);if(v.status==='rejected'){r.total_amount+=r.discount_amount;r.discount_amount=0;r.discount_type='none'}x.status=v.status;x.reviewed_at=stamp();return {status:v.status}}
 fail('此展示功能尚未模擬：'+method+' '+p,404)
}
// Keep all simulated requests entirely inside this browser; no outgoing API traffic.
const fetchOriginal=window.fetch.bind(window);
window.fetch=async function(url,opts={}){
 const u=typeof url==='string'?url:url.url;
 const parsed=new URL(u,location.href);
 if(parsed.origin!==location.origin || !parsed.pathname.startsWith('/api/'))return fetchOriginal(url,opts);
 const method=(opts.method||'GET').toUpperCase();let val={};
 try{db=JSON.parse(localStorage.getItem(KEY)||'null')||initial();if(opts.body)val=JSON.parse(opts.body);const result=handle(parsed.pathname+parsed.search,method,val);if(method!=='GET')save();return new Response(JSON.stringify(result),{status:200,headers:{'Content-Type':'application/json'}})}
 catch(e){console.warn('STAYLINE DEMO:',e.message);return new Response(JSON.stringify({error:e.message}),{status:e.status||500,headers:{'Content-Type':'application/json'}})}
};
save();
})();
