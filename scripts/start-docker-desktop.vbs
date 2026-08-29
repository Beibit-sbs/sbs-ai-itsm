Option Explicit

Dim shell, fileSystem, dockerDesktop
Set shell = CreateObject("WScript.Shell")
Set fileSystem = CreateObject("Scripting.FileSystemObject")

dockerDesktop = shell.ExpandEnvironmentStrings("%ProgramFiles%") & "\Docker\Docker\Docker Desktop.exe"
If Not fileSystem.FileExists(dockerDesktop) Then
  WScript.Echo "Docker Desktop executable was not found: " & dockerDesktop
  WScript.Quit 1
End If

shell.Run """" & dockerDesktop & """", 0, False
