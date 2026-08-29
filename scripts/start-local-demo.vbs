Option Explicit

Dim shell, fileSystem, scriptsDirectory, backendCommand, frontendCommand
Set shell = CreateObject("WScript.Shell")
Set fileSystem = CreateObject("Scripting.FileSystemObject")

scriptsDirectory = fileSystem.GetParentFolderName(WScript.ScriptFullName)
backendCommand = """" & fileSystem.BuildPath(scriptsDirectory, "start-local-backend.cmd") & """"
frontendCommand = """" & fileSystem.BuildPath(scriptsDirectory, "start-local-frontend.cmd") & """"

If Not IsPortListening(8000) Then shell.Run backendCommand, 0, False
If Not IsPortListening(5173) Then shell.Run frontendCommand, 0, False

Function IsPortListening(port)
  Dim check
  Set check = shell.Exec("cmd.exe /d /c netstat -ano | findstr /R /C:"":" & port & " .*LISTENING"" >nul")
  Do While check.Status = 0
    WScript.Sleep 25
  Loop
  IsPortListening = (check.ExitCode = 0)
End Function
