"""End-to-end regression tests for STAYLINE v2, no third-party dependencies."""
import http.cookiejar
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import timedelta
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server

class TestUpgrade(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.prev=server.DB_PATH
        server.DB_PATH=Path(cls.tmp.name)/"hotel.db"
        server.init_db()
        cls.http=server.ThreadingHTTPServer(("127.0.0.1",0),server.HotelHandler)
        cls.url=f"http://127.0.0.1:{cls.http.server_port}"
        cls.th=threading.Thread(target=cls.http.serve_forever,daemon=True)
        cls.th.start()
        cls.admin=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        cls.customer=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        cls.housekeep=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        cls.acsrf="";cls.gcsrf="";cls.hcsrf=""
    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown();cls.http.server_close();cls.th.join(timeout=4)
        server.DB_PATH=cls.prev;cls.tmp.cleanup()
    @classmethod
    def req(cls,method,path,payload=None,who="admin"):
        obj={"admin":cls.admin,"guest":cls.customer,"housekeeping":cls.housekeep}[who]
        csrf={"admin":cls.acsrf,"guest":cls.gcsrf,"housekeeping":cls.hcsrf}[who]
        data=None if method=="GET" else json.dumps(payload if payload is not None else {},ensure_ascii=False).encode()
        req=urllib.request.Request(cls.url+path,method=method,data=data,headers={"Content-Type":"application/json","X-CSRF-Token":csrf})
        try:
            with obj.open(req,timeout=8) as result:
                return result.status, json.load(result)
        except urllib.error.HTTPError as e:
            return e.code,json.loads(e.read().decode())
    def test_00_frontend_assets(self):
        """Every JS/CSS file referenced by either HTML entry must return 200."""
        paths = {
            "/": "text/html",
            "/styles.css": "text/css",
            "/app.js": "text/javascript",
            "/ops.css": "text/css",
            "/ops.js": "text/javascript",
            "/guest": "text/html",
            "/guest.css": "text/css",
            "/guest.js": "text/javascript",
        }
        for path, content_type in paths.items():
            with self.subTest(path=path):
                with self.admin.open(self.url + path, timeout=8) as response:
                    self.assertEqual(response.status, 200)
                    self.assertIn(content_type, response.headers.get("Content-Type", ""))
                    self.assertTrue(response.read())

    def test_01_setup(self):
        status,reply=self.req("POST","/api/setup",{"username":"owner","password":"secretpassword321"})
        self.assertEqual(status,201);self.__class__.acsrf=reply["csrf"]
        self.assertEqual(reply["role"],"admin")
        self.assertEqual(self.req("GET","/api/ops/overview")[0],200)
        self.assertEqual(self.req("GET","/api/public/rooms")[0],200)
        rooms=self.req("GET","/api/rooms")[1];self.__class__.room=rooms[0]
    def test_02_customer_book_and_conflict(self):
        s,reply=self.req("POST","/api/portal/register",{"username":"demoGuest","password":"secretpassword321","full_name":"測試顧客","email":"guest@example.com","phone":"0912000000"},"guest")
        self.assertEqual(s,201);self.__class__.gcsrf=reply["csrf"]
        self.assertEqual(self.req("GET","/api/portal/me",who="guest")[0],200)
        start=server.today().isoformat();end=(server.today()+timedelta(days=1)).isoformat()
        self.__class__.start=start;self.__class__.end=end
        params={"room_id":self.room["id"],"check_in":start,"check_out":end,"adults":1,"children":0}
        s,b=self.req("POST","/api/portal/book",params,"guest")
        self.assertEqual(s,201);self.__class__.booking_id=b["id"]
        self.assertEqual(self.req("POST","/api/portal/book",params,"guest")[0],409)
        self.assertEqual(self.req("POST","/api/portal/services",{"reservation_id":b["id"],"kind":"food","quantity":1},"guest")[0],400)
        self.assertEqual(self.req("GET","/api/portal/reservations",who="guest")[1][0]["source"],"portal")
        # only authorized customer may place own bookings; stale csrf rejected
        self.__class__.gcsrf="wrong"
        self.assertEqual(self.req("POST","/api/portal/tickets",{"subject":"test","message":"hi"},"guest")[0],403)
        self.__class__.gcsrf=reply["csrf"]
    def test_03_employee_records_and_rights(self):
        s,e=self.req("POST","/api/ops/employees",{"full_name":"測試清潔員","position":"房務人員","department":"房務","hire_date":self.start,"phone":"0912345","shift_id":1})
        self.assertEqual(s,201);self.__class__.emp_id=e["id"]
        s,_=self.req("POST","/api/ops/accounts",{"employee_id":e["id"],"username":"housekeeper","password":"supersecret123","role":"housekeeping"})
        self.assertEqual(s,201)
        s,out=self.req("POST","/api/login",{"username":"housekeeper","password":"supersecret123"},"housekeeping")
        self.assertEqual(s,200);self.__class__.hcsrf=out["csrf"]
        self.assertEqual(self.req("GET","/api/ops/overview",who="housekeeping")[0],200)
        self.assertEqual(self.req("POST","/api/ops/attendance/clock-in",{},"housekeeping")[0],200)
        self.assertEqual(self.req("POST","/api/ops/attendance/clock-in",{},"housekeeping")[0],409)
        self.assertEqual(self.req("POST","/api/ops/attendance/clock-out",{},"housekeeping")[0],200)
        self.assertTrue(self.req("GET","/api/ops/overview",who="housekeeping")[1]["attendance"][0]["clock_out"])
        self.assertEqual(self.req("GET","/api/rooms",who="housekeeping")[0],403)
        self.assertEqual(self.req("POST","/api/ops/payroll",{"employee_id":e["id"],"pay_period":"2026-11","amount":30000,"paid_on":self.start},"housekeeping")[0],403)
        self.assertEqual(self.req("POST","/api/ops/leaves",{"employee_id":e["id"],"leave_type":"事假","start_date":self.start,"end_date":self.end})[0],201)
        ov=self.req("GET","/api/ops/overview")[1]
        self.assertEqual(self.req("PATCH",f"/api/ops/leaves/{ov['leaves'][0]['id']}",{"status":"approved"})[0],200)
        self.assertEqual(self.req("POST","/api/ops/training",{"employee_id":e["id"],"title":"Safety","training_date":self.start})[0],201)
        self.assertEqual(self.req("POST","/api/ops/payroll",{"employee_id":e["id"],"pay_period":"2026-11","amount":30000,"paid_on":self.start})[0],201)
        self.assertEqual(self.req("POST","/api/ops/payroll",{"employee_id":e["id"],"pay_period":"2026-11","amount":30000,"paid_on":self.start})[0],409)
    def test_04_services_billing_checkout(self):
        rid=self.booking_id
        s, req=self.req("POST","/api/portal/requests",{"reservation_id":rid,"request_type":"check_in"},"guest")
        self.assertEqual(s,201)
        self.assertEqual(self.req("PATCH",f"/api/ops/requests/{req['id']}",{"status":"approved"},"housekeeping")[0],403)
        self.assertEqual(self.req("PATCH",f"/api/ops/requests/{req['id']}",{"status":"approved"})[0],200)
        s,sid=self.req("POST","/api/portal/services",{"reservation_id":rid,"kind":"food","quantity":2,"note":"不辣"},"guest")
        self.assertEqual(s,201)
        self.assertEqual(self.req("PATCH",f"/api/ops/services/{sid['id']}",{"status":"completed"},"housekeeping")[0],200)
        orders=self.req("GET","/api/reservations")[1]
        r=next(x for x in orders if x["id"]==rid)
        self.assertEqual(r["bill_amount"],r["total_amount"]+600)
        self.assertEqual(self.req("POST",f"/api/reservations/{rid}/check-out")[0],400)
        self.assertEqual(self.req("POST","/api/payments",{"reservation_id":rid,"amount":r["total_amount"],"method":"cash"})[0],201)
        self.assertEqual(self.req("POST",f"/api/reservations/{rid}/check-out")[0],400)
        self.assertEqual(self.req("POST","/api/payments",{"reservation_id":rid,"amount":600,"method":"cash"})[0],201)
        s,req=self.req("POST","/api/portal/requests",{"reservation_id":rid,"request_type":"check_out"},"guest")
        self.assertEqual(s,201)
        self.assertEqual(self.req("PATCH",f"/api/ops/requests/{req['id']}",{"status":"approved"})[0],200)
        self.assertEqual(self.req("GET","/api/portal/requests",who="guest")[1][0]["status"],"approved")
        self.assertEqual(self.req("PATCH",f"/api/ops/rooms/{self.room['id']}/housekeeping",{"housekeeping":"clean"},"housekeeping")[0],200)
        self.assertEqual(self.req("GET","/api/portal/payments",who="guest")[0],200)
    def test_05_support(self):
        s,reply=self.req("POST","/api/portal/tickets",{"subject":"房間","message":"加一條毛巾"},"guest")
        self.assertEqual(s,201)
        self.assertEqual(self.req("PATCH",f"/api/ops/tickets/{reply['id']}",{"status":"replied","reply":"收到"},"housekeeping")[0],403)
        self.assertEqual(self.req("PATCH",f"/api/ops/tickets/{reply['id']}",{"status":"replied","reply":"收到"})[0],200)
        self.assertEqual(self.req("GET","/api/portal/tickets",who="guest")[1][0]["reply"],"收到")
    def test_06_migration_non_destructive(self):
        before=self.req("GET","/api/reservations")[1]
        server.init_db()
        self.assertEqual(before,self.req("GET","/api/reservations")[1])
        self.assertEqual(self.req("GET","/api/ops/overview")[1]["employees"][0]["id"],self.emp_id)

    def test_07_edit_delete_shifts(self):
        # Editing a shift updates all linked employees and persists across restarts.
        self.assertEqual(self.req("PUT","/api/ops/shifts/1",{"name":"早班調整","start_time":"08:30","end_time":"16:30"},"housekeeping")[0],403)
        self.assertEqual(self.req("PUT","/api/ops/shifts/1",{"name":"中班","start_time":"08:30","end_time":"16:30"})[0],409)
        self.assertEqual(self.req("PUT","/api/ops/shifts/1",{"name":"早班調整","start_time":"99:99","end_time":"16:30"})[0],400)
        self.assertEqual(self.req("PUT","/api/ops/shifts/99999",{"name":"不存在","start_time":"08:30","end_time":"16:30"})[0],404)
        self.assertEqual(self.req("PUT","/api/ops/shifts/1",{"name":"早班調整","start_time":"08:30","end_time":"16:30"})[0],200)
        s,ov=self.req("GET","/api/ops/overview")
        self.assertEqual(s,200)
        self.assertEqual(next(x for x in ov["employees"] if x["id"]==self.emp_id)["shift_name"],"早班調整")
        self.assertEqual(self.req("DELETE","/api/ops/shifts/1")[0],409)
        s,r=self.req("POST","/api/ops/shifts",{"name":"臨時班","start_time":"09:00","end_time":"17:00"})
        self.assertEqual(s,201)
        ov=self.req("GET","/api/ops/overview")[1]
        sid=next(x["id"] for x in ov["shifts"] if x["name"]=="臨時班")
        self.assertEqual(self.req("DELETE",f"/api/ops/shifts/{sid}",who="housekeeping")[0],403)
        self.assertEqual(self.req("DELETE",f"/api/ops/shifts/{sid}")[0],200)
        self.assertEqual(self.req("DELETE",f"/api/ops/shifts/{sid}")[0],404)
        server.init_db()
        ov=self.req("GET","/api/ops/overview")[1]
        names=[x["name"] for x in ov["shifts"]]
        self.assertIn("早班調整",names)
        self.assertNotIn("早班",names)
        self.assertNotIn("臨時班",names)
        self.assertTrue(any(x["id"]==self.emp_id for x in ov["employees"]))

    def test_08_student_discount_is_server_calculated(self):
        room=self.req("GET","/api/rooms")[1][1]
        start=(server.today()+timedelta(days=14)).isoformat()
        end=(server.today()+timedelta(days=16)).isoformat()
        payload={"room_id":room["id"],"check_in":start,"check_out":end,"adults":1,"children":0,"student_discount":True,"student_name":"測試顧客","student_school":"示範大學","student_valid_until":(server.today()+timedelta(days=200)).isoformat()}
        s,r=self.req("POST","/api/portal/book",payload,"guest")
        self.assertEqual(s,201)
        rid=r["id"]
        orders=self.req("GET","/api/portal/reservations",who="guest")[1]
        order=next(x for x in orders if x["id"]==rid)
        full=2*room["price"]
        self.assertEqual(order["discount_type"],"student")
        self.assertEqual(order["discount_amount"],round(full*.10))
        self.assertEqual(order["total_amount"],full-round(full*.10))
        # Unexpected discount value is never accepted as a client supplied price.
        self.assertEqual(self.req("POST","/api/portal/book",{**payload,"room_id":3,"student_discount":"yes"},"guest")[0],400)
        server.init_db()
        orders=self.req("GET","/api/portal/reservations",who="guest")[1]
        self.assertEqual(next(x for x in orders if x["id"]==rid)["discount_amount"],round(full*.10))

    def test_09_only_standard_student_discount_and_arrival(self):
        rooms=self.req("GET","/api/rooms")[1]
        standard=next(x for x in rooms if x["room_type"]=="standard")
        deluxe=next(x for x in rooms if x["room_type"]=="deluxe")
        suite=next(x for x in rooms if x["room_type"]=="suite")
        start=(server.today()+timedelta(days=30)).isoformat()
        end=(server.today()+timedelta(days=31)).isoformat()
        base={"check_in":start,"check_out":end,"adults":1,"children":0}
        for room in (deluxe,suite):
            s,msg=self.req("POST","/api/portal/book",{**base,"room_id":room["id"],"student_discount":True,"student_name":"測試顧客","student_school":"示範大學","student_valid_until":(server.today()+timedelta(days=200)).isoformat()},"guest")
            self.assertEqual(s,400)
            self.assertIn("僅適用標準",msg["error"])
        s,res=self.req("POST","/api/portal/book",{**base,"room_id":deluxe["id"],"student_discount":False,"expected_arrival_time":"20:00"},"guest")
        self.assertEqual(s,201)
        orders=self.req("GET","/api/portal/reservations",who="guest")[1]
        r=next(x for x in orders if x["id"]==res["id"])
        self.assertEqual(r["total_amount"],deluxe["price"])
        self.assertEqual(r["discount_type"],"none")
        self.assertEqual(r["expected_arrival_time"],"20:00")
        self.assertEqual(self.req("POST","/api/portal/book",{**base,"room_id":standard["id"],"expected_arrival_time":"02:00"},"guest")[0],400)
        s,res=self.req("POST","/api/portal/book",{**base,"room_id":standard["id"],"student_discount":True,"student_name":"測試顧客","student_school":"示範大學","student_valid_until":(server.today()+timedelta(days=200)).isoformat(),"expected_arrival_time":"21:00"},"guest")
        self.assertEqual(s,201)
        orders=self.req("GET","/api/portal/reservations",who="guest")[1]
        r=next(x for x in orders if x["id"]==res["id"])
        self.assertEqual(r["discount_amount"],round(standard["price"]*0.1))
        self.assertEqual(r["expected_arrival_time"],"21:00")
        # Back office moving a student booking to a deluxe room removes the discount.
        admin_payload={"guest_id":r["guest_id"],"room_id":suite["id"],"check_in":start,"check_out":end,"adults":1,"children":0,"requests":""}
        self.assertEqual(self.req("PUT",f"/api/reservations/{r['id']}",admin_payload)[0],200)
        updated=next(x for x in self.req("GET","/api/reservations")[1] if x["id"]==r["id"])
        self.assertEqual(updated["discount_type"],"none")
        self.assertEqual(updated["discount_amount"],0)
        self.assertEqual(updated["total_amount"],suite["price"])
        server.init_db()  # migrations should remain idempotent
        updated=next(x for x in self.req("GET","/api/portal/reservations",who="guest")[1] if x["id"]==r["id"])
        self.assertEqual(updated["expected_arrival_time"],"21:00")


    def test_10_checkout_requires_review_and_no_duplicate_payment(self):
        room=next(r for r in self.req("GET","/api/rooms")[1] if r["room_type"]=="standard")
        start=(server.today()+timedelta(days=65)).isoformat()
        end=(server.today()+timedelta(days=66)).isoformat()
        base={"room_id":room["id"],"check_in":start,"check_out":end,"adults":1,"children":0,
              "student_discount":True,"student_name":"測試顧客","student_school":"臺灣示範大學",
              "student_valid_until":(server.today()+timedelta(days=400)).isoformat()}
        s,r=self.req("POST","/api/portal/book",base,"guest")
        self.assertEqual(s,201);rid=r["id"]
        self.assertEqual(self.req("GET",f"/api/portal/checkout?reservation_id={rid}",who="guest")[1]["verification_status"],"pending")
        self.assertEqual(self.req("POST","/api/portal/pay",{"reservation_id":rid,"method":"demo_card"},"guest")[0],409)
        self.assertEqual(self.req("POST","/api/student-review",{"reservation_id":rid,"status":"approved"},"housekeeping")[0],403)
        self.assertEqual(self.req("POST","/api/student-review",{"reservation_id":rid,"status":"approved"})[0],200)
        self.assertEqual(self.req("POST","/api/portal/pay",{"reservation_id":rid,"method":"demo_card","card_number":"4111111111111111"},"guest")[0],200)
        self.assertEqual(self.req("POST","/api/portal/pay",{"reservation_id":rid,"method":"demo_card"},"guest")[0],409)
        info=self.req("GET",f"/api/portal/checkout?reservation_id={rid}",who="guest")[1]
        self.assertEqual(info["outstanding"],0)
        self.assertEqual(info["paid_amount"],info["total_amount"])

    def test_11_rejected_student_discount_reverts_to_full_price(self):
        room=next(r for r in self.req("GET","/api/rooms")[1] if r["room_type"]=="standard")
        start=(server.today()+timedelta(days=75)).isoformat()
        end=(server.today()+timedelta(days=76)).isoformat()
        base={"room_id":room["id"],"check_in":start,"check_out":end,"adults":1,"children":0,"student_discount":True,
              "student_name":"測試顧客","student_school":"示範大學","student_valid_until":(server.today()+timedelta(days=400)).isoformat()}
        self.assertEqual(self.req("POST","/api/portal/book",{k:v for k,v in base.items() if k!="student_school"},"guest")[0],400)
        s,r=self.req("POST","/api/portal/book",base,"guest");self.assertEqual(s,201)
        rid=r["id"]
        self.assertEqual(self.req("POST","/api/student-review",{"reservation_id":rid,"status":"rejected"})[0],200)
        info=self.req("GET",f"/api/portal/checkout?reservation_id={rid}",who="guest")[1]
        self.assertEqual(info["total_amount"],room["price"])
        self.assertEqual(info["discount_amount"],0)
        self.assertEqual(self.req("POST","/api/portal/pay",{"reservation_id":rid,"method":"demo_transfer"},"guest")[0],200)

if __name__=="__main__":unittest.main()
