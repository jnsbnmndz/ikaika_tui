; Per-user Windows installer for the frozen app.
;
; RequestExecutionLevel user, installed under %LOCALAPPDATA%: a developer tool that
; demands an administrator prompt is one people install once and stop updating.
;
; A debug build is a SEPARATE install - directory, uninstall entry, settings key and
; command all derive from INSTALL_SLUG - because UNINSTALL_KEY was shared once and
; installing a debug build ran the release build's uninstaller.
;
; LABELS, NEVER RELATIVE JUMPS: `!insertmacro` is not one instruction, and a `+2` over one
; lands inside it. docs/pitfalls.md 7.2.
;
; The uninstaller is run with `_?=` so ExecWait can actually wait for it. docs/pitfalls.md
; 6.8. The PATH edit goes through scripts/lib/path-entry.ps1 and .NET, never NSIS.
;
; An update skips the directory page: the location is settled, and browsing elsewhere
; would leave the old copy installed and first on PATH.

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
!ifndef PUBLISHER
  !error "PUBLISHER is required."
!endif

!ifdef RELEASED
  !define BUILD_KIND "release"
  !define INSTALL_SLUG "${APP_NAME}"
  !define DISPLAY_NAME "${APP_TITLE}"
!else
  !define BUILD_KIND "debug"
  !define INSTALL_SLUG "${APP_NAME}-debug"
  !define DISPLAY_NAME "${APP_TITLE} (debug)"
!endif

!ifdef RELEASED
  !define COMMAND "${APP_NAME}"
!else
  !define COMMAND "${APP_NAME}-debug"
!endif
!define INSTALLED_EXE "${COMMAND}.exe"

!define UNINSTALL_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${INSTALL_SLUG}"
!define SETTINGS_KEY "Software\${PUBLISHER}\${INSTALL_SLUG}"

Name "${DISPLAY_NAME} ${VERSION}"
OutFile "${OUT_FILE}"
Unicode true
RequestExecutionLevel user
InstallDir "$LOCALAPPDATA\Programs\${INSTALL_SLUG}"
InstallDirRegKey HKCU "${SETTINGS_KEY}" "InstallDir"
SetCompressor /SOLID lzma
ShowInstDetails show
ShowUninstDetails show

VIProductVersion "${VI_VERSION}"
VIAddVersionKey "ProductName" "${DISPLAY_NAME}"
VIAddVersionKey "FileDescription" "${DISPLAY_NAME} installer"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "CompanyName" "${PUBLISHER}"
VIAddVersionKey "LegalCopyright" "${PUBLISHER}"
VIAddVersionKey "Comments" "${BUILD_KIND} build"

!include "MUI2.nsh"
!include "WinMessages.nsh"
!include "Sections.nsh"
!include "FileFunc.nsh"
!define MUI_ABORTWARNING
!define MUI_COMPONENTSPAGE_SMALLDESC
!define MUI_FINISHPAGE_RUN "$INSTDIR\${INSTALLED_EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "Open ${DISPLAY_NAME}"
!ifdef RELEASED
!define MUI_FINISHPAGE_TEXT "${DISPLAY_NAME} ${VERSION} is installed.$\r$\n$\r$\n\
Open a new terminal and type  ${COMMAND}  to start it.$\r$\n\
An already-open terminal will not have picked up the change yet."
!else
!define MUI_FINISHPAGE_TEXT "${DISPLAY_NAME} ${VERSION} is installed, beside your \
release build rather than over it.$\r$\n$\r$\n\
Open a new terminal and type  ${COMMAND}  to start it - your release build keeps \
answering to ${APP_NAME}.$\r$\n\
An already-open terminal will not have picked up the change yet."
!endif

!define MUI_PAGE_CUSTOMFUNCTION_PRE SkipDirectoryWhenUpdating
!insertmacro MUI_PAGE_DIRECTORY
!define MUI_PAGE_CUSTOMFUNCTION_PRE SkipComponentsWhenUpdating
!insertmacro MUI_PAGE_COMPONENTS
!define MUI_PAGE_CUSTOMFUNCTION_PRE SayWhichThisIs
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Var PreviousVersion
Var Updating

Function SkipComponentsWhenUpdating
  StrCmp $Updating "1" 0 shown
    Abort
  shown:
