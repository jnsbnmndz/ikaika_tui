; The Windows installer. Compiled by scripts\build-installer.ps1, never by hand.
;
; Everything that changes per build arrives as a /D define, so this file holds no version
; and no paths. Compiling it directly will fail on the first missing one, which is the
; point: a hardcoded default here is a version that goes stale silently.
;
;   APP_NAME     what it is called on disk and in the Start Menu
;   APP_TITLE    what a person reads
;   VERSION      x.y.z+n, shown to people
;   VI_VERSION   x.y.z.n, the four-part form Windows demands of a file resource
;   SOURCE_DIR   the PyInstaller folder being packaged
;   EXE_NAME     the executable inside it
;   OUT_FILE     where to write the installer
;   RELEASED     defined only for an official build
;
;
; PER-USER, NOT PER-MACHINE
;
; RequestExecutionLevel user, installing under LOCALAPPDATA. A developer tool that demands
; an admin prompt to install is a tool people install once and stop updating, and nothing
; here needs to write outside the user's own profile. The uninstall entry therefore goes in
; HKCU - listing it in HKLM while the files are per-user gives every other account on the
; machine an Add/Remove entry for something they do not have.
;
;
; AN UPGRADE UNINSTALLS THE OLD COPY FIRST
;
; A PyInstaller folder's contents change between versions, and copying a new build over an
; old one leaves whatever the new one no longer ships. Those stale files are on the import
; path, so the app keeps loading them - which is a version somebody is running that was
; never built. The old uninstaller is run silently before anything is written.
;
;
; IT PUTS THE INSTALL DIRECTORY ON THE USER'S PATH
;
; So the app can be started by typing its name. The install directory is stable
; across versions - the FOLDER under dist carries the version, the installed one
; does not - so the entry is added once and survives every upgrade. `/NOPATH`
; skips it.
;
; THE EDIT IS NOT DONE IN NSIS, AND THAT IS NOT A STYLE CHOICE. This build reports
; NSIS_MAX_STRLEN=1024 and `ReadRegStr` truncates SILENTLY at it; writing the
; truncated value back is the well-known way an installer destroys somebody's
; PATH. On the machine this was written for, the user PATH was already 723
; characters and the merged machine+user value 1117 - past the limit before this
; installer adds anything. The EnVar plugin would solve it and is not installed.
;
; So scripts\path-entry.ps1 does it through .NET, which has no length limit and
; broadcasts WM_SETTINGCHANGE itself. It is invoked by FULL PATH out of $SYSDIR:
; the one thing that must not be assumed working while repairing PATH is PATH.

!ifndef APP_NAME
  !error "APP_NAME is required - build-installer.ps1 passes it."
!endif
!ifndef VERSION
  !error "VERSION is required."
!endif
!ifndef VI_VERSION
  !error "VI_VERSION is required - the four-part x.y.z.n form."
!endif
!ifndef SOURCE_DIR
  !error "SOURCE_DIR is required."
!endif
!ifndef EXE_NAME
  !error "EXE_NAME is required."
!endif
!ifndef OUT_FILE
  !error "OUT_FILE is required."
!endif
!ifndef PATH_SCRIPT
  !error "PATH_SCRIPT is required - the path-entry.ps1 that edits PATH."
!endif
!ifndef APP_TITLE
  !define APP_TITLE "${APP_NAME}"
!endif
; No default. The publisher names the product in Add/Remove Programs and in the
; settings key path, and a stale default there is a wrong name nothing reports.
!ifndef PUBLISHER
  !error "PUBLISHER is required."
!endif

!define UNINSTALL_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"
!define SETTINGS_KEY "Software\${PUBLISHER}\${APP_NAME}"

!ifdef RELEASED
  !define BUILD_KIND "release"
!else
  !define BUILD_KIND "debug"
!endif

Name "${APP_TITLE} ${VERSION}"
OutFile "${OUT_FILE}"
Unicode true
RequestExecutionLevel user
InstallDir "$LOCALAPPDATA\Programs\${APP_NAME}"
InstallDirRegKey HKCU "${SETTINGS_KEY}" "InstallDir"
SetCompressor /SOLID lzma
ShowInstDetails show
ShowUninstDetails show

VIProductVersion "${VI_VERSION}"
VIAddVersionKey "ProductName" "${APP_TITLE}"
VIAddVersionKey "FileDescription" "${APP_TITLE} installer"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "CompanyName" "${PUBLISHER}"
VIAddVersionKey "LegalCopyright" "${PUBLISHER}"
VIAddVersionKey "Comments" "${BUILD_KIND} build"

!include "MUI2.nsh"
; ${GetSize}, used below for the Add/Remove size. Not built in - without this the
; compiler reports it as an invalid command rather than an undefined macro.
!include "FileFunc.nsh"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\${EXE_NAME}"
!define MUI_FINISHPAGE_RUN_TEXT "Open ${APP_TITLE}"
!define MUI_FINISHPAGE_TEXT "${APP_TITLE} ${VERSION} is installed.$\r$\n$\r$\n\
Open a new terminal and type  ${APP_NAME}  to start it.$\r$\n\
An already-open terminal will not have picked up the change yet."

!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

