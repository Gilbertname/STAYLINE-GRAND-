"""Local-only, fake payments and in-person student-ID review. No real payment credentials."""
from __future__ import annotations
import re
import sqlite3
import hotel_modules


def init_extension(db):
    db.executescript("""
      CREATE TABLE IF NOT EXISTS student_verifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        reservation_id INTEGER NOT NULL UNIQUE REFERENCES reservations(id),
        student_name TEXT NOT NULL,
        school_name TEXT NOT NULL,
        valid_until TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
        reviewed_at TEXT,
        created_at TEXT NOT NULL
      );
      CREATE INDEX IF NOT EXISTS idx_student_verifications_status ON student_verifications(status);
    """)


def handle(h, method, path, query, m):
    if method=="GET" and path in ("/student-review","/student-review.js"):
        name,ctype=("student-review.html","text/html; charset=utf-8") if path=="/student-review" else ("student-review.js","text/javascript; charset=utf-8")
        h.file_response(name,ctype);return True
    if path.startswith("/api/portal/") and path.removeprefix("/api/portal/") in ("checkout","pay"):
        sess=hotel_modules.guest_session(h,m,method!="GET")
        with m.connection() as db:
            user=db.execute("SELECT guest_id FROM guest_accounts WHERE id=?",(sess["uid"],)).fetchone()
            if not user:raise m.ApiError("會員不存在",401)
            gid=user["guest_id"]
            if method=="GET" and path=="/api/portal/checkout":
                try:rid=m.positive_int(query.get("reservation_id",[""])[0],"訂單")
                except m.ApiError:raise
            elif method=="POST" and path=="/api/portal/pay":
                data=h.read_json();rid=m.positive_int(data.get("reservation_id"),"訂單")
            else:raise m.ApiError("不支援的操作",405)
            if method=="POST":db.execute("BEGIN IMMEDIATE")
            r=db.execute('''SELECT r.id,r.code,r.room_id,r.check_in,r.check_out,r.status,r.total_amount,r.discount_type,r.discount_amount,
                   COALESCE((SELECT SUM(amount) FROM payments WHERE reservation_id=r.id),0) paid_amount,
                   COALESCE((SELECT SUM(quantity*unit_price) FROM room_services WHERE reservation_id=r.id AND status='completed'),0) services_amount,
                   sv.status verification_status,sv.school_name,sv.valid_until
                   FROM reservations r LEFT JOIN student_verifications sv ON sv.reservation_id=r.id
                   WHERE r.id=? AND r.guest_id=?''',(rid,gid)).fetchone()
            if not r:raise m.ApiError("找不到自己的訂單",404)
            outstanding=max(0,r["total_amount"]+r["services_amount"]-r["paid_amount"])
            if method=="GET":
                h.json_response({**dict(r),"outstanding":outstanding,"simulation":True});return True
            if r["status"] not in ("reserved","checked_in"):
                raise m.ApiError("此訂單狀態無法付款")
            if outstanding<=0:raise m.ApiError("此訂單已結清",409)
            method_name=data.get("method")
            if method_name not in ("demo_card","demo_transfer","pay_at_hotel"):
                raise m.ApiError("付款方式無效")
            if method_name=="pay_at_hotel":
                db.commit();h.json_response({"status":"pay_at_hotel","outstanding":outstanding,"simulation":True});return True
            if r["discount_type"]=="student" and r["verification_status"]!="approved":
                raise m.ApiError("使用學生九折需先到櫃檯出示有效學生證，經人工審核後才能模擬付款",409)
            # Only fictional successful-payment entry; no gateway or card numbers, no credentials.
            db.execute("INSERT INTO payments(reservation_id,amount,method,note,paid_at) VALUES(?,?,?,?,?)",
                       (rid,outstanding,"card" if method_name=="demo_card" else "transfer","SIMULATION ONLY / not real money",m.now_text()))
            db.commit();h.json_response({"status":"paid_demo","amount":outstanding,"simulation":True});return True
    if path in ("/api/student-reviews", "/api/student-review"):
        session=m.authenticate(h,method!="GET")
        with m.connection() as db:
            u=db.execute("SELECT role FROM users WHERE id=?",(session["uid"],)).fetchone()
            if not u or u["role"]!="admin":raise m.ApiError("只有管理員能審核學生證",403)
            if method=="GET" and path=="/api/student-reviews":
                rows=db.execute('''SELECT sv.*,r.code,r.status reservation_status,r.discount_amount,
                 g.full_name member_name,x.number room_number FROM student_verifications sv
                 JOIN reservations r ON r.id=sv.reservation_id JOIN guests g ON g.id=r.guest_id
                 JOIN rooms x ON x.id=r.room_id ORDER BY sv.id DESC''')
                h.json_response([dict(x) for x in rows]);return True
            if method=="POST" and path=="/api/student-review":
                d=h.read_json();rid=m.positive_int(d.get("reservation_id"),"訂單");status=d.get("status")
                if status not in ("approved","rejected"):raise m.ApiError("審核狀態無效")
                db.execute("BEGIN IMMEDIATE")
                entry=db.execute('''SELECT sv.*,r.status reservation_status,r.total_amount,r.discount_amount,r.discount_type,r.check_in,r.check_out,r.room_id,
                     (SELECT COUNT(*) FROM payments WHERE reservation_id=r.id) payment_count FROM student_verifications sv
                     JOIN reservations r ON r.id=sv.reservation_id WHERE sv.reservation_id=?''',(rid,)).fetchone()
                if not entry or entry["status"]!="pending" or entry["reservation_status"]!="reserved":raise m.ApiError("此訂單無待審的學生證",409)
                if entry["payment_count"]:raise m.ApiError("有付款紀錄的訂單不能變更折扣",409)
                if status=="approved" and entry["valid_until"]<m.today().isoformat():raise m.ApiError("學生證已過期，不能核准",409)
                if status=="rejected":
                    db.execute("UPDATE reservations SET total_amount=total_amount+discount_amount,discount_amount=0,discount_type='none' WHERE id=?",(rid,))
                db.execute("UPDATE student_verifications SET status=?,reviewed_at=? WHERE reservation_id=?",(status,m.now_text(),rid))
                db.commit();h.json_response({"status":status});return True
        raise m.ApiError("找不到審核功能",404)
    return False
