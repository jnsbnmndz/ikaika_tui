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

; A DEBUG BUILD IS A SEPARATE INSTALL, NOT A REPLACEMENT
;
; Everything that identifies an install derives from INSTALL_SLUG: the directory, the
; Add/Remove entry, the settings key, the Start Menu folder. One define, so the four
; cannot end up disagreeing about which install is which.
;
; This is not tidiness. UNINSTALL_KEY was shared, and UninstallPrevious reads it - so
; installing a debug build ran the RELEASE build's uninstaller, took its PATH entry with
; it, and then installed the debug tree into the release's directory. One name, two
; products, and the second one silently ate the first.
;
; The version stays out of all four. A per-version directory would leave every build ever
; installed on the disk, and an upgrade would have nothing to find and replace.
!ifdef RELEASED
  !define BUILD_KIND "release"
  !define INSTALL_SLUG "${APP_NAME}"
  !define DISPLAY_NAME "${APP_TITLE}"
!else
  !define BUILD_KIND "debug"
  !define INSTALL_SLUG "${APP_NAME}-debug"
  ; Named in the title bar, in Add/Remove Programs and on the Start Menu, because two
  ; entries differing only in a version number is a choice nobody can make.
  !define DISPLAY_NAME "${APP_TITLE} (debug)"
!endif

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
; ${WM_SETTEXT}, for retitling the window when this turns out to be an update. The
; `Caption` command is compile-time and one installer serves both cases.
!include "WinMessages.nsh"
; ${SF_SELECTED} and SectionSetFlags, for restoring an update's previous choices.
!include "Sections.nsh"
; ${GetSize}, used below for the Add/Remove size. Not built in - without this the
; compiler reports it as an invalid command rather than an undefined macro.
!include "FileFunc.nsh"
!define MUI_ABORTWARNING
; Turns the highlighted component's description into the box on the components page.
!define MUI_COMPONENTSPAGE_SMALLDESC
!define MUI_FINISHPAGE_RUN "$INSTDIR\${EXE_NAME}"
!define MUI_FINISHPAGE_RUN_TEXT "Open ${DISPLAY_NAME}"
!ifdef RELEASED
!define MUI_FINISHPAGE_TEXT "${DISPLAY_NAME} ${VERSION} is installed.$\r$\n$\r$\n\
Open a new terminal and type  ${APP_NAME}  to start it.$\r$\n\
An already-open terminal will not have picked up the change yet."
!else
; No command to promise: see the PATH block below for why a debug build stays off it.
!define MUI_FINISHPAGE_TEXT "${DISPLAY_NAME} ${VERSION} is installed, beside your \
release build rather than over it.$\r$\n$\r$\n\
Start it from the Start Menu, or run it directly:$\r$\n\
$INSTDIR\${EXE_NAME}"
!endif

; Both pages ask whether this is an update before they draw, which is why the value is
; read in .onInit rather than in the section that uses it.
!define MUI_PAGE_CUSTOMFUNCTION_PRE SkipDirectoryWhenUpdating
!insertmacro MUI_PAGE_DIRECTORY
; Skipped on an update for the same reason the directory page is: the answers are
; already recorded, and .onInit has put them back.
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

; WHAT THE THREE OPTIONAL SECTIONS ARE FOR
;
; The shortcuts and the PATH entry are the three things this installer does OUTSIDE its
; own directory, and every one of them was unconditional. A components page is the
; smallest honest way to offer them: three checkboxes, each named after what it touches.
;
; Their state is REMEMBERED. An update skips the page - the answers are already given -
; and .onInit puts the recorded ones back before any section runs, which is also what
; makes a silent update (`/S`, how the in-app updater installs) keep the choices somebody
; made in the GUI rather than reverting to these defaults.
;
; Desktop is off by default and the other two are on. A terminal application is started by
; typing its name; a desktop icon for one is clutter for most people and the point for
; some, which is exactly what a checkbox is for.

