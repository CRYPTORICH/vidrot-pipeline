' Start the vidrot console with no console window.
' Put a shortcut to this file on the desktop. Do not copy the file itself:
' a shortcut still points here, so the paths keep working.
Option Explicit

Dim shell, fso, here, root, server, chosen, cmd, http, tries
Set shell = CreateObject("Wscript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
root = fso.GetParentFolderName(here)
server = root & "\console\server.py"

' pyw is the windowless Python launcher. Window style 0 stays hidden.
' Prefer 3.11 (the PC this was built on), then any windowless Python.
chosen = PickPython(shell)
If chosen = "" Then
  MsgBox "Python was not found." & vbCrLf & vbCrLf & "Install Python 3.11 from python.org and leave the py launcher enabled, then double-click this shortcut again.", 16, "vidrot.ai"
  WScript.Quit 1
End If

cmd = chosen & " """ & server & """"
shell.Run cmd, 0, False

' Wait until the page answers, then open the browser. A second double-click
' just opens the browser if the app is already running.
tries = 0
Do While tries < 25
  WScript.Sleep 400
  On Error Resume Next
  Set http = CreateObject("MSXML2.XMLHTTP")
  http.Open "GET", "http://127.0.0.1:8765/api/state", False
  http.Send
  If Err.Number = 0 Then
    If http.Status = 200 Then Exit Do
  End If
  Err.Clear
  tries = tries + 1
Loop

shell.Run "http://127.0.0.1:8765/", 1, False

Function PickPython(shell)
  Dim names, i, code
  names = Array("pyw -3.11", "pyw", "pythonw")
  For i = 0 To UBound(names)
    code = shell.Run(names(i) & " -c ""import sys""", 0, True)
    If code = 0 Then
      PickPython = names(i)
      Exit Function
    End If
  Next
  PickPython = ""
End Function
