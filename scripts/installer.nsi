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
; AN UPGRADE SAYS SO, AND DOES NOT ASK WHERE TO INSTALL
;
; A first install and an update are the same files landing in the same place, and they are
; not the same event to the person watching. "Choose Install Location", with a destination
; folder and a Browse button, is a question on a first install and a trap on an update: the
; answer is already settled - $INSTDIR comes back out of SETTINGS_KEY\InstallDir - and a
; browse to somewhere else would leave the old copy installed, on PATH, and first in line.
;
; So the directory page is skipped when a version is already recorded, the page headers say
; Update rather than Install, and the details log names the version being replaced.
; $PreviousVersion is read once in .onInit, before any page could ask about it.
;
;
; WHAT AN UNINSTALL DELIBERATELY LEAVES
;
; Everything under the user's home: settings, remembered tabs, and the script repositories
; cloned into ~/.dti - which are the copies the user EDITS. Removing those would be
; deleting somebody's work to tidy up after a program, so the uninstaller says what it is
; leaving instead of taking it.
;
; The downloaded installers under ~/.dti/updates are the one thing there that is genuinely
; rubbish, and they are not removed here either: this installer cannot tell a stale one
; from the copy currently being offered. The app sweeps them itself at the only moment
; anything knows the difference - see `application/updates.py`.
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
; ${WM_SETTEXT}, for retitling the window when this turns out to be an update. The
; `Caption` command is compile-time and one installer serves both cases.
!include "WinMessages.nsh"
; ${GetSize}, used below for the Add/Remove size. Not built in - without this the
; compiler reports it as an invalid command rather than an undefined macro.
!include "FileFunc.nsh"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\${EXE_NAME}"
!define MUI_FINISHPAGE_RUN_TEXT "Open ${APP_TITLE}"
!define MUI_FINISHPAGE_TEXT "${APP_TITLE} ${VERSION} is installed.$\r$\n$\r$\n\
Open a new terminal and type  ${APP_NAME}  to start it.$\r$\n\
An already-open terminal will not have picked up the change yet."

; Both pages ask whether this is an update before they draw, which is why the value is
; read in .onInit rather than in the section that uses it.
!define MUI_PAGE_CUSTOMFUNCTION_PRE SkipDirectoryWhenUpdating
!insertmacro MUI_PAGE_DIRECTORY
!define MUI_PAGE_CUSTOMFUNCTION_PRE SayWhichThisIs
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Var PreviousVersion
Var Updating

; Read once, before the first page. Read from SETTINGS_KEY rather than from the uninstall
; key: this is the same value $INSTDIR is recovered from, so the two cannot disagree about
; whether there is an install here.
Function .onInit
  ReadRegStr $PreviousVersion HKCU "${SETTINGS_KEY}" "Version"
  StrCpy $Updating "0"
  StrCmp $PreviousVersion "" +2
    StrCpy $Updating "1"
FunctionEnd

; The location is settled on an update, so the page that asks about it is not shown.
; Abort from a PRE function skips the page rather than cancelling the installer.
;
; The caption is retitled here too, and the placement took two attempts worth recording.
; NOT .onInit: $HWNDPARENT is not a window yet, so the SendMessage goes nowhere and fails
; silently - the value is read, the branch is taken, and the title bar still says Setup.
; NOT .onGUIInit either: MUI2 defines that function itself, and a second one is a compile
; error ("Function named .onGUIInit already exists"), which at least says so out loud.
; This is the first page callback, it runs before anything is drawn, and it runs whether or
; not the page it belongs to is shown.
;
; Retitled at all because `Caption` is compile-time and one installer serves both events.
Function SkipDirectoryWhenUpdating
  StrCmp $Updating "1" 0 shown
    SendMessage $HWNDPARENT ${WM_SETTEXT} 0 "STR:${APP_TITLE} ${VERSION} Update"
    Abort
  shown:
FunctionEnd

Function SayWhichThisIs
  StrCmp $Updating "1" 0 installing
    !insertmacro MUI_HEADER_TEXT "Updating ${APP_TITLE}" \
      "Replacing $PreviousVersion with ${VERSION}."
    Goto done
  installing:
    !insertmacro MUI_HEADER_TEXT "Installing ${APP_TITLE}" \
      "Setting up ${APP_TITLE} ${VERSION}."
  done:
FunctionEnd

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
  ; Labels rather than relative jumps. A `+3` here is correct until somebody inserts a
  ; line above it, and then it is silently one instruction wrong.
  StrCmp $Updating "1" 0 sayInstalling
    DetailPrint "Updating $PreviousVersion to ${VERSION} in $INSTDIR"
    Goto saidWhich
  sayInstalling:
    DetailPrint "Installing ${VERSION} in $INSTDIR"
  saidWhich:

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

  ; Said rather than done. That directory holds the settings, the remembered tabs and the
  ; script repositories cloned for editing - somebody's work, which an uninstaller has no
  ; business deleting to tidy up after itself. Named so that leaving it is a decision the
  ; user can see and act on rather than a surprise they find later.
  DetailPrint "Left in place: $PROFILE\.${APP_NAME} - settings, tabs and cloned scripts."
  DetailPrint "Delete that folder by hand if you want nothing left behind."
SectionEnd
