"""STAYLINE GRAND: guest portal, staff operations and service workflows.
All endpoints remain local-only; no credit-card processing or public deployment.
"""
from __future__ import annotations

import hmac
import re
import secrets
import sqlite3
import threading
import time
from datetime import timedelta
from http.cookies import SimpleCookie

GUEST_SESSIONS = {}
GUEST_LOCK = threading.Lock()
SERVICE_TYPES = {"food": ("餐飲配送", 300), "laundry": ("洗衣服務", 200), "cleaning": ("客房清潔", 0), "maintenance": ("設備維修", 0)}
SERVICE_STATUSES = ("requested", "in_progress", "completed", "rejected")
TICKET_STATUSES = ("open", "replied", "closed")
EMPLOYEE_STATUSES = ("active", "inactive")
LEAVE_STATUSES = ("pending", "approved", "rejected")
STAFF_ROLES = ("frontdesk", "housekeeping")


def init_extension(db, m):
    """Idempotent additive migrations. Existing users, room reservations and payments are preserved."""
    for table, col, decl in (
        ("users", "role", "TEXT NOT NULL DEFAULT 'admin'"),
        ("users", "employee_id", "INTEGER"),
        ("rooms", "bed_type", "TEXT NOT NULL DEFAULT 'double'"),
        ("rooms", "description", "TEXT NOT NULL DEFAULT ''"),
        ("reservations", "source", "TEXT NOT NULL DEFAULT 'frontdesk'"),
        ("reservations", "discount_type", "TEXT NOT NULL DEFAULT 'none'"),
        ("reservations", "discount_amount", "INTEGER NOT NULL DEFAULT 0"),
        ("reservations", "expected_arrival_time", "TEXT NOT NULL DEFAULT '15:00'"),
    ):
        cols = {r["name"] for r in db.execute(f"PRAGMA table_info({table})")}
        if col not in cols:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS shifts (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL UNIQUE,
          start_time TEXT NOT NULL,
          end_time TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS employees (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          full_name TEXT NOT NULL,
          position TEXT NOT NULL,
          department TEXT NOT NULL,
          phone TEXT NOT NULL DEFAULT '',
          email TEXT NOT NULL DEFAULT '',
          hire_date TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','inactive')),
          shift_id INTEGER REFERENCES shifts(id),
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS staff_leaves (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          employee_id INTEGER NOT NULL REFERENCES employees(id),
          leave_type TEXT NOT NULL,
          start_date TEXT NOT NULL,
          end_date TEXT NOT NULL,
          notes TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS staff_training (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          employee_id INTEGER NOT NULL REFERENCES employees(id),
          title TEXT NOT NULL,
          training_date TEXT NOT NULL,
          outcome TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS payroll (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          employee_id INTEGER NOT NULL REFERENCES employees(id),
          pay_period TEXT NOT NULL,
          amount INTEGER NOT NULL CHECK(amount >= 0),
          paid_on TEXT NOT NULL,
          note TEXT NOT NULL DEFAULT '',
          UNIQUE(employee_id,pay_period)
        );
        CREATE TABLE IF NOT EXISTS guest_accounts (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          guest_id INTEGER NOT NULL UNIQUE REFERENCES guests(id),
          username TEXT NOT NULL UNIQUE,
          password_salt TEXT NOT NULL,
          password_hash TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS room_services (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          reservation_id INTEGER NOT NULL REFERENCES reservations(id),
          kind TEXT NOT NULL CHECK(kind IN ('food','laundry','cleaning','maintenance')),
          quantity INTEGER NOT NULL CHECK(quantity BETWEEN 1 AND 20),
          unit_price INTEGER NOT NULL CHECK(unit_price >= 0),
          note TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'requested' CHECK(status IN ('requested','in_progress','completed','rejected')),
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_room_service_reservation ON room_services(reservation_id);
        CREATE TABLE IF NOT EXISTS support_tickets (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          guest_id INTEGER NOT NULL REFERENCES guests(id),
          subject TEXT NOT NULL,
          message TEXT NOT NULL,
          reply TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','replied','closed')),
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_tickets_guest ON support_tickets(guest_id);
        CREATE TABLE IF NOT EXISTS guest_requests (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          reservation_id INTEGER NOT NULL REFERENCES reservations(id),
          request_type TEXT NOT NULL CHECK(request_type IN ('check_in','check_out')),
          status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
          staff_note TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          processed_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_guest_requests_res ON guest_requests(reservation_id);
        CREATE TABLE IF NOT EXISTS staff_attendance (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          employee_id INTEGER NOT NULL REFERENCES employees(id),
          work_date TEXT NOT NULL,
          clock_in TEXT NOT NULL,
          clock_out TEXT,
          UNIQUE(employee_id,work_date)
        );
    """)
    # Seed initial templates only once; do not re-create a renamed default shift on restart.
    if db.execute("SELECT COUNT(*) FROM shifts").fetchone()[0] == 0:
        for n,s,e in (("早班","07:00","15:00"),("中班","15:00","23:00"),("夜班","23:00","07:00")):
            db.execute("INSERT INTO shifts(name,start_time,end_time) VALUES(?,?,?)",(n,s,e))


def service_total(db, reservation_id):
    return db.execute("SELECT COALESCE(SUM(quantity*unit_price),0) FROM room_services WHERE reservation_id=? AND status='completed'", (reservation_id,)).fetchone()[0]


def bill_total(db, reservation_id):
    r=db.execute("SELECT total_amount FROM reservations WHERE id=?",(reservation_id,)).fetchone()
    return (r["total_amount"] if r else 0) + service_total(db,reservation_id)


def staff_user(h, method, m, allowed=("admin","frontdesk","housekeeping")):
    sess=m.authenticate(h,method!="GET")
    with m.connection() as db:
        user=db.execute("SELECT id,username,role,employee_id FROM users WHERE id=?",(sess["uid"],)).fetchone()
    if not user or user["role"] not in allowed:
        raise m.ApiError("你的職務沒有權限執行此操作",403)
    return dict(user)


def guest_session(h, m, write=False):
    try:
        cookie=SimpleCookie();cookie.load(h.headers.get("Cookie",""))
        token=cookie["stayline_grand_guest_session"].value if "stayline_grand_guest_session" in cookie else ""
    except Exception:
        token=""
    with GUEST_LOCK:
        s=GUEST_SESSIONS.get(token)
        if s and s["expires"]<=time.time():
            GUEST_SESSIONS.pop(token,None);s=None
        if s:
            s=dict(s,token=token)
    if not s:
        raise m.ApiError("請先登入顧客帳號",401)
    if write and not hmac.compare_digest(h.headers.get("X-CSRF-Token",""),s["csrf"]):
        raise m.ApiError("安全驗證失敗，請重新登入",403)
    return s


def guest_login_session(uid):
    token=secrets.token_urlsafe(40);csrf=secrets.token_urlsafe(32)
    with GUEST_LOCK:
        GUEST_SESSIONS[token]={"uid":uid,"csrf":csrf,"expires":time.time()+12*3600}
    return token,csrf


def error_if(condition, message, m, status=400):
    if condition:raise m.ApiError(message,status)


def staff_overview(db,role,employee_id=None):
    def rows(q,params=()):return [dict(r) for r in db.execute(q,params)]
    services=rows("""SELECT s.*,r.code reservation_code,x.number room_number,g.full_name guest_name
                FROM room_services s JOIN reservations r ON r.id=s.reservation_id JOIN rooms x ON x.id=r.room_id
                JOIN guests g ON g.id=r.guest_id ORDER BY s.id DESC""")
    attend_q="""SELECT a.*,e.full_name employee_name FROM staff_attendance a JOIN employees e ON e.id=a.employee_id"""
    attendance=rows(attend_q+(" ORDER BY a.work_date DESC,a.id DESC" if role=="admin" else " WHERE a.employee_id=? ORDER BY a.work_date DESC,a.id DESC"),() if role=="admin" else (employee_id,))
    if role=="housekeeping":
        return {"services":services,"attendance":attendance,"rooms":rows("SELECT r.*, EXISTS(SELECT 1 FROM reservations x WHERE x.room_id=r.id AND x.status='checked_in') occupied FROM rooms r ORDER BY r.number")}
    result={"services":services,"attendance":attendance,
      "guest_requests":rows("""SELECT a.*,r.code reservation_code,g.full_name guest_name,x.number room_number
                        FROM guest_requests a JOIN reservations r ON r.id=a.reservation_id
                        JOIN guests g ON g.id=r.guest_id JOIN rooms x ON x.id=r.room_id ORDER BY a.id DESC"""),
      "employees":rows("""SELECT e.*, s.name shift_name FROM employees e LEFT JOIN shifts s ON e.shift_id=s.id ORDER BY e.id DESC"""),
      "shifts":rows("SELECT * FROM shifts ORDER BY id"),
      "leaves":rows("""SELECT l.*, e.full_name employee_name FROM staff_leaves l JOIN employees e ON e.id=l.employee_id ORDER BY l.id DESC"""),
      "training":rows("""SELECT t.*,e.full_name employee_name FROM staff_training t JOIN employees e ON e.id=t.employee_id ORDER BY t.id DESC"""),
      "payroll":rows("""SELECT p.*,e.full_name employee_name FROM payroll p JOIN employees e ON e.id=p.employee_id ORDER BY p.id DESC"""),
      "tickets":rows("""SELECT t.*,g.full_name guest_name FROM support_tickets t JOIN guests g ON g.id=t.guest_id ORDER BY t.id DESC"""),
      "staff_accounts":rows("""SELECT u.id,u.username,u.role,e.full_name employee_name FROM users u LEFT JOIN employees e ON e.id=u.employee_id WHERE u.role!='admin' ORDER BY u.id DESC"""),
    }
    if role!="admin":
        result.pop("payroll",None);result.pop("staff_accounts",None)
    return result


def handle(h, method, path, query, m):
    """Return True if handled. Its caller manages ApiError and generic server errors."""
    if method=="GET" and path in ("/guest", "/guest.js", "/guest.css"):
        files={"/guest":("guest.html","text/html; charset=utf-8"), "/guest.js":("guest.js","text/javascript; charset=utf-8"), "/guest.css":("guest.css","text/css; charset=utf-8")}
        h.file_response(*files[path]);return True
    if method=="GET" and path=="/api/public/rooms":
        st=query.get("check_in",[""])[0];ed=query.get("check_out",[""])[0]
        if bool(st) != bool(ed):raise m.ApiError("請同時指定入住與退房日期")
        if st:
            a=m.parse_date(st,"入住日期");b=m.parse_date(ed,"退房日期")
            error_if(a<m.today() or b<=a or (b-a).days>365,"請選擇有效日期（最多 365 晚）",m)
        with m.connection() as db:
            if st:
                rows=db.execute("""SELECT id,number,room_type,floor,capacity,price,bed_type,description FROM rooms
                    WHERE enabled=1 AND NOT EXISTS(SELECT 1 FROM reservations x WHERE x.room_id=rooms.id
                    AND x.status IN ('reserved','checked_in') AND x.check_in<? AND x.check_out>?)
                    ORDER BY price,number""",(ed,st))
            else:
                rows=db.execute("SELECT id,number,room_type,floor,capacity,price,bed_type,description FROM rooms WHERE enabled=1 ORDER BY price,number")
            h.json_response([dict(x) for x in rows]);return True
    if path.startswith("/api/portal/"):
        action=path.removeprefix("/api/portal/")
        if method=="POST" and action=="register":
            d=h.read_json()
            username=m.string(d.get("username"),"顧客帳號",40,True)
            pw=d.get("password")
            name=m.string(d.get("full_name"),"姓名",80,True)
            phone=m.string(d.get("phone"),"電話",40)
            email=m.string(d.get("email"),"電子信箱",120,True)
            error_if(not re.fullmatch(r"[a-zA-Z0-9_]{3,40}",username),"帳號限 3–40 個英數字或底線",m)
            error_if(not isinstance(pw,str) or len(pw)<8 or len(pw)>128,"密碼需 8–128 個字元",m)
            error_if(not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+",email),"電子郵件格式不正確",m)
            salt=secrets.token_hex(16)
            with m.connection() as db:
                db.execute("BEGIN IMMEDIATE")
                try:
                    db.execute("INSERT INTO guests(full_name,phone,email,document_no,notes,created_at) VALUES(?,?,?,'','',?)",(name,phone,email,m.now_text()))
                    gid=db.execute("SELECT last_insert_rowid()").fetchone()[0]
                    db.execute("INSERT INTO guest_accounts(guest_id,username,password_salt,password_hash,created_at) VALUES(?,?,?,?,?)",(gid,username,salt,m.password_hash(pw,salt),m.now_text()))
                    uid=db.execute("SELECT last_insert_rowid()").fetchone()[0]
                    db.commit()
                except sqlite3.IntegrityError:
                    db.rollback();raise m.ApiError("此顧客帳號已使用",409)
                except Exception:
                    db.rollback();raise
            token,csrf=guest_login_session(uid)
            h.json_response({"username":username,"csrf":csrf},201,{"Set-Cookie":f"stayline_grand_guest_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200"});return True
        if method=="POST" and action=="login":
            d=h.read_json();uname=m.string(d.get("username"),"帳號",40)
            pw=d.get("password","")
            error_if(not isinstance(pw,str),"密碼格式錯誤",m)
            with m.connection() as db:
                u=db.execute("SELECT * FROM guest_accounts WHERE username=?",(uname,)).fetchone()
            error_if(not u or not hmac.compare_digest(m.password_hash(pw,u["password_salt"]),u["password_hash"]),"帳號或密碼錯誤",m,401)
            token,csrf=guest_login_session(u["id"])
            h.json_response({"username":uname,"csrf":csrf},200,{"Set-Cookie":f"stayline_grand_guest_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200"});return True
        sess=guest_session(h,m,method!="GET")
        with m.connection() as db:
            u=db.execute("SELECT a.username,g.* FROM guest_accounts a JOIN guests g ON a.guest_id=g.id WHERE a.id=?",(sess["uid"],)).fetchone()
            error_if(not u,"顧客帳號已失效",m,401)
            gid=u["id"]
            if method=="GET" and action=="me":
                h.json_response({"username":u["username"],"csrf":sess["csrf"],"guest":dict(u),"today":m.today().isoformat()});return True
            if method=="POST" and action=="logout":
                with GUEST_LOCK:GUEST_SESSIONS.pop(sess["token"],None)
                h.json_response({"ok":True},extra={"Set-Cookie":"stayline_grand_guest_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"});return True
            if method=="PUT" and action=="profile":
                d=h.read_json();name=m.string(d.get("full_name"),"姓名",80,True)
                phone=m.string(d.get("phone"),"電話",40);email=m.string(d.get("email"),"信箱",120)
                error_if(bool(email) and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+",email),"電子郵件格式不正確",m)
                db.execute("UPDATE guests SET full_name=?,phone=?,email=? WHERE id=?",(name,phone,email,gid))
                h.json_response({"ok":True});return True
            if method=="GET" and action=="reservations":
                rows=db.execute("""SELECT r.*,x.number room_number,x.room_type,
                   COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.reservation_id=r.id),0) paid_amount,
                   COALESCE((SELECT SUM(s.quantity*s.unit_price) FROM room_services s WHERE s.reservation_id=r.id AND s.status='completed'),0) services_amount
                   FROM reservations r JOIN rooms x ON x.id=r.room_id WHERE r.guest_id=? ORDER BY r.id DESC""",(gid,))
                h.json_response([dict(x) for x in rows]);return True
            if method=="POST" and action=="book":
                d=h.read_json()
                d["guest_id"]=gid
                db.execute("BEGIN IMMEDIATE")
                try:
                    vals=list(m.reservation_payload(db,d))
                    student=d.get("student_discount",False)
                    error_if(not isinstance(student,bool),"學生優惠格式不正確",m)
                    room=db.execute("SELECT room_type FROM rooms WHERE id=?",(vals[1],)).fetchone()
                    error_if(student and room["room_type"]!="standard","學生優惠僅適用標準客房",m)
                    arrival=d.get("expected_arrival_time","15:00")
                    error_if(not isinstance(arrival,str) or arrival not in {f"{h:02d}:00" for h in range(15,24)},"預計抵達時間必須為 15:00 至 23:00 的整點",m)
                    discount=round(vals[7]*0.10) if student else 0
                    vals[7]-=discount
                    code="HT"+m.now().strftime("%y%m%d")+secrets.token_hex(3).upper()
                    db.execute("""INSERT INTO reservations(code,guest_id,room_id,check_in,check_out,adults,children,price_per_night,total_amount,requests,created_at,source,discount_type,discount_amount,expected_arrival_time)
                      VALUES(?,?,?,?,?,?,?,?,?,?,?,'portal',?,?,?)""",(code,*vals,m.now_text(),"student" if student else "none",discount,arrival))
                    rid=db.execute("SELECT last_insert_rowid()").fetchone()[0]
                    if student:
                        student_name=m.string(d.get("student_name"),"學生證姓名",80,True)
                        school=m.string(d.get("student_school"),"學校名稱",120,True)
                        valid_until=m.string(d.get("student_valid_until"),"學生證有效日期",10,True)
                        expires=m.parse_date(valid_until,"學生證有效日期")
                        error_if(expires<m.today(),"學生證已過有效日期",m)
                        error_if(student_name.strip()!=u["full_name"].strip(),"學生證姓名必須與會員姓名一致",m)
                        db.execute("INSERT INTO student_verifications(reservation_id,student_name,school_name,valid_until,status,created_at) VALUES(?,?,?,?, 'pending',?)",(rid,student_name,school,valid_until,m.now_text()))
                    db.commit()
                except Exception:db.rollback();raise
                h.json_response({"id":rid,"code":code},201);return True
            if method=="POST" and action=="cancel":
                d=h.read_json();rid=m.positive_int(d.get("reservation_id"),"訂單")
                db.execute("BEGIN IMMEDIATE")
                try:
                    r=db.execute("SELECT * FROM reservations WHERE id=? AND guest_id=?",(rid,gid)).fetchone()
                    error_if(not r or r["status"]!="reserved","只能取消自己的未入住訂單",m)
                    paid=db.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE reservation_id=?",(rid,)).fetchone()[0]
                    error_if(paid>0,"此訂單已付款，請先聯絡櫃檯辦理退款",m)
                    db.execute("UPDATE reservations SET status='cancelled' WHERE id=?",(rid,));db.commit()
                except Exception:db.rollback();raise
                h.json_response({"ok":True});return True
            if method=="GET" and action=="services":
                result=[dict(x) for x in db.execute("""SELECT s.*,r.code reservation_code FROM room_services s
                  JOIN reservations r ON r.id=s.reservation_id WHERE r.guest_id=? ORDER BY s.id DESC""",(gid,))]
                h.json_response(result);return True
            if method=="POST" and action=="services":
                d=h.read_json();rid=m.positive_int(d.get("reservation_id"),"訂單")
                kind=m.require_enum(d.get("kind"),SERVICE_TYPES,"服務類型")
                qty=m.positive_int(d.get("quantity",1),"數量",1,20)
                note=m.string(d.get("note"),"服務說明",500)
                with m.connection() as db2:
                    db2.execute("BEGIN IMMEDIATE")
                    try:
                        r=db2.execute("SELECT status FROM reservations WHERE id=? AND guest_id=?",(rid,gid)).fetchone()
                        error_if(not r or r["status"]!="checked_in","只有已入住的本人訂單可以提出服務要求",m)
                        db2.execute("INSERT INTO room_services(reservation_id,kind,quantity,unit_price,note,status,created_at,updated_at) VALUES(?,?,?,?,?,'requested',?,?)",(rid,kind,qty,SERVICE_TYPES[kind][1],note,m.now_text(),m.now_text()))
                        sid=db2.execute("SELECT last_insert_rowid()").fetchone()[0];db2.commit()
                    except Exception:db2.rollback();raise
                h.json_response({"id":sid},201);return True
            if method=="GET" and action=="tickets":
                h.json_response([dict(x) for x in db.execute("SELECT * FROM support_tickets WHERE guest_id=? ORDER BY id DESC",(gid,))]);return True
            if method=="POST" and action=="tickets":
                d=h.read_json();subject=m.string(d.get("subject"),"問題主旨",100,True)
                message=m.string(d.get("message"),"問題內容",1000,True)
                db.execute("INSERT INTO support_tickets(guest_id,subject,message,created_at,updated_at) VALUES(?,?,?,?,?)",(gid,subject,message,m.now_text(),m.now_text()))
                h.json_response({"id":db.execute("SELECT last_insert_rowid()").fetchone()[0]},201);return True
            if method=="GET" and action=="requests":
                h.json_response([dict(x) for x in db.execute("""SELECT a.*,r.code reservation_code FROM guest_requests a
                      JOIN reservations r ON r.id=a.reservation_id WHERE r.guest_id=? ORDER BY a.id DESC""",(gid,))]);return True
            if method=="POST" and action=="requests":
                d=h.read_json();rid=m.positive_int(d.get("reservation_id"),"訂單")
                reqtype=m.require_enum(d.get("request_type"),("check_in","check_out"),"申請類型")
                db.execute("BEGIN IMMEDIATE")
                try:
                    r=db.execute("SELECT * FROM reservations WHERE id=? AND guest_id=?",(rid,gid)).fetchone()
                    error_if(not r,"找不到自己的訂單",m,404)
                    expected="reserved" if reqtype=="check_in" else "checked_in"
                    error_if(r["status"]!=expected,"目前的訂單狀態無法申請此操作",m)
                    error_if(reqtype=="check_in" and not(r["check_in"]<=m.today().isoformat()<r["check_out"]),"只有入住日到退房日前可以申請入住",m)
                    pending=db.execute("SELECT 1 FROM guest_requests WHERE reservation_id=? AND request_type=? AND status='pending'",(rid,reqtype)).fetchone()
                    error_if(bool(pending),"這筆申請正在等待櫃檯處理",m,409)
                    db.execute("INSERT INTO guest_requests(reservation_id,request_type,created_at) VALUES(?,?,?)",(rid,reqtype,m.now_text()))
                    reqid=db.execute("SELECT last_insert_rowid()").fetchone()[0];db.commit()
                except Exception:db.rollback();raise
                h.json_response({"id":reqid},201);return True
            if method=="GET" and action=="payments":
                h.json_response([dict(x) for x in db.execute("""SELECT p.*,r.code reservation_code FROM payments p
                 JOIN reservations r ON r.id=p.reservation_id WHERE r.guest_id=? ORDER BY p.id DESC""",(gid,))]);return True
        raise m.ApiError("找不到顧客功能",404)
    if not path.startswith("/api/ops/"):
        return False
    staff=staff_user(h,method,m)
    role=staff["role"]
    action=path.removeprefix("/api/ops/")
    with m.connection() as db:
        if method=="GET" and action=="overview":
            h.json_response(staff_overview(db,role,staff.get("employee_id")));return True
        if method=="POST" and action in ("attendance/clock-in","attendance/clock-out"):
            eid=staff.get("employee_id")
            error_if(not eid,"管理員沒有關聯的員工資料；請使用員工帳號打卡",m,403)
            d=m.today().isoformat()
            db.execute("BEGIN IMMEDIATE")
            try:
                att=db.execute("SELECT * FROM staff_attendance WHERE employee_id=? AND work_date=?",(eid,d)).fetchone()
                if action.endswith("clock-in"):
                    error_if(bool(att),"今天已經打過上班卡",m,409)
                    db.execute("INSERT INTO staff_attendance(employee_id,work_date,clock_in) VALUES(?,?,?)",(eid,d,m.now_text()))
                else:
                    error_if(not att or att["clock_out"],"今天尚未打上班卡或已打下班卡",m)
                    db.execute("UPDATE staff_attendance SET clock_out=? WHERE id=?",(m.now_text(),att["id"]))
                db.commit()
            except Exception:db.rollback();raise
            h.json_response({"ok":True});return True
        match=re.fullmatch(r"requests/(\d+)",action)
        if method=="PATCH" and match:
            error_if(role=="housekeeping","房務人員無法審核入住／退房申請",m,403)
            d=h.read_json();status=m.require_enum(d.get("status"),("approved","rejected"),"審核結果")
            note=m.string(d.get("staff_note"),"櫃檯備註",250)
            db.execute("BEGIN IMMEDIATE")
            try:
                rid=int(match[1]);req=db.execute("SELECT * FROM guest_requests WHERE id=?",(rid,)).fetchone()
                error_if(not req,"申請不存在",m,404)
                error_if(req["status"]!="pending","此申請已處理",m)
                book=m.fetch_reservation(db,req["reservation_id"])
                if status=="approved":
                    if req["request_type"]=="check_in":
                        error_if(book["status"]!="reserved","此訂單目前無法入住",m)
                        error_if(not(book["check_in"]<=m.today().isoformat()<book["check_out"]),"只有入住當日到退房日前可批准入住",m)
                        room=m.fetch_room(db,book["room_id"])
                        error_if(room["housekeeping"]!="clean" or not room["enabled"],"房間尚未清潔完成或已停用",m)
                        occ=db.execute("SELECT 1 FROM reservations WHERE room_id=? AND status='checked_in'",(book["room_id"],)).fetchone()
                        error_if(bool(occ),"房間已有住客",m)
                        db.execute("UPDATE reservations SET status='checked_in',actual_check_in=? WHERE id=?",(m.now_text(),book["id"]))
                    else:
                        error_if(book["status"]!="checked_in","此訂單目前無法退房",m)
                        paid=db.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE reservation_id=?",(book["id"],)).fetchone()[0]
                        due=bill_total(db,book["id"])
                        error_if(paid<due,f"仍有未結清金額 NT$ {due-paid:,}",m)
                        db.execute("UPDATE reservations SET status='checked_out',actual_check_out=? WHERE id=?",(m.now_text(),book["id"]))
                        db.execute("UPDATE rooms SET housekeeping='dirty' WHERE id=?",(book["room_id"],))
                db.execute("UPDATE guest_requests SET status=?,staff_note=?,processed_at=? WHERE id=?",(status,note,m.now_text(),rid))
                db.commit()
            except Exception:db.rollback();raise
            h.json_response({"ok":True});return True
        if method=="POST" and action=="employees":
            error_if(role!="admin","只有管理員可新增員工",m,403)
            d=h.read_json();name=m.string(d.get("full_name"),"員工姓名",80,True)
            pos=m.string(d.get("position"),"職位",80,True);dept=m.string(d.get("department"),"部門",80,True)
            phone=m.string(d.get("phone"),"電話",40);email=m.string(d.get("email"),"信箱",120)
            hired=m.parse_date(d.get("hire_date"),"到職日期").isoformat()
            shift_id=m.positive_int(d.get("shift_id",0),"班次",0)
            if shift_id and not db.execute("SELECT 1 FROM shifts WHERE id=?",(shift_id,)).fetchone():raise m.ApiError("班次不存在")
            db.execute("INSERT INTO employees(full_name,position,department,phone,email,hire_date,shift_id,created_at) VALUES(?,?,?,?,?,?,?,?)",(name,pos,dept,phone,email,hired,shift_id or None,m.now_text()))
            h.json_response({"id":db.execute("SELECT last_insert_rowid()").fetchone()[0]},201);return True
        match=re.fullmatch(r"employees/(\d+)",action)
        if method=="PUT" and match:
            error_if(role!="admin","只有管理員可更新員工",m,403)
            d=h.read_json();eid=int(match[1]);name=m.string(d.get("full_name"),"姓名",80,True)
            pos=m.string(d.get("position"),"職位",80,True);dept=m.string(d.get("department"),"部門",80,True)
            status=m.require_enum(d.get("status"),EMPLOYEE_STATUSES,"在職狀態")
            phone=m.string(d.get("phone"),"電話",40);email=m.string(d.get("email"),"電子信箱",120)
            hired=m.parse_date(d.get("hire_date"),"到職日期").isoformat()
            shift_id=m.positive_int(d.get("shift_id",0),"班次",0)
            if shift_id and not db.execute("SELECT 1 FROM shifts WHERE id=?",(shift_id,)).fetchone():raise m.ApiError("班次不存在")
            result=db.execute("UPDATE employees SET full_name=?,position=?,department=?,status=?,phone=?,email=?,hire_date=?,shift_id=? WHERE id=?",(name,pos,dept,status,phone,email,hired,shift_id or None,eid))
            error_if(not result.rowcount,"找不到員工",m,404)
            h.json_response({"ok":True});return True
        if method=="POST" and action=="accounts":
            error_if(role!="admin","只有管理員可建立員工登入帳號",m,403)
            d=h.read_json();eid=m.positive_int(d.get("employee_id"),"員工")
            username=m.string(d.get("username"),"帳號",40,True)
            password=d.get("password");staff_role=m.require_enum(d.get("role"),STAFF_ROLES,"員工權限")
            error_if(not re.fullmatch(r"[a-zA-Z0-9_]{3,40}",username),"帳號限 3–40 個英數字或底線",m)
            error_if(not isinstance(password,str) or not (8<=len(password)<=128),"密碼需要 8–128 字元",m)
            error_if(not db.execute("SELECT 1 FROM employees WHERE id=?",(eid,)).fetchone(),"找不到指定員工",m)
            error_if(bool(db.execute("SELECT 1 FROM users WHERE employee_id=?",(eid,)).fetchone()),"此員工已有登入帳號",m,409)
            salt=secrets.token_hex(16)
            try:
                db.execute("INSERT INTO users(username,password_salt,password_hash,created_at,role,employee_id) VALUES(?,?,?,?,?,?)",(username,salt,m.password_hash(password,salt),m.now_text(),staff_role,eid))
            except sqlite3.IntegrityError:raise m.ApiError("帳號已被使用",409)
            h.json_response({"ok":True},201);return True
        if method=="POST" and action=="shifts":
            error_if(role!="admin","只有管理員可管理班次",m,403)
            d=h.read_json();name=m.string(d.get("name"),"班次名稱",50,True)
            a=m.string(d.get("start_time"),"上班時間",5,True);b=m.string(d.get("end_time"),"下班時間",5,True)
            error_if(not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d",a) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d",b),"班次時間必須為 HH:MM",m)
            try:db.execute("INSERT INTO shifts(name,start_time,end_time) VALUES(?,?,?)",(name,a,b))
            except sqlite3.IntegrityError:raise m.ApiError("班次名稱重複",409)
            h.json_response({"ok":True},201);return True
        match=re.fullmatch(r"shifts/(\d+)",action)
        if method in ("PUT","DELETE") and match:
            error_if(role!="admin","只有管理員可管理班次",m,403)
            sid=int(match[1])
            error_if(not db.execute("SELECT 1 FROM shifts WHERE id=?",(sid,)).fetchone(),"找不到班次",m,404)
            if method=="DELETE":
                count=db.execute("SELECT COUNT(*) FROM employees WHERE shift_id=?",(sid,)).fetchone()[0]
                error_if(count>0,f"此班次仍有 {count} 位員工使用，請先調整員工班次",m,409)
                db.execute("DELETE FROM shifts WHERE id=?",(sid,))
                h.json_response({"ok":True});return True
            d=h.read_json();name=m.string(d.get("name"),"班次名稱",50,True)
            a=m.string(d.get("start_time"),"上班時間",5,True)
            b=m.string(d.get("end_time"),"下班時間",5,True)
            error_if(not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d",a) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d",b),"班次時間必須為 HH:MM",m)
            try:db.execute("UPDATE shifts SET name=?,start_time=?,end_time=? WHERE id=?",(name,a,b,sid))
            except sqlite3.IntegrityError:raise m.ApiError("班次名稱重複",409)
            h.json_response({"ok":True});return True
        if method=="POST" and action=="leaves":
            error_if(role!="admin","只有管理員可登記請假",m,403)
            d=h.read_json();eid=m.positive_int(d.get("employee_id"),"員工")
            leave_type=m.string(d.get("leave_type"),"假別",40,True);note=m.string(d.get("notes"),"備註",400)
            a=m.parse_date(d.get("start_date"),"請假起日");b=m.parse_date(d.get("end_date"),"請假迄日")
            error_if(b<a,"請假結束日不可早於開始日",m)
            error_if(not db.execute("SELECT 1 FROM employees WHERE id=?",(eid,)).fetchone(),"員工不存在",m)
            db.execute("INSERT INTO staff_leaves(employee_id,leave_type,start_date,end_date,notes,created_at) VALUES(?,?,?,?,?,?)",(eid,leave_type,a.isoformat(),b.isoformat(),note,m.now_text()))
            h.json_response({"ok":True},201);return True
        match=re.fullmatch(r"leaves/(\d+)",action)
        if method=="PATCH" and match:
            error_if(role!="admin","只有管理員可審核請假",m,403)
            d=h.read_json();s=m.require_enum(d.get("status"),LEAVE_STATUSES,"假單狀態")
            result=db.execute("UPDATE staff_leaves SET status=? WHERE id=?",(s,int(match[1])))
            error_if(not result.rowcount,"找不到請假紀錄",m,404)
            h.json_response({"ok":True});return True
        if method=="POST" and action=="training":
            error_if(role!="admin","只有管理員可新增培訓紀錄",m,403)
            d=h.read_json();eid=m.positive_int(d.get("employee_id"),"員工")
            title=m.string(d.get("title"),"培訓項目",100,True)
            dt=m.parse_date(d.get("training_date"),"培訓日期").isoformat()
            outcome=m.string(d.get("outcome"),"結果",300)
            error_if(not db.execute("SELECT 1 FROM employees WHERE id=?",(eid,)).fetchone(),"找不到員工",m)
            db.execute("INSERT INTO staff_training(employee_id,title,training_date,outcome,created_at) VALUES(?,?,?,?,?)",(eid,title,dt,outcome,m.now_text()))
            h.json_response({"ok":True},201);return True
        if method=="POST" and action=="payroll":
            error_if(role!="admin","只有管理員可登記薪資",m,403)
            d=h.read_json();eid=m.positive_int(d.get("employee_id"),"員工")
            period=m.string(d.get("pay_period"),"薪資月份",7,True)
            error_if(not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])",period),"薪資月份需 YYYY-MM",m)
            amount=m.positive_int(d.get("amount"),"薪資金額",0,10000000)
            paid=m.parse_date(d.get("paid_on"),"發薪日").isoformat()
            note=m.string(d.get("note"),"備註",250)
            error_if(not db.execute("SELECT 1 FROM employees WHERE id=?",(eid,)).fetchone(),"找不到員工",m)
            try:db.execute("INSERT INTO payroll(employee_id,pay_period,amount,paid_on,note) VALUES(?,?,?,?,?)",(eid,period,amount,paid,note))
            except sqlite3.IntegrityError:raise m.ApiError("此員工該月份已有薪資紀錄",409)
            h.json_response({"ok":True},201);return True
        match=re.fullmatch(r"services/(\d+)",action)
        if method=="PATCH" and match:
            d=h.read_json();sid=int(match[1]);status=m.require_enum(d.get("status"),SERVICE_STATUSES,"服務狀態")
            error_if(role=="housekeeping" and status not in ("in_progress","completed"),"房務人員只能接單或完成服務",m,403)
            db.execute("BEGIN IMMEDIATE")
            try:
                svc=db.execute("SELECT * FROM room_services WHERE id=?",(sid,)).fetchone()
                error_if(not svc,"服務單不存在",m,404)
                r=db.execute("SELECT status FROM reservations WHERE id=?",(svc["reservation_id"],)).fetchone()
                error_if(r["status"]!="checked_in" and status=="completed","退房後不能再產生服務費",m)
                error_if(svc["status"] in ("completed","rejected"),"已結束的服務單不能修改",m)
                error_if(status=="completed" and svc["status"] not in ("requested","in_progress"),"服務狀態不正確",m)
                db.execute("UPDATE room_services SET status=?,updated_at=? WHERE id=?",(status,m.now_text(),sid));db.commit()
            except Exception:db.rollback();raise
            h.json_response({"ok":True});return True
        match=re.fullmatch(r"tickets/(\d+)",action)
        if method=="PATCH" and match:
            error_if(role=="housekeeping","房務人員無法處理客服工單",m,403)
            d=h.read_json();status=m.require_enum(d.get("status"),TICKET_STATUSES,"工單狀態")
            reply=m.string(d.get("reply"),"回覆內容",1000)
            error_if(status=="replied" and not reply,"標記已回覆時必須輸入回覆內容",m)
            result=db.execute("UPDATE support_tickets SET status=?,reply=?,updated_at=? WHERE id=?",(status,reply,m.now_text(),int(match[1])))
            error_if(not result.rowcount,"找不到客服工單",m,404)
            h.json_response({"ok":True});return True
        match=re.fullmatch(r"rooms/(\d+)/housekeeping",action)
        if method=="PATCH" and match:
            d=h.read_json();status=m.require_enum(d.get("housekeeping"),m.HOUSEKEEPING,"清潔狀態")
            rid=int(match[1]);room=m.fetch_room(db,rid)
            occupied=db.execute("SELECT 1 FROM reservations WHERE room_id=? AND status='checked_in'",(rid,)).fetchone()
            error_if(bool(occupied) and status!="clean","目前有房客入住，不能標記待清潔",m)
            db.execute("UPDATE rooms SET housekeeping=? WHERE id=?",(status,rid))
            h.json_response({"ok":True});return True
    raise m.ApiError("找不到此操作或權限不足",404)