FunctionEnd

Function SkipDirectoryWhenUpdating
  StrCmp $Updating "1" 0 shown
    SendMessage $HWNDPARENT ${WM_SETTEXT} 0 "STR:${DISPLAY_NAME} ${VERSION} Update"
    Abort
  shown:
FunctionEnd

Function SayWhichThisIs
  StrCmp $Updating "1" 0 installing
    !insertmacro MUI_HEADER_TEXT "Updating ${DISPLAY_NAME}" \
      "Replacing $PreviousVersion with ${VERSION}."
    Goto done
  installing:
    !insertmacro MUI_HEADER_TEXT "Installing ${DISPLAY_NAME}" \
      "Setting up ${DISPLAY_NAME} ${VERSION} in $INSTDIR."
  done:
FunctionEnd

Function UninstallPrevious
  ReadRegStr $R0 HKCU "${UNINSTALL_KEY}" "UninstallString"
  StrCmp $R0 "" done
  ReadRegStr $R1 HKCU "${SETTINGS_KEY}" "InstallDir"
  StrCmp $R1 "" 0 +2
    StrCpy $R1 "$INSTDIR"
  DetailPrint "Removing the copy already installed..."
  ExecWait '"$R0" /S _?=$R1'
  Delete "$R1\Uninstall.exe"
  RMDir /r "$R1"
  done:
FunctionEnd

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

Section "!${DISPLAY_NAME}" SecCore
  SectionIn RO
  StrCmp $Updating "1" 0 sayInstalling
    DetailPrint "Updating $PreviousVersion to ${VERSION} in $INSTDIR"
    Goto saidWhich
  sayInstalling:
    DetailPrint "Installing ${VERSION} in $INSTDIR"
  saidWhich:

  Call UninstallPrevious

  SetOutPath "$INSTDIR"
  File /r "${SOURCE_DIR}\*.*"

!if "${INSTALLED_EXE}" != "${EXE_NAME}"
  Rename "$INSTDIR\${EXE_NAME}" "$INSTDIR\${INSTALLED_EXE}"
  DetailPrint "Installed as ${INSTALLED_EXE}, so it does not answer to ${APP_NAME}."
!endif

  WriteRegStr HKCU "${SETTINGS_KEY}" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${SETTINGS_KEY}" "Version" "${VERSION}"
  WriteRegStr HKCU "${SETTINGS_KEY}" "BuildKind" "${BUILD_KIND}"

  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayName" "${DISPLAY_NAME}"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "Publisher" "${PUBLISHER}"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayIcon" "$INSTDIR\${INSTALLED_EXE}"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "UninstallString" "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "QuietUninstallString" "$INSTDIR\Uninstall.exe /S"
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoRepair" 1
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "EstimatedSize" "$0"

  WriteUninstaller "$INSTDIR\Uninstall.exe"
  Call RecordChoice
SectionEnd

Section "Start Menu shortcut" SecStartMenu
  CreateDirectory "$SMPROGRAMS\${DISPLAY_NAME}"
  CreateShortcut "$SMPROGRAMS\${DISPLAY_NAME}\${DISPLAY_NAME}.lnk" "$INSTDIR\${INSTALLED_EXE}"
  CreateShortcut "$SMPROGRAMS\${DISPLAY_NAME}\Uninstall ${DISPLAY_NAME}.lnk" "$INSTDIR\Uninstall.exe"
SectionEnd

Section /o "Desktop shortcut" SecDesktop
  CreateShortcut "$DESKTOP\${DISPLAY_NAME}.lnk" "$INSTDIR\${INSTALLED_EXE}"
SectionEnd

Section "Add to PATH (run it by typing  ${COMMAND}  )" SecPath
  InitPluginsDir
  File "/oname=$PLUGINSDIR\path-entry.ps1" "${PATH_SCRIPT}"
  !insertmacro EditPath add
SectionEnd

