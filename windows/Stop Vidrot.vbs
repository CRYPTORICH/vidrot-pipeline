' Ask the running console to exit. No console window.
Option Explicit
Dim http
Set http = CreateObject("MSXML2.XMLHTTP")
On Error Resume Next
http.Open "POST", "http://127.0.0.1:8765/api/shutdown", False
http.Send ""
