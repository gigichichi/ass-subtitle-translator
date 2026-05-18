Option Explicit
' Starts GUI without a black CMD window. Pick ONE active "cmd = ..." (others commented with ').
Dim sh, fso, baseDir, scriptPath, cmd
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
baseDir = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = baseDir
scriptPath = fso.BuildPath(baseDir, "subtitle_gui.py")

' --- Option A: Python launcher (needs pyw on PATH) ---
' cmd = "pyw.exe -3 """ & scriptPath & """"

' --- Option B: Anaconda / full path (must be pythonw.exe for no black window; same folder as python.exe) ---
' VBScript quotes: """path\to\pythonw.exe"" """ & scriptPath & """"  means:  "exe" "script.py"
cmd = """D:\anaconda\pythonw.exe"" """ & scriptPath & """"

' --- Option C: other install (edit path from CMD: where pythonw) ---
' cmd = """C:\Users\YOUR_NAME\AppData\Local\Programs\Python\Python312\pythonw.exe"" """ & scriptPath & """"

sh.Run cmd, 0, False