; Silently removes whatever is installed, so a new build never lands on top of an old
; one's leftovers. Quoted with two levels because ExecWait takes one command line and the
; path can contain spaces - $LOCALAPPDATA always does under a profile with a space in it.
Function UninstallPrevious
  ReadRegStr $R0 HKCU "${UNINSTALL_KEY}" "UninstallString"
  StrCmp $R0 "" done
  ReadRegStr $R1 HKCU "${SETTINGS_KEY}" "InstallDir"
  StrCmp $R1 "" 0 +2
    StrCpy $R1 "$INSTDIR"
  DetailPrint "Removing the copy already installed..."
  ExecWait '"$R0" /S _?=$R1'
  ; _?= keeps the uninstaller in place so ExecWait can actually wait for it; without it
  ; the uninstaller copies itself to temp, returns immediately, and the new files are
  ; written while the old ones are still being deleted.
  Delete "$R1\Uninstall.exe"
  RMDir /r "$R1"
  done:
FunctionEnd

; Runs path-entry.ps1, which adds or removes $INSTDIR from the user's PATH.
;
; ExecToStack rather than Exec so the script's one line of output can be put in
; the details log: this edits something outside the install directory, and an
; installer that changes a person's PATH without saying so is one they cannot
; undo by hand. A failure is REPORTED, not fatal - the app is installed and
; runnable by full path either way, so refusing the whole install over a PATH
; entry would be the wrong trade.
!macro EditPath ACTION
  DetailPrint "PATH: ${ACTION} $INSTDIR"
  nsExec::ExecToStack '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" \
    -NoProfile -NonInteractive -ExecutionPolicy Bypass \
    -File "$PLUGINSDIR\path-entry.ps1" -Directory "$INSTDIR" -Action ${ACTION}'
  Pop $0
  Pop $1
  DetailPrint "  $1"
  StrCmp $0 "0" +2 0
    DetailPrint "  PATH was not changed (exit $0). The app still runs from $INSTDIR."
!macroend

Section "Install"
  Call UninstallPrevious

  SetOutPath "$INSTDIR"
  File /r "${SOURCE_DIR}\*.*"

  WriteRegStr HKCU "${SETTINGS_KEY}" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${SETTINGS_KEY}" "Version" "${VERSION}"
  WriteRegStr HKCU "${SETTINGS_KEY}" "BuildKind" "${BUILD_KIND}"

  ; What Add/Remove Programs reads. EstimatedSize is in KB and is what stops the entry
  ; showing a blank size, which reads as a broken install.
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayName" "${APP_TITLE}"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "Publisher" "${PUBLISHER}"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayIcon" "$INSTDIR\${EXE_NAME}"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "UninstallString" "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "QuietUninstallString" "$INSTDIR\Uninstall.exe /S"
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoRepair" 1
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "EstimatedSize" "$0"

  CreateDirectory "$SMPROGRAMS\${APP_TITLE}"
  CreateShortcut "$SMPROGRAMS\${APP_TITLE}\${APP_TITLE}.lnk" "$INSTDIR\${EXE_NAME}"
  CreateShortcut "$SMPROGRAMS\${APP_TITLE}\Uninstall ${APP_TITLE}.lnk" "$INSTDIR\Uninstall.exe"

  ; After the files, so a failure here leaves a working install rather than a
  ; PATH entry pointing at a directory that was never populated.
  ;
  ; ${GetOptions} sets the error flag when the switch is absent, so the flag is
  ; cleared first - a stale one from any earlier call would read as /NOPATH.
  ClearErrors
  ${GetParameters} $R0
  ${GetOptions} $R0 "/NOPATH" $R1
  IfErrors 0 pathSkipped
    InitPluginsDir
    File "/oname=$PLUGINSDIR\path-entry.ps1" "${PATH_SCRIPT}"
    !insertmacro EditPath add
    WriteRegStr HKCU "${SETTINGS_KEY}" "OnPath" "1"
    Goto pathDone
  pathSkipped:
    DetailPrint "PATH: skipped, /NOPATH was given"
    WriteRegStr HKCU "${SETTINGS_KEY}" "OnPath" "0"
  pathDone:

  WriteUninstaller "$INSTDIR\Uninstall.exe"
SectionEnd

Section "Uninstall"
  ; BEFORE the tree is deleted, while $INSTDIR is still the thing being removed.
  ; Unconditional: the entry is removed whether or not this install put it there,
  ; because path-entry.ps1 is a no-op when the directory is not on PATH, and the
  ; alternative is trusting a registry value an upgrade may have rewritten.
  InitPluginsDir
  File "/oname=$PLUGINSDIR\path-entry.ps1" "${PATH_SCRIPT}"
  !insertmacro EditPath remove

  Delete "$SMPROGRAMS\${APP_TITLE}\${APP_TITLE}.lnk"
  Delete "$SMPROGRAMS\${APP_TITLE}\Uninstall ${APP_TITLE}.lnk"
  RMDir "$SMPROGRAMS\${APP_TITLE}"

  ; The whole tree, because everything in it was written by the installer. Settings live
  ; under the user's home rather than here, so nothing anybody typed is in this directory.
  RMDir /r "$INSTDIR"

  DeleteRegKey HKCU "${UNINSTALL_KEY}"
  DeleteRegKey HKCU "${SETTINGS_KEY}"
SectionEnd