; Read once, before the first page. Read from SETTINGS_KEY rather than from the uninstall
; key: this is the same value $INSTDIR is recovered from, so the two cannot disagree about
; whether there is an install here.
Function .onInit
  ReadRegStr $PreviousVersion HKCU "${SETTINGS_KEY}" "Version"
  StrCpy $Updating "0"
  StrCmp $PreviousVersion "" +2
    StrCpy $Updating "1"

  ; An update reuses what was chosen last time. Read before any page and before any
  ; section, so it holds for a silent run too.
  StrCmp $Updating "1" 0 defaultsStand
    Call RestoreChoice
  defaultsStand:

  ; The command line wins over both, so an unattended install can still say. Applied
  ; last for that reason. ${GetOptions} sets the error flag when a switch is absent, so
  ; each is cleared first.
  ClearErrors
  ${GetParameters} $R0
  ${GetOptions} $R0 "/NOPATH" $R1
  IfErrors +2 0
    !insertmacro UnselectSection ${SecPath}
  ClearErrors
  ${GetOptions} $R0 "/PATH" $R1
  IfErrors +2 0
    !insertmacro SelectSection ${SecPath}
  ClearErrors
  ${GetOptions} $R0 "/NOSHORTCUTS" $R1
  IfErrors +3 0
    !insertmacro UnselectSection ${SecStartMenu}
    !insertmacro UnselectSection ${SecDesktop}
FunctionEnd

; Put a recorded choice back onto its section. A value that was never written leaves the
; default alone - which is what a first install after an upgrade from a version that did
; not record anything looks like.
!macro RestoreOne KEY SECTION
  ReadRegStr $R0 HKCU "${SETTINGS_KEY}" "${KEY}"
  StrCmp $R0 "1" 0 +3
    !insertmacro SelectSection ${SECTION}
    Goto done_${KEY}
  StrCmp $R0 "0" 0 +2
    !insertmacro UnselectSection ${SECTION}
  done_${KEY}:
!macroend

Function RestoreChoice
  !insertmacro RestoreOne "OnPath" ${SecPath}
  !insertmacro RestoreOne "StartMenu" ${SecStartMenu}
  !insertmacro RestoreOne "Desktop" ${SecDesktop}
FunctionEnd

Function SkipComponentsWhenUpdating
  StrCmp $Updating "1" 0 shown
    Abort
  shown:
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

; Required, and named so the components page says what it is rather than "Install".
; `!` makes it bold; SectionIn RO takes the checkbox away, because there is no version of
; this install that does not install the program.
Section "!${DISPLAY_NAME}" SecCore
  SectionIn RO
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
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayName" "${DISPLAY_NAME}"
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

  WriteUninstaller "$INSTDIR\Uninstall.exe"
  ; Recorded here rather than in each optional section, so a section that is NOT
  ; selected still writes its "0" - which is what an update reads back to keep the
  ; choice. Written from the section flags, so the command-line switches, the page and
  ; the restored values all arrive through one path.
  Call RecordChoice
SectionEnd

Section "Start Menu shortcut" SecStartMenu
  CreateDirectory "$SMPROGRAMS\${DISPLAY_NAME}"
  CreateShortcut "$SMPROGRAMS\${DISPLAY_NAME}\${DISPLAY_NAME}.lnk" "$INSTDIR\${EXE_NAME}"
  CreateShortcut "$SMPROGRAMS\${DISPLAY_NAME}\Uninstall ${DISPLAY_NAME}.lnk" "$INSTDIR\Uninstall.exe"
SectionEnd

; Unselected by default - see the note above .onInit.
Section /o "Desktop shortcut" SecDesktop
  CreateShortcut "$DESKTOP\${DISPLAY_NAME}.lnk" "$INSTDIR\${EXE_NAME}"
SectionEnd

