"""不需第三方套件：python -m unittest discover -s tests -v"""
import http.cookiejar
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import timedelta
from pathlib import Path
from http.server import ThreadingHTTPServer
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server

class TestHotelManagement(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        server.DB_PATH=Path(cls.temp.name)/"hotel.db"
        server.init_db()
        cls.http=ThreadingHTTPServer(("127.0.0.1",0),server.HotelHandler)
        cls.base=f"http://127.0.0.1:{cls.http.server_port}"
        cls.thread=threading.Thread(target=cls.http.serve_forever,daemon=True)
        cls.thread.start()
        cls.jar=http.cookiejar.CookieJar()
        cls.opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cls.jar))
        cls.csrf=""

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown();cls.http.server_close();cls.thread.join(timeout=3);cls.temp.cleanup()

    @classmethod
    def request(cls,method,path,payload=None,opener=None,csrf=None):
        data=json.dumps(payload if payload is not None else {},ensure_ascii=False).encode() if method!="GET" else None
        headers={"Content-Type":"application/json"}
        if method!="GET": headers["X-CSRF-Token"]=cls.csrf if csrf is None else csrf
        request=urllib.request.Request(cls.base+path,method=method,data=data,headers=headers)
        try:
            with (opener or cls.opener).open(request,timeout=4) as response:
                return response.status,json.load(response)
        except urllib.error.HTTPError as e:
            return e.code,json.loads(e.read().decode())

    def test_01_initial_setup_and_auth(self):
        self.assertEqual(self.request("GET","/api/bootstrap"),(200,{"needs_setup":True}))
        outsider=urllib.request.build_opener()
        self.assertEqual(self.request("GET","/api/rooms",opener=outsider)[0],401)
        self.assertEqual(self.request("POST","/api/setup",{"username":"boss","password":"short"})[0],400)
        status,r=self.request("POST","/api/setup",{"username":"boss","password":"long-password-123"})
        self.assertEqual(status,201);self.assertTrue(r["csrf"])
        self.__class__.csrf=r["csrf"]
        self.assertEqual(self.request("GET","/api/bootstrap"),(200,{"needs_setup":False}))
        self.assertEqual(self.request("POST","/api/setup",{"username":"other","password":"long-password"})[0],409)
        self.assertEqual(self.request("GET","/api/me")[1]["username"],"boss")
        self.assertEqual(self.request("POST","/api/guests",{"full_name":"a"},csrf="bad")[0],403)
        status, rooms=self.request("GET","/api/rooms")
        self.assertEqual(status,200);self.assertEqual(len(rooms),12)

    def test_02_booking_and_payments(self):
        status,guest=self.request("POST","/api/guests",{"full_name":"小華","phone":"0912-123-456","email":"hua@example.com","document_no":"AB100","notes":"無菸房"})
        self.assertEqual(status,201)
        self.__class__.guest_id=guest["id"]
        d=server.today().isoformat();end=(server.today()+timedelta(days=2)).isoformat()
        self.__class__.dates=(d,end)
        room=self.request("GET","/api/rooms")[1][0]
        self.__class__.room_id=room["id"]
        body={"guest_id":guest["id"],"room_id":room["id"],"check_in":d,"check_out":end,"adults":2,"children":0,"requests":"高樓層"}
        status,r=self.request("POST","/api/reservations",body)
        self.assertEqual(status,201)
        self.__class__.reservation_id=r["id"]
        self.assertEqual(self.request("POST","/api/reservations",body)[0],409)
        a=self.request("GET",f"/api/rooms/available?check_in={d}&check_out={end}")[1]
        self.assertNotIn(room["id"],[r["id"] for r in a])
        self.assertEqual(self.request("POST","/api/reservations",dict(body,adults=10))[0],400)
        status,reservations=self.request("GET","/api/reservations")
        self.assertEqual(status,200)
        self.__class__.amount=reservations[0]["total_amount"]
        self.assertEqual(self.amount,room["price"]*2)
        self.assertEqual(self.request("POST",f"/api/reservations/{r['id']}/check-in")[0],200)
        self.assertEqual(self.request("POST",f"/api/reservations/{r['id']}/check-out")[0],400)
        self.assertEqual(self.request("POST","/api/payments",{"reservation_id":r["id"],"amount":1000,"method":"cash","note":"訂金"})[0],201)
        self.assertEqual(self.request("POST","/api/payments",{"reservation_id":r["id"],"amount":self.amount,"method":"card"})[0],400)
        self.assertEqual(self.request("POST","/api/payments",{"reservation_id":r["id"],"amount":self.amount-1000,"method":"card","note":"餘款"})[0],201)
        self.assertEqual(self.request("POST",f"/api/reservations/{r['id']}/check-out")[0],200)
        rows=self.request("GET","/api/rooms")[1]
        self.assertEqual(rows[0]["housekeeping"],"dirty")
        self.assertFalse(rows[0]["occupied"])
        self.assertEqual(self.request("GET","/api/dashboard")[1]["monthly_revenue"],self.amount)
        self.assertEqual(len(self.request("GET","/api/payments")[1]),2)

    def test_03_modify_cancel_and_clean(self):
        d,end=self.dates
        new_end=(server.today()+timedelta(days=1)).isoformat()
        body={"guest_id":self.guest_id,"room_id":self.room_id,"check_in":d,"check_out":new_end,"adults":1,"children":0,"requests":""}
        status,r=self.request("POST","/api/reservations",body)
        self.assertEqual(status,201)
        # 房間退房後待清潔，不能立即入住
        self.assertEqual(self.request("POST",f"/api/reservations/{r['id']}/check-in")[0],400)
        room=self.request("GET","/api/rooms")[1][0]
        update={"number":room["number"],"room_type":room["room_type"],"floor":room["floor"],"capacity":room["capacity"],"price":room["price"],"housekeeping":"clean","enabled":True}
        self.assertEqual(self.request("PUT",f"/api/rooms/{self.room_id}",update)[0],200)
        self.assertEqual(self.request("POST",f"/api/reservations/{r['id']}/cancel")[0],200)
        self.assertEqual(self.request("POST",f"/api/reservations/{r['id']}/check-in")[0],400)
        self.assertEqual(self.request("DELETE",f"/api/rooms/{self.room_id}")[0],409)
        # 資料被妥善保留，已退房不可更改
        self.assertEqual(self.request("PUT",f"/api/reservations/{self.reservation_id}",body)[0],400)

if __name__=="__main__":unittest.main()
