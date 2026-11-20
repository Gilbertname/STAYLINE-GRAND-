#!/usr/bin/env python3
"""STAYLINE GRAND 飯店管理系統：使用 Python 標準函式庫的本機 Web API。"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import sys
import hotel_modules
import checkout25
import threading
import time
from datetime import date, datetime, timedelta, timezone
from contextlib import contextmanager
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("HOTEL_DB_PATH", str(ROOT / "stayline_grand.db")))
# 台灣全年固定 UTC+8：Windows 沒有 tzdata 時也能直接執行。
# 這個系統只作台灣本機示範，不使用有夏令時間的時區。
try:
    TZ = ZoneInfo("Asia/Taipei")
except Exception:
    TZ = timezone(timedelta(hours=8), name="Asia/Taipei")
SESSIONS: dict[str, dict] = {}
SESSION_LOCK = threading.Lock()
LOGIN_ATTEMPTS: dict[str, list[float]] = {}
ATTEMPT_LOCK = threading.Lock()
ROOM_TYPES = {"standard": "標準客房", "deluxe": "豪華客房", "suite": "行政套房"}
HOUSEKEEPING = {"clean": "已清潔", "dirty": "待清潔", "cleaning": "清潔中"}
RESERVATION_STATUS = {"reserved": "已預訂", "checked_in": "已入住", "checked_out": "已退房", "cancelled": "已取消"}
PAYMENT_METHODS = {"cash": "現金", "card": "信用卡", "transfer": "轉帳"}

class ApiError(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status
        super().__init__(message)

def now():
    return datetime.now(TZ)

def today():
    return now().date()

def now_text():
    return now().strftime("%Y-%m-%d %H:%M:%S")

@contextmanager
def connection():
    db = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    try:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=10000")
        yield db
        if db.in_transaction:
            db.commit()
    except Exception:
        if db.in_transaction:
            db.rollback()
        raise
    finally:
        db.close()

def rowdict(row):
    return dict(row) if row is not None else None

def init_db(seed=True):
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connection() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript('''
            CREATE TABLE IF NOT EXISTS users (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              username TEXT NOT NULL UNIQUE,
              password_salt TEXT NOT NULL,
              password_hash TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS rooms (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              number TEXT NOT NULL UNIQUE,
              room_type TEXT NOT NULL CHECK(room_type IN ('standard','deluxe','suite')),
              floor INTEGER NOT NULL,
              capacity INTEGER NOT NULL CHECK(capacity > 0),
              price INTEGER NOT NULL CHECK(price > 0),
              enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
              housekeeping TEXT NOT NULL DEFAULT 'clean' CHECK(housekeeping IN ('clean','dirty','cleaning')),
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS guests (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              full_name TEXT NOT NULL,
              phone TEXT NOT NULL DEFAULT '',
              email TEXT NOT NULL DEFAULT '',
              document_no TEXT NOT NULL DEFAULT '',
              notes TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reservations (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              code TEXT NOT NULL UNIQUE,
              guest_id INTEGER NOT NULL REFERENCES guests(id) ON DELETE RESTRICT,
              room_id INTEGER NOT NULL REFERENCES rooms(id) ON DELETE RESTRICT,
              check_in TEXT NOT NULL,
              check_out TEXT NOT NULL,
              adults INTEGER NOT NULL CHECK(adults > 0),
              children INTEGER NOT NULL DEFAULT 0 CHECK(children >= 0),
              status TEXT NOT NULL DEFAULT 'reserved' CHECK(status IN ('reserved','checked_in','checked_out','cancelled')),
              price_per_night INTEGER NOT NULL CHECK(price_per_night > 0),
              total_amount INTEGER NOT NULL CHECK(total_amount > 0),
              requests TEXT NOT NULL DEFAULT '',
              actual_check_in TEXT,
              actual_check_out TEXT,
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_reservation_room_dates ON reservations(room_id,check_in,check_out,status);
            CREATE TABLE IF NOT EXISTS payments (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              reservation_id INTEGER NOT NULL REFERENCES reservations(id) ON DELETE RESTRICT,
              amount INTEGER NOT NULL CHECK(amount > 0),
              method TEXT NOT NULL CHECK(method IN ('cash','card','transfer')),
              note TEXT NOT NULL DEFAULT '',
              paid_at TEXT NOT NULL
            );
        ''')
        if seed and db.execute("SELECT COUNT(*) FROM rooms").fetchone()[0] == 0:
            samples = [
                ("101","standard",1,2,2200),("102","standard",1,2,2200),
                ("103","standard",1,2,2200),("104","deluxe",1,3,3500),
                ("201","standard",2,2,2400),("202","standard",2,2,2400),
                ("203","deluxe",2,3,3500),("204","deluxe",2,3,3500),
                ("301","suite",3,4,5800),("302","suite",3,4,5800),
                ("303","deluxe",3,3,3800),("304","deluxe",3,3,3800),
            ]
            db.executemany("INSERT INTO rooms(number,room_type,floor,capacity,price,created_at) VALUES(?,?,?,?,?,?)", [(*x,now_text()) for x in samples])
        hotel_modules.init_extension(db,sys.modules[__name__])
        checkout25.init_extension(db)

def positive_int(value, name, minimum=1, maximum=100000000):
    if isinstance(value, bool):
        raise ApiError(f"{name}必須是整數")
    try:
        n = int(value)
    except (TypeError, ValueError, OverflowError):
        raise ApiError(f"{name}必須是整數")
    if str(value).strip() != str(n) and not isinstance(value, int):
        raise ApiError(f"{name}必須是整數")
    if not minimum <= n <= maximum:
        raise ApiError(f"{name}必須介於 {minimum} 至 {maximum} 之間")
    return n

def string(value, name, max_length=200, required=False):
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ApiError(f"{name}必須是文字")
    value = value.strip()
    if required and not value:
        raise ApiError(f"請輸入{name}")
    if len(value) > max_length:
        raise ApiError(f"{name}不能超過 {max_length} 字元")
    return value

def parse_date(value, name):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ApiError(f"{name}格式必須是 YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ApiError(f"{name}不是有效日期")

def require_enum(value, values, name):
    if value not in values:
        raise ApiError(f"{name}選項無效")
    return value

def password_hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 300_000).hex()

def user_count(db):
    return db.execute("SELECT COUNT(*) FROM users").fetchone()[0]

def make_session(uid):
    token = secrets.token_urlsafe(40)
    csrf = secrets.token_urlsafe(32)
    with SESSION_LOCK:
        SESSIONS[token] = {"uid":uid,"csrf":csrf,"expires":time.time()+12*3600}
    return token, csrf

def get_session(handler):
    raw = handler.headers.get("Cookie", "")
    try:
        c = SimpleCookie(); c.load(raw)
        token = c["stayline_grand_staff_session"].value if "stayline_grand_staff_session" in c else ""
    except Exception:
        return None
    with SESSION_LOCK:
        session = SESSIONS.get(token)
        if not session:
            return None
        if session["expires"] <= time.time():
            SESSIONS.pop(token, None)
            return None
        return dict(session, token=token)

def authenticate(handler, write=False):
    session = get_session(handler)
    if not session:
        raise ApiError("登入已過期，請重新登入", 401)
    if write and not hmac.compare_digest(handler.headers.get("X-CSRF-Token", ""), session["csrf"]):
        raise ApiError("安全驗證失敗，請重新整理頁面", 403)
    return session

def room_payload(data, update=False):
    number = string(data.get("number"), "房號", 12, True)
    if not re.fullmatch(r"[A-Za-z0-9-]{1,12}", number):
        raise ApiError("房號只能包含英文字母、數字及連字號")
    room_type = require_enum(data.get("room_type"), ROOM_TYPES, "房型")
    floor = positive_int(data.get("floor"), "樓層", 0, 200)
    capacity = positive_int(data.get("capacity"), "入住人數", 1, 20)
    price = positive_int(data.get("price"), "每晚房價", 1, 1_000_000)
    enabled = data.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ApiError("啟用狀態必須是布林值")
    housekeeping = require_enum(data.get("housekeeping", "clean"), HOUSEKEEPING, "清潔狀態")
    bed_type=string(data.get("bed_type","double"),"床型",30,True)
    description=string(data.get("description",""),"客房介紹",400)
    return (number,room_type,floor,capacity,price,int(enabled),housekeeping,bed_type,description)

def guest_payload(data):
    full_name = string(data.get("full_name"),"房客姓名",80,True)
    phone = string(data.get("phone"),"電話",40)
    email = string(data.get("email"),"電子郵件",120)
    doc = string(data.get("document_no"),"證件號碼",60)
    notes = string(data.get("notes"),"備註",500)
    if email and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise ApiError("電子郵件格式不正確")
    return full_name,phone,email,doc,notes

def fetch_room(db, rid):
    r = db.execute("SELECT * FROM rooms WHERE id=?",(rid,)).fetchone()
    if not r:
        raise ApiError("找不到指定客房",404)
    return r

def fetch_guest(db, gid):
    r = db.execute("SELECT * FROM guests WHERE id=?",(gid,)).fetchone()
    if not r:
        raise ApiError("找不到指定房客",404)
    return r

def fetch_reservation(db, rid):
    r = db.execute("SELECT * FROM reservations WHERE id=?",(rid,)).fetchone()
    if not r:
        raise ApiError("找不到指定訂單",404)
    return r

def overlap(db, rid, start, end, exclude_id=0):
    return db.execute('''SELECT id, code FROM reservations WHERE room_id=?
          AND status IN ('reserved','checked_in') AND check_in < ? AND check_out > ? AND id<>?
          LIMIT 1''',(rid,end,start,exclude_id)).fetchone()

def reservation_payload(db, data, exclude_id=0):
    gid=positive_int(data.get("guest_id"),"房客")
    rid=positive_int(data.get("room_id"),"客房")
    guest=fetch_guest(db,gid)
    room=fetch_room(db,rid)
    if not room["enabled"]:
        raise ApiError("此房間已停用")
    start=parse_date(data.get("check_in"),"入住日期")
    end=parse_date(data.get("check_out"),"退房日期")
    if start < today():
        raise ApiError("新訂單的入住日期不能早於今天")
    if end <= start:
        raise ApiError("退房日期必須晚於入住日期")
    nights=(end-start).days
    if nights > 365:
        raise ApiError("單筆住宿不可超過365晚")
    adults=positive_int(data.get("adults",1),"成人數",1,20)
    children=positive_int(data.get("children",0),"兒童數",0,20)
    if adults+children > room["capacity"]:
        raise ApiError(f"此客房最多可住 {room['capacity']} 人")
    if overlap(db,rid,start.isoformat(),end.isoformat(),exclude_id):
        raise ApiError("這段日期客房已有訂單，請更換客房或日期",409)
    requests=string(data.get("requests"),"特殊需求",500)
    return (guest["id"], rid, start.isoformat(), end.isoformat(), adults, children, room["price"], nights*room["price"], requests)

def reservation_rows(db):
    return [dict(r) for r in db.execute('''
       SELECT x.*, g.full_name guest_name, g.phone guest_phone, r.number room_number,
              r.room_type room_type, r.housekeeping housekeeping,
              COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.reservation_id=x.id),0) paid_amount,
              x.total_amount + COALESCE((SELECT SUM(s.quantity*s.unit_price) FROM room_services s WHERE s.reservation_id=x.id AND s.status='completed'),0) bill_amount
       FROM reservations x JOIN guests g ON x.guest_id=g.id
       JOIN rooms r ON x.room_id=r.id ORDER BY x.created_at DESC, x.id DESC
    ''')]

def dashboard_data(db):
    d=today().isoformat(); month=d[:7]; week_start=today()-timedelta(days=6)
    total=db.execute("SELECT COUNT(*) FROM rooms WHERE enabled=1").fetchone()[0]
    occupied=db.execute("SELECT COUNT(DISTINCT room_id) FROM reservations WHERE status='checked_in'").fetchone()[0]
    arrivals=db.execute("SELECT COUNT(*) FROM reservations WHERE status='reserved' AND check_in=?",(d,)).fetchone()[0]
    departures=db.execute("SELECT COUNT(*) FROM reservations WHERE status='checked_in' AND check_out=?",(d,)).fetchone()[0]
    income=db.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE substr(paid_at,1,7)=?",(month,)).fetchone()[0]
    outstanding=db.execute("SELECT COALESCE(SUM(total_amount),0) FROM reservations WHERE status IN ('reserved','checked_in')").fetchone()[0] - db.execute('''SELECT COALESCE(SUM(p.amount),0) FROM payments p JOIN reservations r ON r.id=p.reservation_id WHERE r.status IN ('reserved','checked_in')''').fetchone()[0]
    outstanding += db.execute("""SELECT COALESCE(SUM(s.quantity*s.unit_price),0) FROM room_services s
          JOIN reservations r ON r.id=s.reservation_id WHERE s.status='completed' AND r.status IN ('reserved','checked_in')""").fetchone()[0]
    trends={ (week_start+timedelta(days=i)).isoformat():0 for i in range(7) }
    for r in db.execute("SELECT substr(paid_at,1,10) d, SUM(amount) total FROM payments WHERE paid_at>=? GROUP BY substr(paid_at,1,10)",(week_start.isoformat(),)):
        if r["d"] in trends:trends[r["d"]]=r["total"]
    return {"room_count":total,"occupied":occupied,"available_now":max(total-occupied,0),"occupancy_rate":round(occupied/total*100) if total else 0,"arrivals_today":arrivals,"departures_today":departures,"monthly_revenue":income,"outstanding":outstanding,"daily_revenue":[{"date":k,"amount":v} for k,v in trends.items()],"recent":reservation_rows(db)[:6]}

class HotelHandler(BaseHTTPRequestHandler):
    server_version = "HotelManager/1.0"

    def log_message(self, fmt, *args):
        print(f"[{now_text()}] {self.address_string()} - {fmt % args}")

    def _headers(self, status=200, content_type="application/json; charset=utf-8", extra=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("X-Frame-Options","DENY")
        self.send_header("Referrer-Policy","same-origin")
        self.send_header("Content-Security-Policy","default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'")
        if extra:
            for name,value in extra.items(): self.send_header(name,value)
        self.end_headers()

    def json_response(self, obj, status=200, extra=None):
        blob=json.dumps(obj,ensure_ascii=False,separators=(",",":")).encode("utf-8")
        self._headers(status, extra=extra)
        self.wfile.write(blob)

    def file_response(self, filename, ctype):
        blob=(ROOT/filename).read_bytes()
        self._headers(200,ctype)
        self.wfile.write(blob)

    def read_json(self):
        if not self.headers.get("Content-Type", "").split(";")[0].strip().lower()=="application/json":
            raise ApiError("請使用 application/json 格式",415)
        try:
            length=int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ApiError("無效的請求長度")
        if length <= 0 or length > 65536:
            raise ApiError("請求內容不得為空或超過 64KB",413)
        try:
            payload=json.loads(self.rfile.read(length))
        except (json.JSONDecodeError,UnicodeDecodeError):
            raise ApiError("JSON 資料格式錯誤")
        if not isinstance(payload,dict):
            raise ApiError("請傳入 JSON 物件")
        return payload

    def dispatch(self, method):
        path=urlsplit(self.path).path
        query=parse_qs(urlsplit(self.path).query)
        try:
            # Only allow three explicitly bundled photos; no arbitrary file paths.
            if method=="GET" and path in ("/room-images/standard.webp","/room-images/deluxe.webp","/room-images/suite.webp"):
                return self.file_response(path.lstrip("/"),"image/webp")
            if method=="GET" and path in ("/","/styles.css","/app.js","/ops.js","/ops.css"):
                files={
                    "/":("index.html","text/html; charset=utf-8"),
                    "/styles.css":("styles.css","text/css; charset=utf-8"),
                    "/app.js":("app.js","text/javascript; charset=utf-8"),
                    "/ops.js":("ops.js","text/javascript; charset=utf-8"),
                    "/ops.css":("ops.css","text/css; charset=utf-8"),
                }
                return self.file_response(*files[path])
            if not path.startswith("/api/") and path not in ("/guest","/guest.js","/guest.css","/student-review","/student-review.js"):
                raise ApiError("找不到頁面",404)
            if method in ("POST","PUT","PATCH","DELETE"):
                origin=self.headers.get("Origin")
                if origin:
                    host=self.headers.get("Host", "")
                    if urlsplit(origin).netloc != host or urlsplit(origin).scheme not in ("http","https"):
                        raise ApiError("不允許跨網站修改資料",403)
            if checkout25.handle(self,method,path,query,sys.modules[__name__]):
                return
            if hotel_modules.handle(self,method,path,query,sys.modules[__name__]):
                return
            if method=="GET" and path=="/api/bootstrap":
                with connection() as db:
                    return self.json_response({"needs_setup":user_count(db)==0})
            if method=="POST" and path=="/api/setup":
                return self.setup_admin(self.read_json())
            if method=="POST" and path=="/api/login":
                return self.login(self.read_json())
            if method=="GET" and path=="/api/me":
                s=authenticate(self)
                with connection() as db:
                    u=db.execute("SELECT username,role FROM users WHERE id=?",(s["uid"],)).fetchone()
                if not u: raise ApiError("帳號已失效",401)
                return self.json_response({"username":u["username"],"role":u["role"],"csrf":s["csrf"],"today":today().isoformat()})
            if method=="POST" and path=="/api/logout":
                s=authenticate(self,True)
                with SESSION_LOCK: SESSIONS.pop(s["token"],None)
                return self.json_response({"ok":True},extra={"Set-Cookie":"stayline_grand_staff_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"})
            session=authenticate(self, method!="GET")
            with connection() as db:
                role=db.execute("SELECT role FROM users WHERE id=?",(session["uid"],)).fetchone()
                if not role or role["role"] not in ("admin","frontdesk"):
                    raise ApiError("此帳號沒有櫃檯操作權限",403)
                if method=="GET" and path=="/api/dashboard":
                    return self.json_response(dashboard_data(db))
                if method=="GET" and path=="/api/rooms":
                    rows=[dict(r) for r in db.execute('''SELECT rooms.*, EXISTS(
                         SELECT 1 FROM reservations x WHERE x.room_id=rooms.id AND x.status='checked_in') as occupied
                         FROM rooms ORDER BY floor, number''')]
                    return self.json_response(rows)
                if method=="GET" and path=="/api/rooms/available":
                    start=parse_date(query.get("check_in",[""])[0],"入住日期")
                    end=parse_date(query.get("check_out",[""])[0],"退房日期")
                    if start<today() or end<=start:
                        raise ApiError("請選擇今天或之後的有效入住及退房日期")
                    exclude=positive_int(query.get("exclude_id",["0"])[0],"排除訂單",0)
                    rows=[dict(r) for r in db.execute('''SELECT rooms.* FROM rooms WHERE enabled=1 AND NOT EXISTS (
                        SELECT 1 FROM reservations x WHERE x.room_id=rooms.id AND x.status IN ('reserved','checked_in')
                        AND x.id<>? AND x.check_in<? AND x.check_out>?
                        ) ORDER BY floor,number''',(exclude,end.isoformat(),start.isoformat()))]
                    return self.json_response(rows)
                if method=="POST" and path=="/api/rooms":
                    data=room_payload(self.read_json())
                    try:
                        db.execute("BEGIN IMMEDIATE")
                        db.execute("INSERT INTO rooms(number,room_type,floor,capacity,price,enabled,housekeeping,bed_type,description,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(*data,now_text()))
                        rid=db.execute("SELECT last_insert_rowid()").fetchone()[0]; db.commit()
                    except sqlite3.IntegrityError:
                        db.rollback();raise ApiError("房號已存在，請使用其他房號",409)
                    return self.json_response({"id":rid},201)
                if method=="GET" and path=="/api/guests":
                    return self.json_response([dict(r) for r in db.execute("SELECT * FROM guests ORDER BY id DESC")])
                if method=="POST" and path=="/api/guests":
                    data=guest_payload(self.read_json())
                    db.execute("INSERT INTO guests(full_name,phone,email,document_no,notes,created_at) VALUES(?,?,?,?,?,?)",(*data,now_text()))
                    return self.json_response({"id":db.execute("SELECT last_insert_rowid()").fetchone()[0]},201)
                if method=="GET" and path=="/api/reservations":
                    return self.json_response(reservation_rows(db))
                if method=="POST" and path=="/api/reservations":
                    data=self.read_json()
                    db.execute("BEGIN IMMEDIATE")
                    try:
                        vals=reservation_payload(db,data)
                        code="HT"+now().strftime("%y%m%d")+secrets.token_hex(3).upper()
                        db.execute('''INSERT INTO reservations(code,guest_id,room_id,check_in,check_out,adults,children,price_per_night,total_amount,requests,created_at)
                                      VALUES(?,?,?,?,?,?,?,?,?,?,?)''',(code,*vals,now_text()))
                        rid=db.execute("SELECT last_insert_rowid()").fetchone()[0];db.commit()
                    except Exception:
                        db.rollback();raise
                    return self.json_response({"id":rid,"code":code},201)
                if method=="GET" and path=="/api/payments":
                    rows=[dict(r) for r in db.execute('''SELECT p.*, x.code reservation_code, g.full_name guest_name, r.number room_number
                        FROM payments p JOIN reservations x ON x.id=p.reservation_id
                        JOIN guests g ON g.id=x.guest_id JOIN rooms r ON r.id=x.room_id
                        ORDER BY p.id DESC''')]
                    return self.json_response(rows)
                if method=="POST" and path=="/api/payments":
                    body=self.read_json()
                    rid=positive_int(body.get("reservation_id"),"訂單")
                    amount=positive_int(body.get("amount"),"收款金額",1,10_000_000)
                    method_name=require_enum(body.get("method"),PAYMENT_METHODS,"收款方式")
                    note=string(body.get("note"),"收款備註",300)
                    db.execute("BEGIN IMMEDIATE")
                    try:
                        r=fetch_reservation(db,rid)
                        if r["status"] in ("cancelled","checked_out"):
                            raise ApiError("已取消或已退房的訂單無法新增收款")
                        paid=db.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE reservation_id=?",(rid,)).fetchone()[0]
                        due=hotel_modules.bill_total(db,rid)
                        if amount>due-paid:
                            raise ApiError(f"收款超出剩餘尾款 NT$ {due-paid:,}")
                        db.execute("INSERT INTO payments(reservation_id,amount,method,note,paid_at) VALUES(?,?,?,?,?)",(rid,amount,method_name,note,now_text()))
                        pid=db.execute("SELECT last_insert_rowid()").fetchone()[0];db.commit()
                    except Exception:
                        db.rollback();raise
                    return self.json_response({"id":pid},201)
                match=re.fullmatch(r"/api/rooms/(\d+)",path)
                if match:
                    rid=int(match[1]); r=fetch_room(db,rid)
                    if method in ("PUT","PATCH"):
                        data=room_payload(self.read_json(),True)
                        db.execute("BEGIN IMMEDIATE")
                        try:
                            occupancy=db.execute("SELECT COUNT(*) FROM reservations WHERE room_id=? AND status='checked_in'",(rid,)).fetchone()[0]
                            if occupancy and (not data[5] or data[6]!="clean"):
                                raise ApiError("正在入住的客房不能停用或變更清潔狀態")
                            active=db.execute("SELECT COUNT(*) FROM reservations WHERE room_id=? AND status IN ('reserved','checked_in')",(rid,)).fetchone()[0]
                            if active and not data[5]:
                                raise ApiError("仍有有效訂單的客房不能停用")
                            db.execute("UPDATE rooms SET number=?,room_type=?,floor=?,capacity=?,price=?,enabled=?,housekeeping=?,bed_type=?,description=? WHERE id=?",(*data,rid))
                            db.commit()
                        except sqlite3.IntegrityError:
                            db.rollback();raise ApiError("房號已存在，請使用其他房號",409)
                        except Exception:
                            db.rollback();raise
                        return self.json_response({"ok":True})
                    if method=="DELETE":
                        try:
                            db.execute("DELETE FROM rooms WHERE id=?",(rid,))
                        except sqlite3.IntegrityError:
                            raise ApiError("此房間已有訂單紀錄，不能刪除，請改為停用",409)
                        return self.json_response({"ok":True})
                match=re.fullmatch(r"/api/guests/(\d+)",path)
                if match:
                    gid=int(match[1]);fetch_guest(db,gid)
                    if method in ("PUT","PATCH"):
                        data=guest_payload(self.read_json())
                        db.execute("UPDATE guests SET full_name=?,phone=?,email=?,document_no=?,notes=? WHERE id=?",(*data,gid))
                        return self.json_response({"ok":True})
                    if method=="DELETE":
                        try: db.execute("DELETE FROM guests WHERE id=?",(gid,))
                        except sqlite3.IntegrityError:raise ApiError("此房客已有訂單紀錄，不能刪除",409)
                        return self.json_response({"ok":True})
                match=re.fullmatch(r"/api/reservations/(\d+)",path)
                if match and method in ("PUT","PATCH"):
                    rid=int(match[1]);body=self.read_json()
                    db.execute("BEGIN IMMEDIATE")
                    try:
                        r=fetch_reservation(db,rid)
                        if r["status"]!="reserved":raise ApiError("只有尚未入住的預訂可以修改")
                        paid=db.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE reservation_id=?",(rid,)).fetchone()[0]
                        vals=list(reservation_payload(db,body,rid))
                        # Keep any existing educational student discount consistent when the front desk edits dates/room.
                        new_room=fetch_room(db,vals[1])
                        keep_student=r["discount_type"]=="student" and new_room["room_type"]=="standard"
                        discount=round(vals[7]*0.10) if keep_student else 0
                        vals[7]-=discount
                        if vals[7]<paid:raise ApiError("新訂單總額不能少於已收款金額")
                        db.execute('''UPDATE reservations SET guest_id=?,room_id=?,check_in=?,check_out=?,adults=?,children=?,price_per_night=?,total_amount=?,requests=?,discount_amount=?,discount_type=? WHERE id=?''',(*vals,discount,"student" if keep_student else "none",rid))
                        db.commit()
                    except Exception:
                        db.rollback();raise
                    return self.json_response({"ok":True})
                match=re.fullmatch(r"/api/reservations/(\d+)/(check-in|check-out|cancel)",path)
                if match and method=="POST":
                    rid=int(match[1]);action=match[2]
                    db.execute("BEGIN IMMEDIATE")
                    try:
                        r=fetch_reservation(db,rid)
                        if action=="check-in":
                            if r["status"]!="reserved":raise ApiError("只有已預訂的訂單可以辦理入住")
                            if not (r["check_in"]<=today().isoformat()<r["check_out"]):raise ApiError("只能在訂房入住日到退房日前辦理入住")
                            room=fetch_room(db,r["room_id"])
                            if room["housekeeping"]!="clean" or not room["enabled"]:raise ApiError("客房需先清潔完成且啟用，才能入住")
                            if db.execute("SELECT COUNT(*) FROM reservations WHERE room_id=? AND status='checked_in'",(r["room_id"],)).fetchone()[0]:raise ApiError("此客房已有人入住")
                            db.execute("UPDATE reservations SET status='checked_in',actual_check_in=? WHERE id=?",(now_text(),rid))
                        elif action=="check-out":
                            if r["status"]!="checked_in":raise ApiError("只有已入住的訂單可以辦理退房")
                            paid=db.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE reservation_id=?",(rid,)).fetchone()[0]
                            due=hotel_modules.bill_total(db,rid)
                            if paid<due:raise ApiError(f"請先結清剩餘款項 NT$ {due-paid:,}")
                            db.execute("UPDATE reservations SET status='checked_out',actual_check_out=? WHERE id=?",(now_text(),rid))
                            db.execute("UPDATE rooms SET housekeeping='dirty' WHERE id=?",(r["room_id"],))
                        elif action=="cancel":
                            if r["status"]!="reserved":raise ApiError("只有尚未入住的訂單可以取消")
                            paid=db.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE reservation_id=?",(rid,)).fetchone()[0]
                            if paid:raise ApiError("已有收款的訂單不能直接取消，請先以人工方式處理退款")
                            db.execute("UPDATE reservations SET status='cancelled' WHERE id=?",(rid,))
                        db.commit()
                    except Exception:
                        db.rollback();raise
                    return self.json_response({"ok":True})
            raise ApiError("找不到此 API 路徑",404)
        except ApiError as e:
            self.json_response({"error":e.message},e.status)
        except (BrokenPipeError,ConnectionResetError):
            return
        except Exception as e:
            print("API error:",repr(e))
            self.json_response({"error":"伺服器發生錯誤，請查看終端機日誌"},500)

    def setup_admin(self,data):
        username=string(data.get("username"),"管理員帳號",40,True)
        pwd=data.get("password")
        if not re.fullmatch(r"[a-zA-Z0-9_]{3,40}",username):raise ApiError("帳號須為3–40位英文字母、數字或底線")
        if not isinstance(pwd,str) or not (8<=len(pwd)<=128):raise ApiError("密碼長度必須介於8至128字元")
        salt=secrets.token_hex(16);digest=password_hash(pwd,salt)
        with connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                if user_count(db):raise ApiError("系統已完成初始化",409)
                db.execute("INSERT INTO users(username,password_salt,password_hash,created_at) VALUES(?,?,?,?)",(username,salt,digest,now_text()))
                uid=db.execute("SELECT last_insert_rowid()").fetchone()[0]
                db.commit()
            except Exception:
                db.rollback();raise
        token,csrf=make_session(uid)
        self.json_response({"username":username,"role":"admin","csrf":csrf,"today":today().isoformat()},201,{"Set-Cookie":f"stayline_grand_staff_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200"})

    def login(self,data):
        username=string(data.get("username"),"帳號",40)
        password=data.get("password","")
        if not isinstance(password,str):raise ApiError("密碼格式錯誤")
        ip=self.client_address[0]
        with ATTEMPT_LOCK:
            recent=[t for t in LOGIN_ATTEMPTS.get(ip,[]) if time.time()-t<300]
            LOGIN_ATTEMPTS[ip]=recent
            if len(recent)>=10:raise ApiError("登入失敗次數太多，請5分鐘後再試",429)
        with connection() as db:
            u=db.execute("""SELECT u.*,e.status employee_status FROM users u
                    LEFT JOIN employees e ON e.id=u.employee_id WHERE u.username=?""",(username,)).fetchone()
        if not u or (u["employee_id"] and u["employee_status"]!="active") or not hmac.compare_digest(password_hash(password,u["password_salt"]),u["password_hash"]):
            with ATTEMPT_LOCK:LOGIN_ATTEMPTS.setdefault(ip,[]).append(time.time())
            raise ApiError("帳號或密碼不正確",401)
        with ATTEMPT_LOCK:LOGIN_ATTEMPTS.pop(ip,None)
        token,csrf=make_session(u["id"])
        self.json_response({"username":u["username"],"role":u["role"],"csrf":csrf,"today":today().isoformat()},200,{"Set-Cookie":f"stayline_grand_staff_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200"})

    def do_GET(self):self.dispatch("GET")
    def do_POST(self):self.dispatch("POST")
    def do_PUT(self):self.dispatch("PUT")
    def do_PATCH(self):self.dispatch("PATCH")
    def do_DELETE(self):self.dispatch("DELETE")

def main():
    parser=argparse.ArgumentParser(description="STAYLINE GRAND 飯店管理系統")
    parser.add_argument("--host",default="127.0.0.1",help="預設只接受本機連線")
    parser.add_argument("--port",type=int,default=8100)
    args=parser.parse_args()
    init_db()
    server=ThreadingHTTPServer((args.host,args.port),HotelHandler)
    print(f"\n🏨 STAYLINE GRAND 飯店管理系統已啟動：http://{args.host}:{args.port}")
    print(f"📁 資料庫位置：{DB_PATH}")
    print("首次啟動請在瀏覽器建立管理員帳號，按 Ctrl+C 結束。\n")
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()

if __name__=="__main__":main()
