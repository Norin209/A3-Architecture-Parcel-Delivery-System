Option Explicit
Dim shell, files, folder, python, command
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
folder = files.GetParentFolderName(WScript.ScriptFullName)
python = shell.ExpandEnvironmentStrings("%APPDATA%") & "\uv\python\cpython-3.11.16-windows-x86_64-none\pythonw.exe"
If files.FileExists(python) Then
    command = Chr(34) & python & Chr(34)
Else
    command = "pyw -3"
End If
shell.CurrentDirectory = folder
On Error Resume Next
shell.Run command & " " & Chr(34) & folder & "\run_ui.pyw" & Chr(34), 0, False
If Err.Number <> 0 Then
    MsgBox "Python could not be started. Install Python 3.11 or newer, or run python run_ui.py from this folder.", 48, "Your Order We Deliver"
End If