; AFTER THE SECTIONS, AND THAT IS THE WHOLE POINT.
;
; `${SecPath}` and friends are defines the compiler creates when it reaches each Section.
; Declared above them, `.onInit` and RestoreChoice referenced constants that did not exist
; yet - `warning 6000: unknown variable/constant "{SecDesktop}" detected, ignoring` on
; every build - and NSIS read the literal text as section index 0, which is SecCore.
;
; So RestoreOne "Desktop", reading the recorded "0" that a desktop shortcut nobody asked
; for leaves behind, UNSELECTED THE REQUIRED COMPONENT. The installer then ran, installed
; nothing, and exited 0. docs/pitfalls.md 7.3.
Function .onInit
  ReadRegStr $PreviousVersion HKCU "${SETTINGS_KEY}" "Version"
  StrCpy $Updating "0"
  StrCmp $PreviousVersion "" +2
    StrCpy $Updating "1"

  StrCmp $Updating "1" 0 defaultsStand
    Call RestoreChoice
  defaultsStand:

  ClearErrors
  ${GetParameters} $R0
  ${GetOptions} $R0 "/NOPATH" $R1
  IfErrors noPathAbsent
    !insertmacro UnselectSection ${SecPath}
  noPathAbsent:

  ClearErrors
  ${GetOptions} $R0 "/PATH" $R1
  IfErrors pathAbsent
    !insertmacro SelectSection ${SecPath}
  pathAbsent:

  ClearErrors
  ${GetOptions} $R0 "/NOSHORTCUTS" $R1
  IfErrors shortcutsAbsent
    !insertmacro UnselectSection ${SecStartMenu}
    !insertmacro UnselectSection ${SecDesktop}
  shortcutsAbsent:
FunctionEnd

!macro RestoreOne KEY SECTION
  ReadRegStr $R0 HKCU "${SETTINGS_KEY}" "${KEY}"
  StrCmp $R0 "1" 0 notOn_${KEY}
    !insertmacro SelectSection ${SECTION}
    Goto done_${KEY}
  notOn_${KEY}:
  StrCmp $R0 "0" 0 done_${KEY}
    !insertmacro UnselectSection ${SECTION}
  done_${KEY}:
!macroend

Function RestoreChoice
  !insertmacro RestoreOne "OnPath" ${SecPath}
  !insertmacro RestoreOne "StartMenu" ${SecStartMenu}
  !insertmacro RestoreOne "Desktop" ${SecDesktop}
FunctionEnd


!macro RecordOne KEY SECTION
  SectionGetFlags ${SECTION} $R0
  IntOp $R0 $R0 & ${SF_SELECTED}
  IntCmp $R0 ${SF_SELECTED} selected_${KEY} notSelected_${KEY} notSelected_${KEY}
  selected_${KEY}:
    WriteRegStr HKCU "${SETTINGS_KEY}" "${KEY}" "1"
    Goto recorded_${KEY}
  notSelected_${KEY}:
    WriteRegStr HKCU "${SETTINGS_KEY}" "${KEY}" "0"
  recorded_${KEY}:
!macroend

Function RecordChoice
  !insertmacro RecordOne "OnPath" ${SecPath}
  !insertmacro RecordOne "StartMenu" ${SecStartMenu}
  !insertmacro RecordOne "Desktop" ${SecDesktop}
FunctionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecCore} "The application itself. Required."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecStartMenu} "A Start Menu entry, with an uninstall shortcut beside it."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecDesktop} "An icon on your desktop."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecPath} "Add the install folder to your user PATH, so  ${COMMAND}  starts it from any new terminal."
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Section "Uninstall"
  InitPluginsDir
  File "/oname=$PLUGINSDIR\path-entry.ps1" "${PATH_SCRIPT}"
  !insertmacro EditPath remove

  Delete "$SMPROGRAMS\${DISPLAY_NAME}\${DISPLAY_NAME}.lnk"
  Delete "$SMPROGRAMS\${DISPLAY_NAME}\Uninstall ${DISPLAY_NAME}.lnk"
  RMDir "$SMPROGRAMS\${DISPLAY_NAME}"
  Delete "$DESKTOP\${DISPLAY_NAME}.lnk"

  RMDir /r "$INSTDIR"

  DeleteRegKey HKCU "${UNINSTALL_KEY}"
  DeleteRegKey HKCU "${SETTINGS_KEY}"

  DetailPrint "Left in place: $PROFILE\.${APP_NAME} - settings, tabs and cloned scripts,"
  DetailPrint "  shared with the other build if you have one installed."
  DetailPrint "Delete that folder by hand if you want nothing left behind."
SectionEnd