; AFTER the files, so a failure here leaves a working install rather than a PATH entry
; pointing at a directory that was never populated. Section order is execution order,
; which is what puts it here rather than a comment asking for it.
;
; A RELEASE IS SELECTED BY DEFAULT AND A DEBUG BUILD IS NOT
;
; Both install an executable of the same name, so two of them on PATH means the command
; means whichever directory comes first. That order changes when anything else edits
; PATH, it is invisible from the prompt, and the wrong answer looks exactly like the
; right one - which is worse than having to type a path.
!ifdef RELEASED
Section "Add to PATH" SecPath
!else
Section /o "Add to PATH (release build already owns this name)" SecPath
!endif
  InitPluginsDir
  File "/oname=$PLUGINSDIR\path-entry.ps1" "${PATH_SCRIPT}"
  !insertmacro EditPath add
SectionEnd

; One place that turns section flags into the three recorded values.
!macro RecordOne KEY SECTION
  SectionGetFlags ${SECTION} $R0
  IntOp $R0 $R0 & ${SF_SELECTED}
  IntCmp $R0 ${SF_SELECTED} 0 +3 0
    WriteRegStr HKCU "${SETTINGS_KEY}" "${KEY}" "1"
    Goto recorded_${KEY}
  WriteRegStr HKCU "${SETTINGS_KEY}" "${KEY}" "0"
  recorded_${KEY}:
!macroend

Function RecordChoice
  !insertmacro RecordOne "OnPath" ${SecPath}
  !insertmacro RecordOne "StartMenu" ${SecStartMenu}
  !insertmacro RecordOne "Desktop" ${SecDesktop}
FunctionEnd

; What the components page says about each line when it is highlighted.
!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecCore} "The application itself. Required."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecStartMenu} "A Start Menu entry, with an uninstall shortcut beside it."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecDesktop} "An icon on your desktop."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecPath} "Add the install folder to your user PATH, so  ${APP_NAME}  starts it from any new terminal."
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Section "Uninstall"
  ; BEFORE the tree is deleted, while $INSTDIR is still the thing being removed.
  ; Unconditional: the entry is removed whether or not this install put it there,
  ; because path-entry.ps1 is a no-op when the directory is not on PATH, and the
  ; alternative is trusting a registry value an upgrade may have rewritten.
  InitPluginsDir
  File "/oname=$PLUGINSDIR\path-entry.ps1" "${PATH_SCRIPT}"
  !insertmacro EditPath remove

  ; Unconditional, like the PATH entry above and for the same reason: deleting a
  ; shortcut that is not there is a no-op, and trusting a registry value an upgrade may
  ; have rewritten is how a shortcut outlives the program it points at.
  Delete "$SMPROGRAMS\${DISPLAY_NAME}\${DISPLAY_NAME}.lnk"
  Delete "$SMPROGRAMS\${DISPLAY_NAME}\Uninstall ${DISPLAY_NAME}.lnk"
  RMDir "$SMPROGRAMS\${DISPLAY_NAME}"
  Delete "$DESKTOP\${DISPLAY_NAME}.lnk"

  ; The whole tree, because everything in it was written by the installer. Settings live
  ; under the user's home rather than here, so nothing anybody typed is in this directory.
  RMDir /r "$INSTDIR"

  DeleteRegKey HKCU "${UNINSTALL_KEY}"
  DeleteRegKey HKCU "${SETTINGS_KEY}"

  ; Said rather than done. That directory holds the settings, the remembered tabs and the
  ; script repositories cloned for editing - somebody's work, which an uninstaller has no
  ; business deleting to tidy up after itself. Named so that leaving it is a decision the
  ; user can see and act on rather than a surprise they find later.
  ;
  ; It is also SHARED: the release build and the debug build install to separate
  ; directories but read the same store, because the app derives it from its own name and
  ; not from which build it is. So removing it here would take the other install's
  ; settings and tabs with it, which is a second reason on top of the first.
  DetailPrint "Left in place: $PROFILE\.${APP_NAME} - settings, tabs and cloned scripts,"
  DetailPrint "  shared with the other build if you have one installed."
  DetailPrint "Delete that folder by hand if you want nothing left behind."
SectionEnd
